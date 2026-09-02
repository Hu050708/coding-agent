"""实现支持取消、输出限额和进程树清理的子进程执行。"""

from __future__ import annotations

import locale
import math
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping

from coding_agent.agents.security import PermissionPolicy, ToolApprovalRequest
from coding_agent.agents.security.command_policy import CommandDecision
from coding_agent.agents.security.workspace import Workspace

from .contracts import (
    CancellationCheck,
    ToolConfirmation,
    ToolError,
    optional_number,
    optional_string,
    reject_unknown,
)


_CANCEL_POLL_SECONDS = 0.1


class _BoundedBytes:
    """保留固定大小的头尾内容，同时统计排空的全部字节。"""

    def __init__(self, limit: int) -> None:
        """创建保留头尾片段的有界字节缓冲区。

        :param limit: 最终最多保留的字节总数，不能小于 64。
        :raises ValueError: 输出上限过小。
        """

        # 允许保留的总字节数。
        if limit < 64:
            raise ValueError("The output limit must be at least 64 bytes.")
        self.limit = limit
        self.head_limit = limit // 2
        self.tail_limit = limit - self.head_limit
        self.head = bytearray()
        self.tail = bytearray()
        self.total_bytes = 0

    def feed(self, chunk: bytes) -> None:
        """计数并吸收一块子进程输出。

        :param chunk: 从标准输出或错误输出读取的新字节块。
        """

        self.total_bytes += len(chunk)
        if len(self.head) < self.head_limit:
            take = min(self.head_limit - len(self.head), len(chunk))
            self.head.extend(chunk[:take])
            chunk = chunk[take:]
        if chunk and self.tail_limit:
            self.tail.extend(chunk)
            if len(self.tail) > self.tail_limit:
                del self.tail[: len(self.tail) - self.tail_limit]

    @property
    def truncated(self) -> bool:
        """判断子进程输出是否超过保留容量。

        :return: 至少有一个字节被省略时为 True。
        """

        return self.total_bytes > len(self.head) + len(self.tail)

    @property
    def omitted_bytes(self) -> int:
        """计算未保留在头尾片段中的字节数。

        :return: 非负的省略字节数量。
        """

        return max(0, self.total_bytes - len(self.head) - len(self.tail))

    def render(self) -> tuple[str, str]:
        """:return: 解码后的有界文本及实际采用的编码标签。"""

        if not self.truncated:
            return _decode_bytes(bytes(self.head + self.tail))

        head_text, head_encoding = _decode_bytes(bytes(self.head))
        tail_text, tail_encoding = _decode_bytes(bytes(self.tail))
        encoding = head_encoding if head_encoding == tail_encoding else f"{head_encoding}/{tail_encoding}"
        marker = f"\n... <{self.omitted_bytes} bytes omitted> ...\n"
        return head_text + marker + tail_text, encoding


class _WindowsKillJob:
    """持有关闭时会终止全部关联进程的 Windows 作业对象。"""

    def __init__(self, handle: Any, close_handle: Callable[[Any], Any]) -> None:
        """接管一个 Windows 作业句柄及其关闭函数。

        :param handle: 已关联子进程的原生 Windows 作业句柄。
        :param close_handle: 关闭句柄并触发作业进程终止的系统函数。
        """

        self._handle = handle
        self._close_handle = close_handle

    def close(self) -> bool:
        """幂等关闭 Windows 作业句柄并触发进程树终止。

        :return: 句柄已关闭或系统关闭调用成功时为 True。
        """

        handle, self._handle = self._handle, None
        if handle is None:
            return True
        try:
            return bool(self._close_handle(handle))
        except Exception:
            return False

# python test.py
def run_command(
    workspace: Workspace,
    arguments: Mapping[str, Any],
    *,
    confirm_action: ToolConfirmation | None = None,
    permission_policy: PermissionPolicy | None = None,
    cancel_check: CancellationCheck | None = None,
    max_output_bytes: int = 12_000,
    timeout_cap_seconds: float | None = None,
) -> dict[str, Any]:
    """按权限策略执行命令，并对时限、输出量及子进程树进行统一控制。

    :param workspace: 解析工作目录、可执行文件和安全环境的工作区对象。
    :param arguments: ``argv``、可选工作目录和请求超时组成的工具参数。
    :param confirm_action: 风险命令需要人工审批时调用的同步回调。
    :param permission_policy: 本次运行冻结的工具与命令权限策略。
    :param cancel_check: 执行前及执行期间检查用户取消状态的回调。
    :param max_output_bytes: 标准输出和错误输出各自允许保留的最大字节数。
    :param timeout_cap_seconds: Agent 剩余墙钟时间对本命令施加的额外上限。
    :return: 退出状态、有界输出以及耗时、截断和进程树清理元数据。
    :raises ToolError: 参数、权限、审批、超时、取消或命令退出状态不合法。
    """

    # 第一步：严格校验模型参数，并把单次命令超时压缩到运行剩余时限内。
    reject_unknown(arguments, {"argv", "cwd", "timeout_seconds"})
    argv = arguments.get("argv")
    if not isinstance(argv, list) or not argv:
        raise ToolError("invalid_argv", "argv must be a non-empty JSON array.")
    if any(not isinstance(argument, str) for argument in argv):
        raise ToolError("invalid_argv", "Every argv item must be a string.")
    cwd = optional_string(arguments, "cwd", default=".", max_length=1024)
    assert cwd is not None
    requested_timeout_seconds = optional_number(
        arguments,
        "timeout_seconds",
        default=120.0,
        minimum=0.1,
        maximum=120.0,
    )
    if max_output_bytes < 64:
        raise ToolError("invalid_output_limit", "The command output limit is too small.")
    effective_timeout_seconds = requested_timeout_seconds
    deadline_limited = False
    if timeout_cap_seconds is not None:
        if (
            isinstance(timeout_cap_seconds, bool)
            or not isinstance(timeout_cap_seconds, (int, float))
            or not math.isfinite(float(timeout_cap_seconds))
        ):
            raise ToolError("invalid_timeout", "The wall-time cap must be a finite number or null.")
        timeout_cap_seconds = float(timeout_cap_seconds)
        if timeout_cap_seconds <= 0:
            raise ToolError("wall_time_exceeded", "The run wall-time budget is exhausted.")
        effective_timeout_seconds = min(requested_timeout_seconds, timeout_cap_seconds)
        deadline_limited = timeout_cap_seconds < requested_timeout_seconds

    # 第二步：解析可执行文件、工作目录和风险等级，必要时等待用户批准。
    request = workspace.prepare_command(argv, cwd=cwd)
    policy = permission_policy or PermissionPolicy()
    decision = policy.command_decision(request.decision)
    if decision is CommandDecision.DENY:
        raise ToolError("command_denied", request.reason)
    if decision is CommandDecision.CONFIRM:
        if confirm_action is None:
            raise ToolError("command_confirmation_required", request.reason)
        try:
            approved = bool(
                confirm_action(
                    ToolApprovalRequest.for_command(
                        request,
                        reason=policy.command_approval_reason(request.reason),
                    )
                )
            )
        except Exception as exc:
            raise ToolError("command_confirmation_failed", "The command confirmation callback failed.") from exc
        if not approved:
            raise ToolError("command_rejected", "The user rejected the command.")

    # 第三步：创建进程前再次解析工作目录，防止策略检查后目录连接被替换。
    current_cwd = workspace.resolve_existing(cwd, expected="directory", operation="execute")
    if current_cwd != request.cwd:
        raise ToolError("cwd_changed", "The command working directory changed before execution.")
    # 仅继承最小环境变量白名单并排除模型、数据库凭据；这用于降低普通子进程
    # 意外泄密风险，但不能替代操作系统级沙箱。
    environment = workspace.sanitized_environment(minimal=True)
    if _cancel_requested(cancel_check):
        raise ToolError("command_cancelled", "The command was cancelled before it started.")

    # 第四步：准备有界输出缓冲区和平台相关的独立进程组参数。
    stdout_capture = _BoundedBytes(max_output_bytes)
    stderr_capture = _BoundedBytes(max_output_bytes)
    popen_options: dict[str, Any] = {
        "args": list(request.resolved_argv),
        "cwd": request.cwd,
        "env": environment,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
        "close_fds": True,
    }
    if os.name == "nt":
        popen_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_options["start_new_session"] = True

    # 第五步：启动进程，并用两个后台线程并行排空标准输出和标准错误，避免管道阻塞。
    started = time.monotonic()
    try:
        process = subprocess.Popen(**popen_options)
    except OSError as exc:
        raise ToolError("command_start_failed", "The command process could not be started.") from exc
    process_job = (
        _create_windows_kill_job(process)
        if os.name == "nt" and cancel_check is not None
        else None
    )

    assert process.stdout is not None
    assert process.stderr is not None
    stdout_thread = threading.Thread(
        target=_drain_pipe,
        args=(process.stdout, stdout_capture),
        name="coding-agent-stdout-drain",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_pipe,
        args=(process.stderr, stderr_capture),
        name="coding-agent-stderr-drain",
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    # 第六步：轮询取消信号和截止时间；触发任一条件时终止整棵进程树。
    timed_out = False
    cancelled = False
    tree_kill_ok: bool | None = None
    try:
        try:
            if cancel_check is None:
                process.wait(timeout=effective_timeout_seconds)
            else:
                deadline = started + effective_timeout_seconds
                while process.poll() is None:
                    if _cancel_requested(cancel_check):
                        cancelled = True
                        tree_kill_ok = _stop_process_tree(process, environment, process_job)
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        tree_kill_ok = _stop_process_tree(process, environment, process_job)
                        break
                    try:
                        process.wait(timeout=min(_CANCEL_POLL_SECONDS, remaining))
                    except subprocess.TimeoutExpired:
                        continue
        except subprocess.TimeoutExpired:
            timed_out = True
            tree_kill_ok = _stop_process_tree(process, environment, process_job)
    finally:
        if process_job is not None:
            process_job.close()
        _finish_drain(process.stdout, stdout_thread)
        _finish_drain(process.stderr, stderr_thread)

    # 第七步：整理截断、编码、耗时等元数据，再将失败状态映射成结构化工具错误。
    duration_seconds = time.monotonic() - started
    stdout, stdout_encoding = stdout_capture.render()
    stderr, stderr_encoding = stderr_capture.render()
    return_code = process.returncode if process.returncode is not None else -1
    data = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": return_code,
        "duration_seconds": round(duration_seconds, 6),
        "timed_out": timed_out,
    }
    meta = {
        "policy": request.decision.value,
        "exit_code": return_code,
        "duration_ms": round(duration_seconds * 1000),
        "truncated": stdout_capture.truncated or stderr_capture.truncated,
        "requested_timeout_seconds": requested_timeout_seconds,
        "effective_timeout_seconds": effective_timeout_seconds,
        "deadline_limited": deadline_limited,
        "stdout_encoding": stdout_encoding,
        "stderr_encoding": stderr_encoding,
        "stdout_total_bytes": stdout_capture.total_bytes,
        "stderr_total_bytes": stderr_capture.total_bytes,
        "stdout_omitted_bytes": stdout_capture.omitted_bytes,
        "stderr_omitted_bytes": stderr_capture.omitted_bytes,
        "stdout_truncated": stdout_capture.truncated,
        "stderr_truncated": stderr_capture.truncated,
        "tree_kill_ok": tree_kill_ok,
    }
    if cancel_check is not None:
        data["cancelled"] = cancelled
        meta["cancelled"] = cancelled
    if cancelled:
        raise ToolError(
            "command_cancelled",
            "The command was cancelled.",
            data=data,
            meta=meta,
        )
    if timed_out:
        error_code = "wall_time_exceeded" if deadline_limited else "command_timed_out"
        timeout_description = (
            "the remaining run wall-time budget"
            if deadline_limited
            else f"its {effective_timeout_seconds:g}-second timeout"
        )
        raise ToolError(
            error_code,
            f"The command exceeded {timeout_description}.",
            data=data,
            meta=meta,
        )
    if return_code != 0:
        raise ToolError(
            "command_exit_nonzero",
            f"The command exited with status {return_code}.",
            data=data,
            meta=meta,
        )
    return {"data": data, "meta": meta}


def _drain_pipe(pipe: BinaryIO, capture: _BoundedBytes) -> None:
    """持续排空一个子进程管道，防止进程因缓冲区写满而阻塞。

    :param pipe: 子进程标准输出或错误输出的二进制管道。
    :param capture: 接收并截断输出的有界字节缓冲区。
    """

    try:
        while True:
            chunk = pipe.read(8192)
            if not chunk:
                break
            capture.feed(chunk)
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _finish_drain(pipe: BinaryIO, thread: threading.Thread) -> None:
    """等待排空线程结束，必要时关闭管道促使线程退出。

    :param pipe: 排空线程正在读取的管道。
    :param thread: 对应的后台排空线程。
    """

    thread.join(timeout=3)
    if thread.is_alive():
        try:
            pipe.close()
        except OSError:
            pass
        thread.join(timeout=1)


def _cancel_requested(cancel_check: CancellationCheck | None) -> bool:
    """安全查询建议性的外部取消信号。

    :param cancel_check: 可选取消状态回调。
    :return: 回调明确返回真值时为 ``True``；缺失或异常时为 ``False``。
    """

    if cancel_check is None:
        return False
    try:
        return bool(cancel_check())
    except Exception:
        # 取消检查只是建议性信号；损坏的观察器不能终止本来有效的命令，
        # 也不能突破注册表的结构化错误边界。
        return False


def _stop_process_tree(
    process: subprocess.Popen[bytes],
    environment: Mapping[str, str],
    process_job: _WindowsKillJob | None,
) -> bool:
    """终止命令及其子进程，并返回进程树清理是否完整成功。

    :param process: 要终止的主子进程对象。
    :param environment: 供 Windows ``taskkill`` 使用的最小安全环境。
    :param process_job: 创建进程时绑定的 Windows 作业对象；其他平台为空。
    :return: 成功使用树级终止机制且无需退化时返回 ``True``。
    """

    # 第一步：优先使用创建进程时绑定的平台级进程组或 Windows 作业对象。
    if process_job is not None:
        tree_kill_ok = process_job.close()
        if not tree_kill_ok:
            tree_kill_ok = _terminate_process_tree(process, environment)
    elif os.name != "nt":
        tree_kill_ok = _terminate_process_tree(process, environment)
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
        tree_kill_ok = _force_kill_posix_process_group(process.pid) and tree_kill_ok
    else:
        tree_kill_ok = _terminate_process_tree(process, environment)
    # 第二步：等待正常清理；超时后强制杀死仍存活的主进程。
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        tree_kill_ok = False
    return tree_kill_ok


def _force_kill_posix_process_group(process_group_id: int) -> bool:
    """向 POSIX 进程组发送强制终止信号。

    :param process_group_id: 需要清理的进程组 ID，通常等于主进程 PID。
    :return: 进程组已不存在或信号发送成功时返回 ``True``。
    """

    try:
        os.killpg(process_group_id, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        return False


def _create_windows_kill_job(
    process: subprocess.Popen[bytes],
) -> _WindowsKillJob | None:
    """Windows 允许时，将子进程加入关闭即终止的作业对象。

    :param process: 已启动且暴露原生句柄的 Windows 子进程。
    :return: 成功配置的作业对象；平台或权限不支持时返回 ``None``。
    """

    try:
        import ctypes
        from ctypes import wintypes

        class _BasicLimitInformation(ctypes.Structure):
            """Windows 作业对象的基础资源限制结构。"""

            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            """Windows 作业对象累计的输入输出计数结构。"""

            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
            """组合基础限制、I/O 计数和内存限制的扩展结构。"""

            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_job = kernel32.CreateJobObjectW
        create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        create_job.restype = wintypes.HANDLE
        set_information = kernel32.SetInformationJobObject
        set_information.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        set_information.restype = wintypes.BOOL
        assign_process = kernel32.AssignProcessToJobObject
        assign_process.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        assign_process.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        handle = create_job(None, None)
        if not handle:
            return None
        assigned = False
        try:
            information = _ExtendedLimitInformation()
            information.BasicLimitInformation.LimitFlags = 0x00002000
            if not set_information(
                handle,
                9,
                ctypes.byref(information),
                ctypes.sizeof(information),
            ):
                return None
            process_handle = getattr(process, "_handle", None)
            if process_handle is None or not assign_process(handle, process_handle):
                return None
            assigned = True
            return _WindowsKillJob(handle, close_handle)
        finally:
            if not assigned:
                close_handle(handle)
    except Exception:
        # 作业对象只是尽力而为的快速路径；在受限或特殊 Windows 环境中，
        # taskkill/kill 仍作为平台级兜底方案。
        return None


def _decode_bytes(data: bytes) -> tuple[str, str]:
    """优先按 UTF-8 解码命令输出，失败时使用系统首选编码替换坏字节。

    :param data: 捕获到的有界输出字节。
    :return: 可展示文本及采用的编码名称。
    """

    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        return data.decode(encoding, errors="replace"), encoding


def _terminate_process_tree(process: subprocess.Popen[bytes], environment: Mapping[str, str]) -> bool:
    """按平台终止进程树，并返回是否成功使用了树级终止机制。

    :param process: 要终止的主子进程。
    :param environment: 查找固定系统工具时使用的最小环境映射。
    :return: 树级终止机制成功或进程已经结束时返回 ``True``。
    """

    # 第一步：Windows 优先调用固定系统路径下的 taskkill 终止整棵子进程树。
    if process.poll() is not None:
        return True
    if os.name == "nt":
        system_root = environment.get("SystemRoot") or environment.get("SYSTEMROOT") or r"C:\Windows"
        taskkill = Path(system_root) / "System32" / "taskkill.exe"
        taskkill_ok = False
        if taskkill.is_file():
            try:
                completed = subprocess.run(
                    [os.fspath(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                    env=dict(environment),
                    timeout=5,
                    check=False,
                )
                taskkill_ok = completed.returncode == 0
            except (OSError, subprocess.SubprocessError):
                taskkill_ok = False
        # 第二步：树级终止失败或未完成时，至少直接终止已知父进程。
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        return taskkill_ok

    # POSIX 使用独立会话的进程组；失败时退化为直接终止父进程。
    try:
        os.killpg(process.pid, signal.SIGTERM)
        return True
    except OSError:
        try:
            process.kill()
        except OSError:
            return False
        return False


__all__ = ["run_command"]
