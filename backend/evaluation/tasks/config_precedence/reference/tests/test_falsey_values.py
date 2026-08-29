"""falsey 值配置回归测试。"""

import json

from appconfig.loader import load_settings
from appconfig.models import Settings


def test_cli_falsey_values_override_environment(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"retries": 7, "debug": True, "label": "file"}), encoding="utf-8")

    result = load_settings(
        path,
        retries=0,
        debug=False,
        label="",
        environ={"APP_RETRIES": "5", "APP_DEBUG": "true", "APP_LABEL": "env"},
    )

    assert result == Settings(retries=0, debug=False, label="")
