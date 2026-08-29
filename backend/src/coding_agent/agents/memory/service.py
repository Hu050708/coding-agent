"""实现工作区校验、记忆策略和确定性检索。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from coding_agent.agents.memory.models import (
    MemoryEntry,
    MemoryKind,
    MemorySnapshot,
    MemorySource,
    StoredMemory,
)
from .repository import (
    MemoryCapacityError,
    MemoryDuplicateError,
    MemoryNotFoundError,
    MemoryRepository,
    MemoryRepositoryError,
)
from coding_agent.agents.security import WorkspacePolicy, WorkspacePolicyError


MAX_MEMORY_CONTENT_CHARS = 2_000
MAX_MEMORIES_PER_WORKSPACE = 500
DEFAULT_SNAPSHOT_ITEMS = 8
DEFAULT_SNAPSHOT_CHARS = 6_000


class MemoryServiceError(RuntimeError):
    """记忆用例无法完成且需要稳定错误映射时抛出。"""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        """创建可稳定映射到 HTTP 响应的记忆服务错误。

        :param code: 供程序判断的稳定错误码。
        :param message: 面向调用方的错误说明。
        :param status_code: 对应的 HTTP 状态码。
        """

        super().__init__(message)
        # 稳定错误码、展示信息和 HTTP 状态分别保存，避免上层解析异常文本。
        self.code = code
        self.message = message
        self.status_code = status_code


class MemoryService:
    """以隔离的仓储键提供工作区范围的记忆操作。"""

    def __init__(
        self,
        repository: MemoryRepository,
        workspace_policy: WorkspacePolicy,
        *,
        max_items: int = MAX_MEMORIES_PER_WORKSPACE,
        snapshot_items: int = DEFAULT_SNAPSHOT_ITEMS,
        snapshot_chars: int = DEFAULT_SNAPSHOT_CHARS,
    ) -> None:
        """初始化工作区记忆服务及快照预算。

        :param repository: 负责记忆持久化和唯一性约束的仓储。
        :param workspace_policy: 负责校验、规范化工作区路径的安全策略。
        :param max_items: 单个工作区允许持久化的最大条目数。
        :param snapshot_items: 一次运行最多装载的记忆条目数。
        :param snapshot_chars: 一次运行装载记忆正文的总字符上限。
        :raises ValueError: 任一数量或字符限制不是正数。
        """

        if max_items < 1 or snapshot_items < 1 or snapshot_chars < 1:
            raise ValueError("memory limits must be positive")
        self.repository = repository
        self.workspace_policy = workspace_policy
        self.max_items = max_items
        self.snapshot_items = snapshot_items
        self.snapshot_chars = snapshot_chars

    def list(self, workspace: str) -> list[MemoryEntry]:
        """列出指定工作区的全部记忆条目。

        :param workspace: 待查询的工作区路径。
        :return: 使用规范工作区路径表示的记忆条目列表。
        :raises MemoryServiceError: 工作区无效或底层仓储不可用。
        """

        resolved, key = self._workspace(workspace)
        try:
            records = self.repository.list(key)
        except MemoryRepositoryError as exc:
            raise self._unavailable(exc) from exc
        return [self._entry(resolved, record) for record in records]

    def create(
        self,
        *,
        workspace: str,
        kind: MemoryKind | str,
        content: str,
        pinned: bool = False,
        source: MemorySource | str = MemorySource.MANUAL,
        source_run_id: str | None = None,
    ) -> MemoryEntry:
        """校验并创建记忆，将底层约束错误映射为稳定服务错误。

        :param workspace: 记忆所属的工作区路径。
        :param kind: 记忆的业务分类或其字符串值。
        :param content: 非空的记忆正文。
        :param pinned: 是否在构建运行快照时优先选择该条目。
        :param source: 条目是人工创建还是从运行结果生成。
        :param source_run_id: 自动生成条目所关联的已完成运行 ID。
        :return: 创建后的用户可见记忆条目。
        :raises MemoryServiceError: 输入无效、内容重复、容量已满或仓储不可用。
        """

        # 第一步：规范化工作区、类型、来源和内容，并处理来源运行规则。
        resolved, key = self._workspace(workspace)
        safe_kind = self._kind(kind)
        safe_source = self._source(source)
        safe_content = self._content(content)
        if safe_source is MemorySource.MANUAL:
            source_run_id = None
        else:
            source_run_id = self._source_run_id(source_run_id)
        # 第二步：写入仓储，再将去重、容量和可用性错误转换到应用边界。
        try:
            record = self.repository.create(
                memory_id=uuid4().hex,
                workspace_key=key,
                kind=safe_kind,
                content=safe_content,
                source=safe_source,
                source_run_id=source_run_id,
                pinned=bool(pinned),
                content_hash=self._content_hash(safe_content),
                max_items=self.max_items,
            )
        except MemoryDuplicateError as exc:
            raise MemoryServiceError(
                "memory_duplicate", "An equivalent memory entry already exists.", status_code=409
            ) from exc
        except MemoryCapacityError as exc:
            raise MemoryServiceError(
                "memory_capacity_reached",
                "The workspace memory limit has been reached.",
                status_code=409,
            ) from exc
        except MemoryRepositoryError as exc:
            raise self._unavailable(exc) from exc
        return self._entry(resolved, record)

    def update(
        self,
        *,
        workspace: str,
        memory_id: str,
        kind: MemoryKind | str | None = None,
        content: str | None = None,
        pinned: bool | None = None,
        enabled: bool | None = None,
    ) -> MemoryEntry:
        """仅更新显式提供的字段，并在内容变化时同步更新去重哈希。

        :param workspace: 记忆所属的工作区路径。
        :param memory_id: 待更新记忆的唯一标识。
        :param kind: 新业务分类；为 None 时保持原值。
        :param content: 新正文；为 None 时保持原值。
        :param pinned: 新置顶状态；为 None 时保持原值。
        :param enabled: 新启用状态；为 None 时保持原值。
        :return: 更新后的用户可见记忆条目。
        :raises MemoryServiceError: 没有变更、条目不存在、内容重复或仓储不可用。
        """

        # 第一步：构造字段白名单内的最小变更集。
        resolved, key = self._workspace(workspace)
        changes: dict[str, object] = {}
        if kind is not None:
            changes["kind"] = self._kind(kind)
        if content is not None:
            safe_content = self._content(content)
            changes["content"] = safe_content
            changes["content_hash"] = self._content_hash(safe_content)
        if pinned is not None:
            changes["pinned"] = bool(pinned)
        if enabled is not None:
            changes["enabled"] = bool(enabled)
        if not changes:
            raise MemoryServiceError(
                "memory_update_empty", "At least one memory field must be updated.", status_code=422
            )
        # 第二步：执行更新，并把不存在、重复和存储故障分别映射。
        try:
            record = self.repository.update(key, self._id(memory_id), changes)
        except MemoryNotFoundError as exc:
            raise MemoryServiceError(
                "memory_not_found", "Memory entry was not found.", status_code=404
            ) from exc
        except MemoryDuplicateError as exc:
            raise MemoryServiceError(
                "memory_duplicate", "An equivalent memory entry already exists.", status_code=409
            ) from exc
        except MemoryRepositoryError as exc:
            raise self._unavailable(exc) from exc
        return self._entry(resolved, record)

    def delete(self, *, workspace: str, memory_id: str) -> None:
        """删除工作区中的一条记忆。

        :param workspace: 记忆所属的工作区路径。
        :param memory_id: 待删除记忆的唯一标识。
        :raises MemoryServiceError: 条目不存在、工作区无效或仓储不可用。
        """

        _, key = self._workspace(workspace)
        try:
            self.repository.delete(key, self._id(memory_id))
        except MemoryNotFoundError as exc:
            raise MemoryServiceError(
                "memory_not_found", "Memory entry was not found.", status_code=404
            ) from exc
        except MemoryRepositoryError as exc:
            raise self._unavailable(exc) from exc

    def purge(self, *, workspace: str) -> int:
        """清空指定工作区的全部记忆。

        :param workspace: 待清理的工作区路径。
        :return: 实际删除的条目数量。
        :raises MemoryServiceError: 工作区无效或仓储不可用。
        """

        _, key = self._workspace(workspace)
        try:
            return self.repository.purge(key)
        except MemoryRepositoryError as exc:
            raise self._unavailable(exc) from exc

    def snapshot(self, *, workspace: str | Path, task: str) -> MemorySnapshot:
        """按置顶、任务相关度和新鲜度构建确定性的有界记忆快照。

        :param workspace: 本次运行所在的工作区路径。
        :param task: 当前任务文本，用于计算与记忆正文的词元重叠度。
        :return: 受条目数和总字符数双重限制的不可变快照。
        :raises MemoryServiceError: 工作区无效或仓储不可用。
        """

        # 第一步：读取启用条目，并提取任务词元计算简单相关度。
        resolved, key = self._workspace(os.fspath(workspace))
        try:
            records = self.repository.list(key, enabled_only=True)
        except MemoryRepositoryError as exc:
            raise self._unavailable(exc) from exc
        if not records:
            return MemorySnapshot(status="empty")

        task_tokens = _tokens(task)
        ranked = sorted(
            records,
            key=lambda item: (
                -int(item.pinned),
                -len(task_tokens.intersection(_tokens(item.content))),
                -item.updated_at.timestamp(),
                item.id,
            ),
        )
        # 第二步：按条目数和总字符数双重预算依次选取，超长单项直接跳过。
        selected: list[MemoryEntry] = []
        used_chars = 0
        for record in ranked:
            if len(selected) >= self.snapshot_items:
                break
            content_chars = len(record.content)
            if used_chars + content_chars > self.snapshot_chars:
                continue
            selected.append(self._entry(resolved, record))
            used_chars += content_chars
        if not selected:
            return MemorySnapshot(status="empty")
        return MemorySnapshot(status="loaded", entries=tuple(selected))

    def _workspace(self, workspace: str) -> tuple[Path, str]:
        """校验工作区并生成不泄露本地路径的仓储键。

        :param workspace: 用户提供的工作区路径。
        :return: 规范绝对路径与其 SHA-256 仓储键。
        :raises MemoryServiceError: 路径不符合工作区安全策略。
        """

        try:
            resolved = self.workspace_policy.validate(workspace)
        except WorkspacePolicyError as exc:
            raise MemoryServiceError(exc.code, exc.message, status_code=400) from exc
        normalized = os.path.normcase(os.path.abspath(os.fspath(resolved)))
        key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return resolved, key

    @staticmethod
    def _entry(workspace: Path, record: StoredMemory) -> MemoryEntry:
        """把内部仓储记录转换为用户可见领域对象。

        :param workspace: 已规范化的用户可见工作区路径。
        :param record: 不包含真实路径的内部仓储记录。
        :return: 可由服务层或 API 返回的记忆条目。
        """

        return MemoryEntry(
            id=record.id,
            workspace=os.fspath(workspace),
            kind=record.kind,
            content=record.content,
            source=record.source,
            source_run_id=record.source_run_id,
            pinned=record.pinned,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _content(value: str) -> str:
        """清理并校验记忆正文。

        :param value: 待校验的原始正文。
        :return: 去除首尾空白后的正文。
        :raises MemoryServiceError: 正文为空、过长或包含空字符。
        """

        if not isinstance(value, str) or not value.strip():
            raise MemoryServiceError(
                "memory_content_invalid", "Memory content must be non-empty text.", status_code=422
            )
        content = value.strip()
        if len(content) > MAX_MEMORY_CONTENT_CHARS:
            raise MemoryServiceError(
                "memory_content_too_large",
                f"Memory content must not exceed {MAX_MEMORY_CONTENT_CHARS} characters.",
                status_code=413,
            )
        if "\x00" in content:
            raise MemoryServiceError(
                "memory_content_invalid", "Memory content is malformed.", status_code=422
            )
        return content

    @staticmethod
    def _content_hash(content: str) -> str:
        """计算用于语义近似去重的规范化正文哈希。

        :param content: 已通过基础校验的记忆正文。
        :return: 统一大小写、兼容字符和空白后的 SHA-256 十六进制摘要。
        """

        normalized = " ".join(unicodedata.normalize("NFKC", content).casefold().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _kind(value: MemoryKind | str) -> MemoryKind:
        """把枚举或字符串转换为合法记忆分类。

        :param value: 分类枚举或其字符串值。
        :return: 规范的 ``MemoryKind``。
        :raises MemoryServiceError: 值不属于支持的分类。
        """

        try:
            return value if isinstance(value, MemoryKind) else MemoryKind(value)
        except (TypeError, ValueError) as exc:
            raise MemoryServiceError(
                "memory_kind_invalid", "Memory kind is invalid.", status_code=422
            ) from exc

    @staticmethod
    def _source(value: MemorySource | str) -> MemorySource:
        """把枚举或字符串转换为合法记忆来源。

        :param value: 来源枚举或其字符串值。
        :return: 规范的 ``MemorySource``。
        :raises MemoryServiceError: 值不属于支持的来源。
        """

        try:
            return value if isinstance(value, MemorySource) else MemorySource(value)
        except (TypeError, ValueError) as exc:
            raise MemoryServiceError(
                "memory_source_invalid", "Memory source is invalid.", status_code=422
            ) from exc

    @staticmethod
    def _id(value: str) -> str:
        """校验外部提供的记忆 ID，且不泄露条目存在性。

        :param value: 待校验的记忆唯一标识。
        :return: 原始合法标识。
        :raises MemoryServiceError: 标识类型、长度或内容非法。
        """

        if not isinstance(value, str) or not value or len(value) > 128:
            raise MemoryServiceError(
                "memory_not_found", "Memory entry was not found.", status_code=404
            )
        return value

    @staticmethod
    def _source_run_id(value: str | None) -> str:
        """校验自动记忆所关联的来源运行 ID。

        :param value: 调用方提供的来源运行标识。
        :return: 非空且不含控制字符的运行标识。
        :raises MemoryServiceError: 标识缺失、过长或格式非法。
        """

        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 128
            or "\x00" in value
            or any(ord(character) < 32 for character in value)
        ):
            raise MemoryServiceError(
                "memory_source_run_invalid",
                "A valid completed source run is required.",
                status_code=422,
            )
        return value

    @staticmethod
    def _unavailable(_exc: Exception) -> MemoryServiceError:
        """把仓储异常隐藏为稳定且不泄露内部信息的服务错误。

        :param _exc: 触发映射的底层异常，仅用于保留调用语义。
        :return: HTTP 503 对应的记忆存储不可用错误。
        """

        return MemoryServiceError(
            "memory_store_unavailable", "Project memory storage is unavailable.", status_code=503
        )


_WORD_OR_CJK = re.compile(r"[a-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff]+", re.IGNORECASE)


def _tokens(value: str) -> frozenset[str]:
    """提取英文词元以及中文单字、双字词元用于轻量相关度排序。

    :param value: 待分析的任务或记忆文本。
    :return: 经过 Unicode 规范化和大小写折叠的不可变词元集合。
    """

    tokens: set[str] = set()
    for match in _WORD_OR_CJK.findall(unicodedata.normalize("NFKC", value).casefold()):
        if re.fullmatch(r"[\u3400-\u4dbf\u4e00-\u9fff]+", match):
            characters = tuple(match)
            tokens.update(characters)
            tokens.update("".join(characters[index : index + 2]) for index in range(len(characters) - 1))
        else:
            tokens.add(match)
    return frozenset(tokens)


__all__ = [
    "DEFAULT_SNAPSHOT_CHARS",
    "DEFAULT_SNAPSHOT_ITEMS",
    "MAX_MEMORIES_PER_WORKSPACE",
    "MAX_MEMORY_CONTENT_CHARS",
    "MemoryService",
    "MemoryServiceError",
]
