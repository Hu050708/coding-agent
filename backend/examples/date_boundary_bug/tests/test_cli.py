import json

from logstats.cli import main


def test_cli_emits_stable_json(tmp_path, capsys) -> None:
    log_file = tmp_path / "events.jsonl"
    log_file.write_text(
        '{"timestamp":"2026-08-25T12:30:00","level":"INFO"}\n',
        encoding="utf-8",
    )

    assert main([str(log_file)]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "total": 1,
        "levels": {"INFO": 1},
    }
