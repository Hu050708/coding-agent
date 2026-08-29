"""日期边界 verifier 的向后兼容入口。"""

from evaluation.core.contracts import CheckResult
from evaluation.core.environment import candidate_environment as _candidate_environment
from evaluation.tasks.date_boundary.verifier import (
    DateBoundaryVerifier,
    main,
    verify,
)

__all__ = [
    "CheckResult",
    "DateBoundaryVerifier",
    "_candidate_environment",
    "main",
    "verify",
]


if __name__ == "__main__":
    raise SystemExit(main())
