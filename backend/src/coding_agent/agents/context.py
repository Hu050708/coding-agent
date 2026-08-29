"""不可变且有容量边界的可见会话与工作区记忆上下文。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any, Literal

from coding_agent.agents.config import AgentConfig


VisibleRole = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class VisibleMessage:
    """一条可安全重放给模型的持久化用户可见消息。"""

    # 消息发送方，只允许用户或助手，禁止工具及隐藏推理角色。
    role: VisibleRole
    # 最终用户可以看到并允许重新发送给模型的消息正文。
    content: str

    def __post_init__(self) -> None:
        """校验消息角色和正文，阻止隐藏角色或空内容进入上下文。"""
        if self.role not in {"user", "assistant"}:
            raise ValueError("visible message role must be user or assistant")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("visible message content must be non-empty text")

    def as_history_dict(self) -> dict[str, str]:
        """转换为模型消息历史接受的角色、正文字典。

        :return: 仅含 ``role`` 和 ``content`` 的新字典。
        """

        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True)
class MemoryReference:
    """Agent 从长期记忆中选出来、提供给当前这一次运行使用的一条“记忆”"""

    # 持久化记忆的唯一标识，用于追踪本次运行实际使用了哪条记忆。
    id: str
    # 记忆类型，例如事实、约定或决策。
    kind: str
    # 作为不可信参考资料提供给模型的记忆正文。
    content: str

    def __post_init__(self) -> None:
        """校验记忆标识、分类和正文均为非空文本。"""

        for name, value in (("id", self.id), ("kind", self.kind), ("content", self.content)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"memory {name} must be non-empty text")


@dataclass(frozen=True, slots=True)
class AgentContext:
    """运行本地快照，刻意不暴露任何持久化方法。"""

    # 按原会话顺序保留的用户可见历史消息。
    prior_messages: tuple[VisibleMessage, ...] = ()
    # 本次运行冻结并允许提供给模型的工作区记忆。
    memory_entries: tuple[MemoryReference, ...] = ()
    # 因条数或字符预算被丢弃的较早历史消息数量。
    dropped_prior_messages: int = 0

    def __post_init__(self) -> None:
        """校验上下文集合不可变、元素类型正确且丢弃计数合法。"""

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
        """判断当前上下文是否包含至少一条记忆。

        :return: 存在记忆条目时为 True。
        """

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
        """把记忆序列化为普通用户数据，并将当前任务置于最后。

        :param task: 当前用户提交的权威任务正文。
        :return: 无记忆时返回原任务；有记忆时返回包含记忆和任务的紧凑 JSON。
        """

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


class AgentContextBuilder:
    """校验外部记录并保留确定且有界的快照。"""

    def build(
        self,
        *,
        config: AgentConfig | None = None,
        prior_messages: Sequence[VisibleMessage | Mapping[str, Any]] = (),
        memory_entries: Sequence[MemoryReference | Mapping[str, Any]] = (),
    ) -> AgentContext:
        """验证外部上下文，并按从近到远的顺序应用消息和记忆预算。

        :param config: 提供消息和记忆容量上限的 Agent 配置；省略时使用默认值。
        :param prior_messages: 按时间从旧到新排列的可见历史消息或公开字段映射。
        :param memory_entries: 按调用方优先级排列的记忆引用或公开字段映射。
        :return: 经过类型校验和容量裁剪的不可变上下文快照。
        :raises TypeError: 配置或输入集合类型不符合接口要求。
        :raises ValueError: 消息、记忆字段或单条记忆尺寸不合法。
        """

        # 第一步：统一从 AgentConfig 读取容量限制，避免在上下文层重复维护默认值。
        if config is None:
            effective_config = AgentConfig()
        elif not isinstance(config, AgentConfig):
            raise TypeError("config must be an AgentConfig")
        else:
            effective_config = config

        # 第二步：拒绝字符串伪装的序列，再把所有外部记录转换为领域值。
        if isinstance(prior_messages, (str, bytes)) or not isinstance(prior_messages, Sequence):
            raise TypeError("prior_messages must be a sequence")
        if isinstance(memory_entries, (str, bytes)) or not isinstance(memory_entries, Sequence):
            raise TypeError("memory_entries must be a sequence")

        # 第三步：从最新消息向前保留完整后缀，任一预算触顶即停止。
        validated_messages = tuple(self._visible_message(value) for value in prior_messages)
        kept_reversed: list[VisibleMessage] = []
        used_chars = 0
        for message in reversed(validated_messages):
            content_chars = len(message.content)
            if content_chars > effective_config.max_message_chars:
                break
            if len(kept_reversed) >= effective_config.max_prior_messages:
                break
            if used_chars + content_chars > effective_config.max_prior_chars:
                break
            kept_reversed.append(message)
            used_chars += content_chars
        kept_messages = tuple(reversed(kept_reversed))

        # 第四步：记忆保持调用方给定顺序，并应用单条、条目数和字符数上限。
        validated_memory = tuple(
            self._memory_reference(value, config=effective_config)
            for value in memory_entries
        )
        kept_memory: list[MemoryReference] = []
        used_memory_chars = 0
        for entry in validated_memory:
            if len(kept_memory) >= effective_config.max_memory_entries:
                break
            if (
                used_memory_chars + len(entry.content)
                > effective_config.max_memory_chars
            ):
                break
            kept_memory.append(entry)
            used_memory_chars += len(entry.content)

        return AgentContext(
            prior_messages=kept_messages,
            memory_entries=tuple(kept_memory),
            dropped_prior_messages=len(validated_messages) - len(kept_messages),
        )

    def _visible_message(self, value: VisibleMessage | Mapping[str, Any]) -> VisibleMessage:
        """把一条外部历史记录转换为仅含公开字段的可见消息。

        :param value: ``VisibleMessage`` 或只包含 ``role/content`` 的映射。
        :return: 经过角色和正文校验的 ``VisibleMessage``。
        :raises TypeError: 输入不是支持的对象类型。
        :raises ValueError: 映射包含隐藏字段、未知字段或非法角色/正文。
        """

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
        self,
        value: MemoryReference | Mapping[str, Any],
        *,
        config: AgentConfig,
    ) -> MemoryReference:
        """把外部记忆输入收敛为受长度限制的上下文引用。

        :param value: ``MemoryReference`` 或只包含 ``id/kind/content`` 的映射。
        :param config: 提供单条记忆正文字符上限的 Agent 配置。
        :return: 经过字段和尺寸校验的 ``MemoryReference``。
        :raises TypeError: 输入不是支持的对象类型。
        :raises ValueError: 字段集合、元数据长度或正文长度不合法。
        """

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
        if len(entry.content) > config.max_memory_item_chars:
            raise ValueError("a memory entry exceeds the per-item context limit")
        return entry


__all__ = [
    "AgentContext",
    "AgentContextBuilder",
    "MemoryReference",
    "VisibleMessage",
    "VisibleRole",
]
