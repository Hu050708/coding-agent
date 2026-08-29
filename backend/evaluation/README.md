# Coding Agent 可复现评测

评测系统直接调用项目自己的 CLI，不经过 FastAPI、前端或数据库。每轮先把固定任务模板
复制到新的临时工作区，再由 Agent 修改该副本，最后在工作区外启动独立 verifier。
模型声称完成不代表成功；只有 Agent 正常结束且 verifier 全部通过才计为成功。

## 三类任务

| ID | 类型 | 主要能力 |
|---|---|---|
| `date_boundary` | Bug 修复 | 阅读代码、日期边界、回归测试 |
| `category_filter` | 多文件功能 | CLI、服务层、筛选逻辑和兼容性 |
| `config_precedence` | 回归修复 | 跨来源数据流、合法 falsey 值和优先级 |

每个任务都有 Agent 可见的 `TASK.md`、源码和基础测试，以及 Agent 工作区之外的
verifier 和参考修复覆盖层。自动化测试会证明原始模板无法通过隐藏验收，而参考修复可以
通过，避免评测任务本身失效。

## 运行

在 `backend/` 目录执行完整的 3×3 评测：

```powershell
conda activate coding-agent
$env:DEEPSEEK_API_KEY="你的实际密钥"
python -m evaluation.run_benchmark --model deepseek-v4-flash --repeats 3
```

只调试单个任务：

```powershell
python -m evaluation.run_benchmark --task date_boundary --repeats 1
```

结果默认写入 `backend/tmp/benchmark-runs/benchmark-<UTC时间>/`：

- `trials/<trial-id>/workspace/`：本轮候选副本；
- `agent.stdout.log`、`agent.stderr.log`：合成任务运行日志；
- `trial.json`：单轮结构化指标和独立验收结果；
- `summary.json`：全部轮次的机器可读汇总；
- `BENCHMARK_REPORT.md`：面向评审的中文报告。

评测顺序执行，避免并发请求影响结果。报告记录 Git 提交和工作区脏状态，但不会因此阻止
试验。`deepseek-v4-flash` 是滚动别名，因此每轮同时记录供应商返回的实际模型名称和
fingerprint；三次重复仅提供描述性证据，不宣称统计显著性。

## 记录和边界

评测从现有安全 JSONL trace 读取模型调用、工具调用、Token、耗时、错误码、重复调用提示
和终止原因，并用文件哈希统计新增、修改和删除的相对路径。它不记录提示词、隐藏推理、
文件正文、完整命令输出或 API 凭据。

verifier 子进程会移除类似 API Key、Token、Secret 和 Password 的环境变量，并在 Agent
工作区外生成验收数据。它仍然只是本地进程隔离，不是操作系统级沙箱；这些固定任务均为
仓库内可丢弃的合成项目，不应使用该评测器执行任意下载代码。

旧的单任务命令仍然保留：

```powershell
python evaluation/verify_date_boundary.py <候选目录>
python scripts/run_demo_trial.py
```
