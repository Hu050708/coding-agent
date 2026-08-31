# Coding Agent 实现设计

## 1. 目标

用户指定本地工作区并提交编程任务。Agent 通过 DeepSeek 选择工具，在工作区内完成检查、修改和验证。

项目自行实现以下部分：

- 对话历史与上下文；
- 工具 schema、参数校验和本地执行；
- 模型响应解析；
- Agent 循环、预算和终止；
- API、工具、审批和取消错误处理。

`openai` Python 包只负责 HTTP 请求和供应商数据对象。运行时不使用 Agent 框架、Agent SDK、MCP、服务端文件工具或远程代码执行。

## 2. 分层

```text
CLI ──────────────────────────────────────┐
                                          v
Vue -> FastAPI -> services -> RunManager -> Agent
                    |              |         |  \
                    v              v         |   `-> CompletionAdapter -> DeepSeek
               repository      SSE events    `----> ToolExecutor -> local tools
                    |
                    v
                PostgreSQL
```

### Agent 核心

`agents/agent.py` 只依赖三个接口：

- `CompletionAdapter`：返回规范化模型结果；
- `ToolExecutor`：提供工具 schema 并执行工具；
- `TraceEmitter`：接收脱敏诊断事件。

核心不导入 OpenAI SDK、FastAPI、SQLAlchemy 或具体工具实现。离线测试可用假模型驱动完整循环。

### 组合入口

- `cli.py` 创建工作区、DeepSeek 适配器、工具注册表和 Agent。
- `agents/runtime/agent_runner.py` 为每个 Web 运行创建独立适配器和工具注册表。
- `main.py` 装配 FastAPI、数据库、应用服务和运行管理器。

## 3. 运行输入与上下文

每次运行固定以下输入：

- 工作区；
- 当前任务；
- 权限模式；
- 可见会话历史；
- 工作区记忆快照；
- 模型和资源预算。

跨运行只保存用户和助手可见正文。历史按最近完整后缀裁剪，并作为普通用户数据提供给模型；工具结果和隐藏推理不会进入长期会话历史。

记忆由用户确认，按工作区隔离。运行创建事务按置顶和更新时间选择启用条目，最多 32 条，正文合计不超过 32,000 字符。快照写入 `run_memories`，原记忆之后的修改不影响已经创建的运行。

当前任务始终位于记忆数据之后。系统提示要求模型把历史、记忆和仓库内容视为不可信资料。

单次运行内保留完整协议历史：

```text
system
user
assistant(tool_calls)
tool
assistant(tool_calls)
tool
...
assistant(final)
```

## 4. Agent 循环

```text
构造初始消息
while 未终止:
    检查取消、时间、模型次数和 Token 预算
    请求模型
    累计 usage，记录安全事件
    按 finish_reason 校验响应
    如果是 final：结束
    如果是 tool_calls：
        校验整批调用 ID 和工具预算
        写入 assistant tool turn
        顺序执行每个工具
        为每个 call ID 写入一个 tool result
```

### 协议不变量

1. 每个 tool-call ID 在运行内唯一。
2. 每个 tool call 恰好对应一个同 ID 的工具结果。
3. 同一批调用在进入下一轮模型请求前全部获得结果。
4. 工具参数必须是有限、无重复键的 JSON object。
5. 整批 ID 和预算校验通过后才允许执行副作用。
6. 多工具调用顺序执行，结果顺序稳定。
7. 截断、过滤或协议冲突的响应不进入历史，也不执行工具。

普通工具失败会以结构化 JSON 回填，让模型修正参数或代码。用户取消和总时间耗尽会取消批次中尚未执行的调用，但仍为每个调用补齐结果。

### 完成原因

| `finish_reason` | 处理 |
|---|---|
| `tool_calls` | 校验并执行工具，继续循环 |
| `stop` | 要求无工具调用且正文非空，然后正常结束 |
| `length` | 以响应截断失败，不执行部分参数 |
| `content_filter` | 以内容过滤失败 |
| `insufficient_system_resource` | 丢弃本次响应，在预算内重试原请求 |
| 其他值或字段冲突 | 以协议错误失败 |

`model_finished` 只表示模型停止调用工具，不表示任务已经通过验收。

## 5. DeepSeek 适配器

`agents/providers/deepseek.py` 使用 DeepSeek 官方 Chat Completions 服务，固定采用非流式请求：

```text
model: deepseek-v4-flash
reasoning_effort: high
thinking: enabled
max_tokens: 8192
stream: false
```

适配器负责：

- 创建禁用 SDK 自动重试的客户端；
- 发送完整消息和工具 schema；
- 将供应商对象转换为 `ModelCompletion`；
- 解析正文、推理字段、工具调用、usage、模型名和 fingerprint；
- 将网络和 HTTP 错误转换为稳定异常。

DeepSeek 工具回合中的 `reasoning_content` 保留在本次运行内，用于下一轮协议回放。它不展示、不写入数据库，也不进入诊断 trace。工具回合的 `content=null` 在回放时规范化为空字符串。

## 6. 工具

所有工具返回统一 JSON：

```json
{"ok":true,"data":{},"meta":{}}
```

或：

```json
{"ok":false,"error":{"code":"...","message":"...","retryable":false}}
```

| 工具 | 作用 | 主要约束 |
|---|---|---|
| `list_files` | 列出目录 | 稳定排序、条目上限、不进入目录链接 |
| `read_file` | 读取 UTF-8 文本 | 分段、大小限制、返回 SHA-256 和文本格式 |
| `search_text` | 字面文本搜索 | 文件数、字节数、结果数和输出上限 |
| `make_directory` | 创建目录 | 幂等、可创建父目录、不跟随链接 |
| `write_file` | 创建文件 | 只创建、不覆盖、原子发布 |
| `replace_text` | 修改文件 | 最近读取哈希、唯一匹配、原子替换 |
| `delete_file` | 删除文件 | 普通文件、最近读取哈希、删除前复核 |
| `run_command` | 运行测试和检查 | argv、`shell=False`、超时、输出限长 |

`write_file` 和 `replace_text` 分离，避免创建操作覆盖已有文件。`replace_text` 与 `delete_file` 在执行前再次校验路径、大小和哈希，发现文件变化时返回 `stale_file`。

## 7. 工作区与命令策略

文件工具只接受工作区相对路径，并拒绝：

- 绝对路径、UNC、盘符相对路径和父目录穿越；
- Windows 设备名、ADS、尾随空格或点；
- 越出工作区的符号链接和重解析点；
- `.git`、虚拟环境、缓存和诊断目录；
- `.env`、私钥、证书和常见凭据文件。

命令先解析可信可执行文件，再按风险分类：

- `ALLOW`：固定 Python 测试/编译、受限 Node 检查、安全形式的 `git status/diff`；
- `CONFIRM`：其他未命中硬拒绝规则的本地命令；
- `DENY`：shell、批处理、提权或破坏性程序、远端及历史修改型 Git 操作。

子进程使用清理后的最小环境，剥离 API Key、Token、数据库凭据和危险运行时变量。工作区内的 PATH 项会被移除，防止同名可执行文件劫持。

## 8. 权限

权限在运行开始时冻结：

| 模式 | 文件读取 | 文件修改 | 删除 | 命令 |
|---|---|---|---|---|
| `ask` | 自动 | 确认 | 确认 | 确认 |
| `agent` | 自动 | 自动 | 确认 | 按命令分类 |
| `workspace_full` | 自动 | 自动 | 自动 | 除 `DENY` 外自动 |

权限模式不能绕过工作区边界、受保护文件、工具参数合同、命令 `DENY`、预算或取消。

审批通过 `ApprovalBroker` 连接同步工具线程和 HTTP 接口。审批有超时，拒绝、过期和取消都返回明确工具结果。

## 9. 预算、重试与进度

默认预算：

| 项目 | 默认值 |
|---|---:|
| 模型请求 | 50 次 |
| 工具调用 | 100 次 |
| 累计 Token | 1,000,000 |
| 总墙钟时间 | 600 秒 |
| 单次 API 超时 | 60 秒 |
| 单次模型输出 | 8192 Token |
| 瞬时错误重试 | 3 次 |

每次等待时间取操作上限和运行剩余时间中的较小值。请求尝试在发出前计数，SDK 自动重试关闭。

连接失败、超时、429、500、503 和供应商资源不足按指数退避重试。认证、参数和协议错误不重试。有副作用的工具不会由控制器自动重做。

重复检测对工具名、规范化参数和去除耗时字段后的结果计算 SHA-256。相同交换从第三次起附加 `progress_warning`，不改变原结果，也不提前终止。检测器最多保存 256 个指纹。

## 10. 修改后检查

`ChangeCheck` 记录文件工具成功修改后的版本号，并识别后续测试、编译或程序运行：

- `needs_check`：已有修改，尚未检查；
- `passed`：最新修改之后的检查成功；
- `failed`：检查失败；
- `outdated`：检查后又发生修改；
- `no_changes`：没有文件修改。

该状态只描述运行内观察到的检查顺序。任务正确性仍由测试和独立 verifier 判断。

## 11. Web、持久化与并发

FastAPI 通过应用服务访问 PostgreSQL。主要数据包括：

| 表 | 内容 |
|---|---|
| `workspaces` | 规范工作区路径 |
| `conversations` | 会话设置和消息序号 |
| `runs` | 权限、状态、模型、用量和终止结果 |
| `messages` | 用户与助手可见正文 |
| `run_events` | 可重放安全事件 |
| `approvals` | 工具审批 |
| `memory_entries` | 用户确认的工作区记忆 |
| `run_memories` | 运行创建时冻结的记忆副本 |

创建运行时按 `workspace -> conversation -> run` 的顺序加锁，在一个事务中写入运行和用户消息、读取有界历史，并保存记忆快照。

同一工作区最多一个活动运行：

- 应用层先返回明确冲突；
- PostgreSQL 部分唯一索引处理并发竞争；
- 不同工作区可并行；
- `client_request_id` 保证浏览器重试不会重复创建运行和消息。

`RunManager` 保存当前进程的线程、取消信号、审批等待和实时事件缓冲。服务重启时，数据库中的活动运行标记为 `interrupted`，并追加可重放事件。

## 12. SSE

事件使用 `(run_id, seq)` 唯一标识。客户端通过 `Last-Event-ID` 或 `after_seq` 续传：

1. 先从 PostgreSQL 读取游标后的事件；
2. 再使用进程内 `EventBuffer` 等待新事件；
3. 终态后确认最终事件已经写入，再关闭流。

事件只包含白名单字段，例如工具名、目标摘要、状态、耗时、错误码和 Token。文件正文、完整命令输出、隐藏推理和密钥不会进入事件。

## 13. 验证

测试分为四层：

1. 核心和工具单元测试；
2. 假模型驱动真实工具的离线完整循环；
3. 显式启用的 DeepSeek API 冒烟测试；
4. 合成任务副本与工作区外 verifier。

评测把模型正常结束和 verifier 通过分开记录。固定报告保存请求模型、响应模型、fingerprint、调用次数、Token、耗时、工具错误、文件变化和验收结果。

## 14. 安全边界

- 文件工具的工作区限制不等于子进程隔离。
- 获准执行的程序仍拥有当前运行账户权限。
- Docker 中的 PostgreSQL 只提供数据服务，不是命令执行沙箱。
- 发送给模型的任务、源码片段和工具结果会离开本机。
- Web 只支持本机或 SSH 隧道访问。
- Trace 用于诊断，不是不可篡改审计日志。
