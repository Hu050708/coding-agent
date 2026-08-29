"""配置来源优先级的基础测试。"""

import json

from appconfig.loader import load_settings
from appconfig.models import Settings


def config_file(tmp_path, payload: dict[str, object]):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cli_values_override_all_sources(tmp_path) -> None:
    path = config_file(tmp_path, {"retries": 7, "debug": False, "label": "file"})

    result = load_settings(
        path,
        retries=2,
        debug=True,
        label="cli",
        environ={"APP_RETRIES": "5", "APP_DEBUG": "false", "APP_LABEL": "env"},
    )

    assert result == Settings(retries=2, debug=True, label="cli")


def test_environment_overrides_file(tmp_path) -> None:
    path = config_file(tmp_path, {"retries": 7, "debug": False, "label": "file"})

    result = load_settings(
        path,
        environ={"APP_RETRIES": "5", "APP_DEBUG": "true", "APP_LABEL": "env"},
    )

    assert result == Settings(retries=5, debug=True, label="env")


def test_file_overrides_defaults(tmp_path) -> None:
    path = config_file(tmp_path, {"retries": 7, "debug": True, "label": "file"})

    assert load_settings(path, environ={}) == Settings(retries=7, debug=True, label="file")


def test_defaults_fill_missing_values(tmp_path) -> None:
    path = config_file(tmp_path, {})

    assert load_settings(path, environ={}) == Settings(retries=3, debug=False, label="default")
