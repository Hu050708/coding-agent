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

from coding_agent.security.command_policy import CommandDecision, CommandRequest
from coding_agent.security.workspace import Workspace

from .contracts import (
    CancellationCheck,
    CommandConfirmation,
    ToolError,
    optional_number,
    optional_string,
    reject_unknown,
)


_CANCEL_POLL_SECONDS = 0.1


class _BoundedBytes:
    """Keep a fixed-size head and tail while counting all drained bytes."""

    def __init__(self, limit: int) -> None:
        if limit < 64:
            raise ValueError("The output limit must be at least 64 bytes.")
        self.limit = limit
        self.head_limit = limit // 2
        self.tail_limit = limit - self.head_limit
        self.head = bytearray()
        self.tail = bytearray()
        self.total_bytes = 0

    def feed(self, chunk: bytes) -> None:
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
        return self.total_bytes > len(self.head) + len(self.tail)

    @property
    def omitted_bytes(self) -> int:
        return max(0, self.total_bytes - len(self.head) - len(self.tail))

    def render(self) -> tuple[str, str]:
        if not self.truncated:
            return _decode_bytes(bytes(self.head + self.tail))

        head_text, head_encoding = _decode_bytes(bytes(self.head))
        tail_text, tail_encoding = _decode_bytes(bytes(self.tail))
        encoding = head_encoding if head_encoding == tail_encoding else f"{head_encoding}/{tail_encoding}"
        marker = f"\n... <{self.omitted_bytes} bytes omitted> ...\n"
        return head_text + marker + tail_text, encoding


class _WindowsKillJob:
    """Own a Windows Job Object whose close terminates every assigned process."""

    def __init__(self, handle: Any, close_handle: Callable[[Any], Any]) -> None:
        self._handle = handle
        self._close_handle = close_handle

    def close(self) -> bool:
        handle, self._handle = self._handle, None
        if handle is None:
            return True
        try:
            return bool(self._close_handle(handle))
        except Exception:
            return False


def run_command(
    workspace: Workspace,
    arguments: Mapping[str, Any],
    *,
    confirm_command: CommandConfirmation | None = None,
    cancel_check: CancellationCheck | None = None,
    auto_approve: bool = False,
    max_output_bytes: int = 12_000,
    timeout_cap_seconds: float | None = None,
) -> dict[str, Any]:
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

    request = workspace.prepare_command(argv, cwd=cwd)
    if request.decision is CommandDecision.DENY:
        raise ToolError("command_denied", request.reason)
    if request.decision is CommandDecision.CONFIRM:
        if auto_approve:
            approved = True
        elif confirm_command is None:
            raise ToolError("command_confirmation_required", request.reason)
        else:
            try:
                approved = bool(confirm_command(request))
            except Exception as exc:
                raise ToolError("command_confirmation_failed", "The command confirmation callback failed.") from exc
        if not approved:
            raise ToolError("command_rejected", "The user rejected the command.")

    # Resolve cwd again immediately before process creation so a replaced
    # junction cannot silently change the destination after policy evaluation.
    current_cwd = workspace.resolve_existing(cwd, expected="directory", operation="execute")
    if current_cwd != request.cwd:
        raise ToolError("cwd_changed", "The command working directory changed before execution.")
    environment = workspace.sanitized_environment()
    if _cancel_requested(cancel_check):
        raise ToolError("command_cancelled", "The command was cancelled before it started.")

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
    thread.join(timeout=3)
    if thread.is_alive():
        try:
            pipe.close()
        except OSError:
            pass
        thread.join(timeout=1)


def _cancel_requested(cancel_check: CancellationCheck | None) -> bool:
    if cancel_check is None:
        return False
    try:
        return bool(cancel_check())
    except Exception:
        # Cancellation is advisory. A broken observer must not terminate an
        # otherwise valid command or escape the registry's structured boundary.
        return False


def _stop_process_tree(
    process: subprocess.Popen[bytes],
    environment: Mapping[str, str],
    process_job: _WindowsKillJob | None,
) -> bool:
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
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        tree_kill_ok = False
    return tree_kill_ok


def _force_kill_posix_process_group(process_group_id: int) -> bool:
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
    """Assign a child to a kill-on-close Job Object when Windows permits it."""

    try:
        import ctypes
        from ctypes import wintypes

        class _BasicLimitInformation(ctypes.Structure):
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
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
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
        # Job Objects are a best-effort fast path. taskkill/kill remains the
        # platform fallback for restricted or unusual Windows environments.
        return None


def _decode_bytes(data: bytes) -> tuple[str, str]:
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        return data.decode(encoding, errors="replace"), encoding


def _terminate_process_tree(process: subprocess.Popen[bytes], environment: Mapping[str, str]) -> bool:
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
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        return taskkill_ok

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
