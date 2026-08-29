"""应用配置模型。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """合并完成后的三个配置值。"""

    retries: int
    debug: bool
    label: str
