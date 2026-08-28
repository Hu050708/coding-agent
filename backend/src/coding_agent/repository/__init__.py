"""事务仓储、不可变记录和持久化服务。"""

from coding_agent.models import (
    ACTIVE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    ApprovalStatus,
    MemoryKind,
    MemorySource,
    MessageRole,
    PermissionMode,
    RunStatus,
)

from .records import (
    ApprovalRecord,
    ConversationRecord,
    MemoryEntryRecord,
    MessageRecord,
    RunEventRecord,
    RunMemoryRecord,
    RunRecord,
    WorkspaceRecord,
)
from .approval_repo import ApprovalRepository
from .base import (
    MAX_MEMORY_CHARS,
    MAX_MEMORY_CONTENT_CHARS,
    MAX_MEMORY_ENTRIES,
    PersistenceConflictError,
    PersistenceNotFoundError,
)
from .conversation_repo import ConversationRepository
from .event_repo import RunEventRepository
from .memory_repo import MemoryRepository
from .message_repo import MessageRepository
from .run_repo import RunRepository
from .workspace_repo import WorkspaceRepository
from .safe_events import UnsafeEventError, safe_approval_data, sanitize_run_event
from .service import PersistenceService, RunCreation

__all__ = [
    "ACTIVE_RUN_STATUSES",
    "TERMINAL_RUN_STATUSES",
    "ApprovalRecord",
    "ApprovalRepository",
    "ApprovalStatus",
    "ConversationRecord",
    "ConversationRepository",
    "MemoryEntryRecord",
    "MemoryKind",
    "MemoryRepository",
    "MemorySource",
    "MAX_MEMORY_CHARS",
    "MAX_MEMORY_CONTENT_CHARS",
    "MAX_MEMORY_ENTRIES",
    "MessageRecord",
    "MessageRepository",
    "MessageRole",
    "PermissionMode",
    "PersistenceConflictError",
    "PersistenceNotFoundError",
    "PersistenceService",
    "RunCreation",
    "RunEventRecord",
    "RunEventRepository",
    "RunMemoryRecord",
    "RunRecord",
    "RunRepository",
    "RunStatus",
    "UnsafeEventError",
    "WorkspaceRecord",
    "WorkspaceRepository",
    "safe_approval_data",
    "sanitize_run_event",
]
