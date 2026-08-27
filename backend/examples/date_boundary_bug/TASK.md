# Task: fix the inclusive `--to` date boundary

`logstats` summarizes JSONL log files and accepts inclusive `--from` and `--to`
calendar dates. Its current `--to YYYY-MM-DD` handling only includes the first
instant of that date (`00:00:00`).

Fix the implementation so that `--to` includes the entire named day through
`23:59:59.999999`, while a record at `00:00:00` on the following day remains
excluded.

Requirements:

- Add at least one focused regression test for the missing end-of-day behavior.
- Preserve the CLI arguments, JSON output schema, and all other behavior.
- Keep the implementation timezone-naive; timezone support is outside this task.
- Run the full test suite before declaring the task complete.
