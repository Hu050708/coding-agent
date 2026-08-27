# logstats date-boundary demo

This is a deliberately small project used to demonstrate Coding Agent on a real
bug-fixing task. Each input line is a JSON object with an ISO-8601 `timestamp`
and a `level`.

```powershell
python -m pip install -e .
python -m logstats.cli examples/sample.jsonl --from 2026-08-25 --to 2026-08-26
```

The command prints a stable JSON object containing the selected record total
and counts grouped by level. See `TASK.md` for the exercise.
