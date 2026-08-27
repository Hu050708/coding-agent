"""Server-only configuration for the local Coding Agent Web UI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

from coding_agent.providers import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
)


DEFAULT_ALLOWED_ROOT = Path(r"E:\code")
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _default_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Coding Agent"
    return Path.home() / ".local" / "share" / "Coding Agent"


class SettingsError(ValueError):
    """Raised when server configuration is unsafe or malformed."""


def _dotenv_values(path: Path) -> dict[str, str]:
    """Read a deliberately small, non-executing subset of dotenv syntax."""

    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SettingsError("The configured env file could not be read safely.") from exc
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        name = name.strip()
        if not name or not name.replace("_", "A").isalnum():
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        values[name] = value
    return values


def _parse_int(name: str, value: str | None, default: int, *, minimum: int, maximum: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise SettingsError(f"{name} must be an integer.") from exc
    if parsed < minimum or parsed > maximum:
        raise SettingsError(f"{name} must be between {minimum} and {maximum}.")
    return parsed


def _parse_float(
    name: str,
    value: str | None,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if value is None or not value.strip():
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a number.") from exc
    if not math.isfinite(parsed) or parsed < minimum or parsed > maximum:
        raise SettingsError(f"{name} must be between {minimum:g} and {maximum:g}.")
    return parsed


def _parse_bool(name: str, value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"{name} must be a boolean value.")


def _valid_base_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Validated immutable settings shared by one local server process."""

    api_key: str = field(default="", repr=False)
    allowed_root: Path = DEFAULT_ALLOWED_ROOT
    data_dir: Path = field(default_factory=_default_data_dir)
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_active_runs: int = 1
    max_retained_runs: int = 50
    event_buffer_size: int = 256
    approval_timeout_seconds: float = 480.0
    max_model_calls: int = 16
    max_tool_calls: int = 40
    max_total_tokens: int = 200_000
    wall_time_seconds: float = 480.0
    api_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_transient_retries: int = 3
    trace_enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8000

    def __post_init__(self) -> None:
        root = Path(self.allowed_root).expanduser()
        if not root.is_absolute():
            raise SettingsError("CODING_AGENT_ALLOWED_ROOT must be an absolute path.")
        try:
            root = root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SettingsError("CODING_AGENT_ALLOWED_ROOT must be an existing directory.") from exc
        if not root.is_dir():
            raise SettingsError("CODING_AGENT_ALLOWED_ROOT must be a directory.")
        object.__setattr__(self, "allowed_root", root)

        data_dir = Path(self.data_dir).expanduser()
        if not data_dir.is_absolute():
            raise SettingsError("CODING_AGENT_DATA_DIR must be an absolute path.")
        try:
            data_dir = data_dir.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise SettingsError("CODING_AGENT_DATA_DIR is invalid.") from exc
        try:
            common = os.path.commonpath((os.fspath(root), os.fspath(data_dir)))
        except ValueError:
            # Paths on different Windows drives cannot overlap.
            common = ""
        if os.path.normcase(common) == os.path.normcase(os.fspath(root)):
            raise SettingsError(
                "CODING_AGENT_DATA_DIR must be outside CODING_AGENT_ALLOWED_ROOT."
            )
        object.__setattr__(self, "data_dir", data_dir)

        if self.host != "127.0.0.1":
            raise SettingsError("Coding Agent Web must bind to 127.0.0.1.")
        if not isinstance(self.model, str) or not self.model.strip():
            raise SettingsError("The model must be non-empty text.")
        if not _valid_base_url(self.base_url):
            raise SettingsError("The provider base URL is invalid.")

        integer_ranges = {
            "max_tokens": (self.max_tokens, 1, 1_000_000),
            "max_active_runs": (self.max_active_runs, 1, 4),
            "max_retained_runs": (self.max_retained_runs, 1, 1_000),
            "event_buffer_size": (self.event_buffer_size, 32, 10_000),
            "max_model_calls": (self.max_model_calls, 1, 1_000),
            "max_tool_calls": (self.max_tool_calls, 1, 10_000),
            "max_total_tokens": (self.max_total_tokens, 1, 10_000_000),
            "max_transient_retries": (self.max_transient_retries, 0, 20),
            "port": (self.port, 1, 65_535),
        }
        for name, (value, minimum, maximum) in integer_ranges.items():
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise SettingsError(f"{name} must be an integer between {minimum} and {maximum}.")
        if self.max_retained_runs < self.max_active_runs:
            raise SettingsError("max_retained_runs must be at least max_active_runs.")
        number_ranges = {
            "approval_timeout_seconds": (self.approval_timeout_seconds, 1.0, 86_400.0),
            "wall_time_seconds": (self.wall_time_seconds, 1.0, 86_400.0),
            "api_timeout_seconds": (self.api_timeout_seconds, 1.0, 600.0),
        }
        for name, (value, minimum, maximum) in number_ranges.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not minimum <= float(value) <= maximum
            ):
                raise SettingsError(f"{name} must be between {minimum:g} and {maximum:g}.")

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key.strip())

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        env_file: str | os.PathLike[str] | None = DEFAULT_ENV_FILE,
    ) -> "AppSettings":
        source = os.environ if environ is None else environ
        file_values = _dotenv_values(Path(env_file)) if env_file is not None else {}

        def get(name: str) -> str | None:
            value = source.get(name)
            return value if value is not None else file_values.get(name)

        allowed_root = Path(get("CODING_AGENT_ALLOWED_ROOT") or DEFAULT_ALLOWED_ROOT)
        return cls(
            api_key=(get("DEEPSEEK_API_KEY") or "").strip(),
            allowed_root=allowed_root,
            data_dir=Path(get("CODING_AGENT_DATA_DIR") or _default_data_dir()),
            model=(get("CODING_AGENT_MODEL") or DEFAULT_MODEL).strip(),
            base_url=(get("CODING_AGENT_BASE_URL") or DEFAULT_BASE_URL).strip(),
            max_tokens=_parse_int(
                "CODING_AGENT_MAX_TOKENS", get("CODING_AGENT_MAX_TOKENS"), DEFAULT_MAX_TOKENS,
                minimum=1, maximum=1_000_000,
            ),
            max_active_runs=_parse_int(
                "CODING_AGENT_MAX_ACTIVE_RUNS", get("CODING_AGENT_MAX_ACTIVE_RUNS"), 1,
                minimum=1, maximum=4,
            ),
            max_retained_runs=_parse_int(
                "CODING_AGENT_MAX_RETAINED_RUNS", get("CODING_AGENT_MAX_RETAINED_RUNS"), 50,
                minimum=1, maximum=1_000,
            ),
            event_buffer_size=_parse_int(
                "CODING_AGENT_EVENT_BUFFER_SIZE", get("CODING_AGENT_EVENT_BUFFER_SIZE"), 256,
                minimum=32, maximum=10_000,
            ),
            approval_timeout_seconds=_parse_float(
                "CODING_AGENT_APPROVAL_TIMEOUT_SECONDS", get("CODING_AGENT_APPROVAL_TIMEOUT_SECONDS"), 480.0,
                minimum=1.0, maximum=86_400.0,
            ),
            max_model_calls=_parse_int(
                "CODING_AGENT_MAX_MODEL_CALLS", get("CODING_AGENT_MAX_MODEL_CALLS"), 16,
                minimum=1, maximum=1_000,
            ),
            max_tool_calls=_parse_int(
                "CODING_AGENT_MAX_TOOL_CALLS", get("CODING_AGENT_MAX_TOOL_CALLS"), 40,
                minimum=1, maximum=10_000,
            ),
            max_total_tokens=_parse_int(
                "CODING_AGENT_MAX_TOTAL_TOKENS", get("CODING_AGENT_MAX_TOTAL_TOKENS"), 200_000,
                minimum=1, maximum=10_000_000,
            ),
            wall_time_seconds=_parse_float(
                "CODING_AGENT_WALL_TIME_SECONDS", get("CODING_AGENT_WALL_TIME_SECONDS"), 480.0,
                minimum=1.0, maximum=86_400.0,
            ),
            api_timeout_seconds=_parse_float(
                "CODING_AGENT_API_TIMEOUT_SECONDS", get("CODING_AGENT_API_TIMEOUT_SECONDS"),
                DEFAULT_TIMEOUT_SECONDS, minimum=1.0, maximum=600.0,
            ),
            max_transient_retries=_parse_int(
                "CODING_AGENT_MAX_TRANSIENT_RETRIES", get("CODING_AGENT_MAX_TRANSIENT_RETRIES"), 3,
                minimum=0, maximum=20,
            ),
            trace_enabled=_parse_bool(
                "CODING_AGENT_TRACE_ENABLED", get("CODING_AGENT_TRACE_ENABLED"), True
            ),
            port=_parse_int(
                "CODING_AGENT_WEB_PORT", get("CODING_AGENT_WEB_PORT"), 8000,
                minimum=1, maximum=65_535,
            ),
        )


__all__ = ["AppSettings", "DEFAULT_ALLOWED_ROOT", "DEFAULT_ENV_FILE", "SettingsError"]
