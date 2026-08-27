from __future__ import annotations

from evaluation.verify_date_boundary import _candidate_environment


def test_candidate_process_never_inherits_api_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-leak")
    monkeypatch.setenv("CUSTOM_API_KEY", "must-not-leak")
    monkeypatch.setenv("CUSTOM_TOKEN", "must-not-leak")
    monkeypatch.setenv("PYTHONPATH", "outside-project")

    environment = _candidate_environment(tmp_path)

    assert "DEEPSEEK_API_KEY" not in environment
    assert "CUSTOM_API_KEY" not in environment
    assert "CUSTOM_TOKEN" not in environment
    assert environment["PYTHONPATH"] == str(tmp_path / "src")
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTHONNOUSERSITE"] == "1"
