# Coding Agent 可复现评测

评测器通过项目 CLI 运行真实 Agent。每轮复制新的任务工作区，Agent 只修改该副本，随后由工作区外的 verifier 验收。

一次试验计为成功必须同时满足：

1. Agent 进程正常结束；
2. verifier 的全部检查通过。

模型最终回答不参与通过判定。

## 任务

| ID | 类型 | 验收重点 |
|---|---|---|
| `date_boundary` | Bug 修复 | 日期结束边界、回归测试、原行为 |
| `category_filter` | 多文件功能 | CLI 参数、服务逻辑、多类别和兼容性 |
| `config_precedence` | 回归修复 | falsey 值、配置优先级和原行为 |

每个任务包含：

- Agent 可见的 `TASK.md`、源码和基础测试；
- 工作区外的 verifier；
- 用于验证任务有效性的参考修复。

自动测试确认原始模板无法通过隐藏验收，参考修复可以通过。

## 执行流程

```text
任务模板
  -> 复制到新目录
  -> 调用 coding_agent CLI
  -> 收集安全 trace 和文件变化
  -> 清理 verifier 子进程环境
  -> 在工作区外执行 verifier
  -> 写入 trial.json、summary.json 和 Markdown 报告
```

试验顺序执行，避免并发请求影响耗时和限流结果。

## 运行

在 `backend/` 目录执行：

```powershell
conda activate coding-agent
$env:DEEPSEEK_API_KEY="你的密钥"
python -m evaluation.run_benchmark --model deepseek-v4-flash --repeats 3
```

只运行指定任务：

```powershell
python -m evaluation.run_benchmark --task date_boundary --repeats 1
```

可重复指定任务：

```powershell
python -m evaluation.run_benchmark --task date_boundary --task config_precedence --repeats 3
```

指定输出目录或运行时间：

```powershell
python -m evaluation.run_benchmark --output tmp/my-run --wall-time 480
```

## 输出

默认目录：

```text
tmp/benchmark-runs/benchmark-<UTC时间>/
├─ trials/<trial-id>/
│  ├─ workspace/        # 候选副本
│  ├─ agent.stdout.log
│  ├─ agent.stderr.log
│  └─ trial.json        # 单轮结果
├─ summary.json         # 全部轮次汇总
└─ BENCHMARK_REPORT.md  # 中文报告
```

报告记录：

- 请求模型、供应商响应模型和 fingerprint；
- 源码提交号和工作区是否干净；
- Agent 状态与终止原因；
- 模型调用、工具调用和工具错误；
- Token、缓存命中和耗时；
- 新增、修改和删除的相对路径；
- 修改后检查状态；
- verifier 的逐项结果。

## 隔离与数据边界

- Agent 只能访问本轮候选副本；
- verifier 位于候选工作区之外；
- verifier 子进程不继承 API Key、Token、Secret 和 Password 类环境变量；
- trace 不保存提示词、隐藏推理、文件正文、完整命令输出或凭据；
- 候选项目是仓库内的可丢弃合成任务。

verifier 仍是本地子进程，不提供操作系统级隔离。不要用该评测器运行来源不明的代码。

## 固定结果

仓库保存的固定报告对应提交 `536c94158978afc68ab0a273635a94807bba5135`、模型 `deepseek-v4-flash` 和 2026-08-29 的 3×3 试验：

- 独立验收：9/9；
- Agent 端到端：9/9；
- 最后修改后检查通过：9/9。

结果文件：

- [BENCHMARK_REPORT.md](../docs/evaluation-results/benchmark-20260829T140452Z/BENCHMARK_REPORT.md)
- [summary.json](../docs/evaluation-results/benchmark-20260829T140452Z/summary.json)

该结果只描述固定提交和任务集，不代表任意项目上的成功率。

## 单次演示

日期边界演示会创建新候选目录、调用 Agent，再运行独立 verifier：

```powershell
python scripts/run_demo_trial.py
```

脚本拒绝覆盖已有输出，结果写入 `tmp/demo-runs/`。
