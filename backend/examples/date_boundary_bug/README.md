# logstats 日期边界演示

这是一个刻意精简的小项目，用于演示 Coding Agent 如何处理真实的缺陷修复任务。
每个输入行都是一个 JSON 对象，包含 ISO-8601 格式的 `timestamp` 和 `level`。

```powershell
python -m pip install -e .
python -m logstats.cli examples/sample.jsonl --from 2026-08-25 --to 2026-08-26
```

该命令会输出结构稳定的 JSON 对象，其中包含选中记录的总数以及按级别分组的计数。
练习要求见 `TASK.md`。
