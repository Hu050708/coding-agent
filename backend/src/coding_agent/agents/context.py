"""不可变且有容量边界的可见会话与工作区记忆上下文。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any, Literal


VisibleRole = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class VisibleMessage:
    """一条可安全重放给模型的持久化用户可见消息。"""

    role: VisibleRole
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"user", "assistant"}:
            raise ValueError("visible message role must be user or assistant")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("visible message content must be non-empty text")

    def as_history_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True)
class MemoryReference:
    """运行已选记忆快照中的一个不可变条目。"""

    id: str
    kind: str
    content: str

    def __post_init__(self) -> None:
        for name, value in (("id", self.id), ("kind", self.kind), ("content", self.content)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"memory {name} must be non-empty text")


@dataclass(frozen=True, slots=True)
class AgentContext:
    """运行本地快照，刻意不暴露任何持久化方法。"""

    prior_messages: tuple[VisibleMessage, ...] = ()
    memory_entries: tuple[MemoryReference, ...] = ()
    dropped_prior_messages: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.prior_messages, tuple) or not all(
            isinstance(message, VisibleMessage) for message in self.prior_messages
        ):
            raise TypeError("prior_messages must be an immutable tuple of VisibleMessage values")
        if not isinstance(self.memory_entries, tuple) or not all(
            isinstance(entry, MemoryReference) for entry in self.memory_entries
        ):
            raise TypeError("memory_entries must be an immutable tuple of MemoryReference values")
        if (
            isinstance(self.dropped_prior_messages, bool)
            or not isinstance(self.dropped_prior_messages, int)
            or self.dropped_prior_messages < 0
        ):
            raise ValueError("dropped_prior_messages must be a non-negative integer")

    @property
    def has_memory(self) -> bool:
        return bool(self.memory_entries)

    def render_prior_transcript(self) -> str | None:
        """将保留的可见历史渲染为一个紧凑 JSON 项。"""

        if not self.prior_messages:
            return None
        payload = {
            "type": "coding_agent_visible_history",
            "messages": [message.as_history_dict() for message in self.prior_messages],
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )

    def render_current_task(self, task: str) -> str:
        """把记忆序列化为普通用户数据，并将当前任务置于最后。"""

        if not self.memory_entries:
            return task
        payload = {
            "type": "coding_agent_task_with_workspace_memory",
            "workspace_memory": [
                {"id": item.id, "kind": item.kind, "content": item.content}
                for item in self.memory_entries
            ],
            # 权威的当前请求在视觉和结构上都必须保持在最后。
            "current_task": task,
        }
        return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class AgentContextBuilder:
    """校验外部记录并保留确定且有界的快照。"""

    max_prior_messages: int = 48
    max_prior_chars: int = 80_000
    max_message_chars: int = 24_000
    max_memory_entries: int = 32
    max_memory_chars: int = 32_000
    max_memory_item_chars: int = 4_000

    def __post_init__(self) -> None:
        for name in (
            "max_prior_messages",
            "max_prior_chars",
            "max_message_chars",
            "max_memory_entries",
            "max_memory_chars",
            "max_memory_item_chars",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def build(
        self,
        *,
        prior_messages: Sequence[VisibleMessage | Mapping[str, Any]] = (),
        memory_entries: Sequence[MemoryReference | Mapping[str, Any]] = (),
    ) -> AgentContext:
        """验证外部上下文，并按从近到远的顺序应用消息和记忆预算。"""

        # 第一步：拒绝字符串伪装的序列，再把所有外部记录转换为领域值。
        if isinstance(prior_messages, (str, bytes)) or not isinstance(prior_messages, Sequence):
            raise TypeError("prior_messages must be a sequence")
        if isinstance(memory_entries, (str, bytes)) or not isinstance(memory_entries, Sequence):
            raise TypeError("memory_entries must be a sequence")

        # 第二步：从最新消息向前保留完整后缀，任一预算触顶即停止。
        validated_messages = tuple(self._visible_message(value) for value in prior_messages)
        kept_reversed: list[VisibleMessage] = []
        used_chars = 0
        for message in reversed(validated_messages):
            content_chars = len(message.content)
            if content_chars > self.max_message_chars:
                break
            if len(kept_reversed) >= self.max_prior_messages:
                break
            if used_chars + content_chars > self.max_prior_chars:
                break
            kept_reversed.append(message)
            used_chars += content_chars
        kept_messages = tuple(reversed(kept_reversed))

        # 第三步：记忆保持调用方给定顺序，并应用条目数和字符数双重上限。
        validated_memory = tuple(self._memory_reference(value) for value in memory_entries)
        kept_memory: list[MemoryReference] = []
        used_memory_chars = 0
        for entry in validated_memory:
            if len(kept_memory) >= self.max_memory_entries:
                break
            if used_memory_chars + len(entry.content) > self.max_memory_chars:
                break
            kept_memory.append(entry)
            used_memory_chars += len(entry.content)

        return AgentContext(
            prior_messages=kept_messages,
            memory_entries=tuple(kept_memory),
            dropped_prior_messages=len(validated_messages) - len(kept_messages),
        )

    def _visible_message(self, value: VisibleMessage | Mapping[str, Any]) -> VisibleMessage:
        if isinstance(value, VisibleMessage):
            message = value
        elif isinstance(value, Mapping):
            if set(value) != {"role", "content"}:
                raise ValueError(
                    "visible history records may contain only role and content; tool and reasoning data are forbidden"
                )
            message = VisibleMessage(role=value["role"], content=value["content"])
        else:
            raise TypeError("each prior message must be VisibleMessage or a role/content mapping")
        return message

    def _memory_reference(
        self, value: MemoryReference | Mapping[str, Any]
    ) -> MemoryReference:
        """把外部记忆输入收敛为受长度限制的上下文引用。"""

        # 第一步：只接受强类型对象或恰好包含三个公开字段的映射。
        if isinstance(value, MemoryReference):
            entry = value
        elif isinstance(value, Mapping):
            if set(value) != {"id", "kind", "content"}:
                raise ValueError("memory context records may contain only id, kind, and content")
            entry = MemoryReference(
                id=value["id"],
                kind=value["kind"],
                content=value["content"],
            )
        else:
            raise TypeError("each memory entry must be MemoryReference or an id/kind/content mapping")
        # 第二步：限制元数据和正文尺寸，防止单条记忆占满模型上下文。
        if len(entry.id) > 128 or len(entry.kind) > 64:
            raise ValueError("memory metadata exceeds the context limit")
        if len(entry.content) > self.max_memory_item_chars:
            raise ValueError("a memory entry exceeds the per-item context limit")
        return entry


__all__ = [
    "AgentContext",
    "AgentContextBuilder",
    "MemoryReference",
    "VisibleMessage",
    "VisibleRole",
]
