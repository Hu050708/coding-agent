# Coding Agent 编程智能体设计（v0.5，实现态）

日期：2026-08-27<br>
状态：核心闭环、FastAPI/Vue 会话工作台、三档权限与 PostgreSQL 持久化已实现<br>
原则：先证明一个最小闭环真实、可靠、合规，再增加功能。`Coding Agent` 表示核心循环透明、可观察、可解释。

v0.5 在不改变题目要求的自研 Agent 核心前提下增加了本机 WebUI、持久会话和项目记忆。仓库根层
只保留 `backend/`、`frontend/` 两个业务目录；Python 代码统一使用 `coding_agent` 命名空间。
Web 与记忆是核心循环之外的适配/编排能力，不替模型解析工具，也不替 Agent 执行状态机。

## 1. 项目目标

用户指定一个本地工作目录并给出一个编程任务。Coding Agent 使用 DeepSeek 官方 API 反复选择和调用本项目自定义的本地工具，完成：

```text
理解任务 -> 查看项目 -> 执行测试/命令 -> 修改文件 -> 再次验证 -> 汇报
```

题目要求的关键逻辑全部由本项目实现：

- 消息历史和上下文预算；
- 工具定义、参数解析、校验、注册和本地执行；
- 模型响应和 tool call 解析；
- agent 状态机、循环和终止条件；
- API 错误、工具错误、超时和取消处理。

运行时不使用现成 coding agent、agent 框架、agent SDK、服务端代码执行、服务端文件工具、服务端搜索或 MCP。

## 2. 已核实的模型事实

截至 2026-08-27：

- 官方 API 模型 ID 是 `deepseek-v4-flash`；当前后端版本标识为 DeepSeek-V4-Flash-0731。
- 该 ID 是滚动别名，当前没有发现可锁定 `0731` 的官方云 API ID。
- 官方仍将 Flash API 称为 public beta，因此运行轨迹必须记录日期、请求/响应模型 ID 和可用的 `system_fingerprint`。
- OpenAI-format base URL 是 `https://api.deepseek.com`。
- Chat Completions 支持思考模式和 function tool calls。
- 思考模式默认开启，默认 effort 为 `high`。
- 请求携带 `tools` 时，后续请求必须完整回传此前 assistant 的 `reasoning_content`，否则会返回 400。
- V4 thinking + tools 不支持 `tool_choice`，且回放的 tool-call assistant 消息必须有非 `null` 的 `content` 字段。
- 普通 tool calling 仍可能生成非法 JSON、额外字段或错误类型，必须本地校验。
- `/beta` strict mode 只支持 JSON Schema 子集，不作为首版可靠性或安全边界。

依据：

- [DeepSeek 更新日志](https://api-docs.deepseek.com/updates/)
- [模型与计费](https://api-docs.deepseek.com/quick_start/pricing/)
- [思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)
- [工具调用](https://api-docs.deepseek.com/guides/tool_calls/)
- [聊天补全 API](https://api-docs.deepseek.com/api/create-chat-completion/)
- [错误码](https://api-docs.deepseek.com/quick_start/error_codes/)

## 3. 冻结的核心选择

| 项目 | 首版选择 | 取舍 |
|---|---|---|
| 语言 | Python 3.11 | 标准库覆盖 CLI、文件、子进程、配置与日志 |
| 开发环境 | 全新 Conda 环境 | 与系统 Python 和旧项目隔离 |
| API | 非流式 Chat Completions | 状态结构小，DeepSeek 文档和测试面更清楚 |
| 客户端 | 官方 `openai` Python 包 | 只承担 HTTP/数据对象，不承担 agent 逻辑 |
| 模型 | `deepseek-v4-flash` | 官方现行、成本较低、面向 agent/coding 优化 |
| 思考模式 | 固定 `high` | 只实现和验证一种主路径，避免四套协议分支 |
| 工具 | 自定义 `type: function` | 远端只选择工具，本地解析和执行 |
| strict | 不使用 `/beta` | 始终本地校验，避免 beta 依赖 |
| 流式 | 不做 | 避免拼装流式 reasoning/tool-call 增量 |
| 命令 | `shell=False`、argv 数组、策略分级 | 不支持管道、重定向和复合 shell |
| 上下文 | 完整保留本次运行历史 | 通过有限轮次、token 预算和工具输出限长控制规模 |
| 目标平台 | 当前 Windows 主机（build 22000）实测 | POSIX 仅 best effort，不作放行承诺 |
| 界面 | CLI + 本机 FastAPI/Vue WebUI | 前后端分离，仅绑定 loopback，不改变 Agent 核心协议 |
| 持久化 | 独立 loopback PostgreSQL + SQLAlchemy/Alembic | Web 强制使用；CLI 保持数据库独立 |
| 记忆 | 工作区级 PostgreSQL + 手动确认写入 | 每次运行冻结实际送模集合；不允许模型自行持久化 |

只调用：

```python
client.chat.completions.create(...)
```

不使用 `openai-agents`、自动 tool runner、`chat.completions.parse()`、`pydantic_function_tool()` 或任何替项目解析/执行工具的 helper。SDK 设置 `max_retries=0`，重试策略由本项目实现。真实联调后固定已验证的 `openai` 版本，防止额外字段序列化行为漂移。

DeepSeek 参数固定为：

```python
model="deepseek-v4-flash"
reasoning_effort="high"
extra_body={"thinking": {"type": "enabled"}}
tools=<本地函数 schema>
max_tokens=8192
```

思考模式下不发送不兼容的 `tool_choice`，也不发送会被静默忽略的 `temperature`、`top_p`、`presence_penalty` 或 `frequency_penalty`。

## 4. 最小架构

```text
CLI ----------------------------------------------+
                                                   v
Vue -> FastAPI -> 应用服务 -> 运行管理器 -> Agent 控制器
                    |             |             |         |
                    v             v             |         `-> DeepSeek
                持久化层       安全 SSE 通知     v
                    |                       工具注册表 / 策略
                    v
              PostgreSQL
              工作区 / 会话 / 可见消息 / 运行 /
              安全事件 / 审批 / 工作区记忆
```

模块按职责分包，但不机械地为每个类建目录：

```text
backend/src/coding_agent/
  cli.py                    # 薄组合根：参数、配置、确认、退出码
  main.py / web.py          # FastAPI 组合根和 loopback Web 入口
  settings/settings.py      # 环境变量、.env 和运行参数
  router/                   # FastAPI 路由和 HTTP 错误映射
  schemas/                  # HTTP 请求与响应模型
  dependencies/             # FastAPI 依赖函数
  services/                 # 工作区、会话、运行和记忆用例
  models/                   # SQLAlchemy 模型与持久化枚举
  repository/               # 仓储、DTO、事务门面和安全事件
  database/                 # 连接、迁移和启动恢复
  agents/
    config.py               # 单次 Agent 运行的预算和重试配置
    contracts.py            # 值对象和依赖端口
    context.py              # 有界可见历史与不可变记忆上下文
    progress.py             # 完全重复工具交换的有界哈希检测
    tool_protocol.py        # 严格 JSON 与工具结果协议
    agent.py                # 状态机、消息历史和终止循环
    providers/deepseek.py   # API 请求、响应规范化、错误分类
    tools/                  # 六个工具的 schema、分发与实现
    security/               # 工作区、命令分级和三档权限
    runtime/                # 运行生命周期、审批、取消和实时事件
    memory/                 # Agent 记忆值、提示合同和 CLI 记忆服务
    diagnostics/trace.py    # 简单的脱敏 JSONL emit()
```

`agents/` 根部的循环只依赖 adapter/registry Protocol，不导入 OpenAI SDK、Web 或工具具体实现；
`agents/providers` 和 `agents/tools` 分别实现这些端口，CLI/FastAPI 负责装配。测试目录镜像源码职责边界，
并另设 live integration 和端到端测试；不为每个概念建立额外生产模块。

### 4.1 Web 运行边界

- FastAPI 只绑定 `127.0.0.1`，Vue 开发服务器通过同源 `/api` 代理访问后端。
- Web 强制使用独立 PostgreSQL：容器 `coding-agent-postgres`、卷
  `coding_agent_postgres_data`、loopback 端口 `5434`。启动时自动执行 Alembic 迁移；连接或迁移失败
  直接阻止 Web 启动，不回退 SQLite。开发启动顺序固定为 Compose PostgreSQL、FastAPI、Vue；
  CLI 不依赖数据库或 Web。
- PostgreSQL 持久化 workspace、conversation、可见 user/assistant message、run、白名单 event、
  approval 和 memory。隐藏推理、原始提供方响应、环境变量和完整工具输出没有持久化字段。
- `RunManager` 只在进程内执行活动任务、取消和审批；同一工作区由数据库部分唯一索引和事务锁保证
  最多一个活动 run，不同工作区可以并行。
- SSE 先按 `Last-Event-ID` 从 PostgreSQL 重放，再用进程内通知降低实时延迟。重启时未完成 run 被标为
  `interrupted` 并追加可重放事件，而不是伪装成可恢复执行。
- 每个 run 冻结一种后端权限：`ask` 对文件修改和命令逐次审批；`agent` 自动执行工作区修改和
  常规检查，只审批风险命令；`workspace_full` 自动执行工作区内所有非禁止操作。所有模式始终
  拒绝越界路径和 `DENY` 命令。
- 前端按 `app / features / shared` 分层，并使用 Vue Router + Pinia；workspace、conversation、chat、
  run、permission、memory 各自拥有类型、API、状态和组件。

### 4.2 第一版项目记忆边界

- 作用域只有数据库登记且规范化后的同一 workspace；不做跨项目或用户画像。
- workspace、conversation、可见消息和 memory 都在 PostgreSQL 中，但会话历史与工作区记忆是两类
  数据：历史只在当前 conversation 回放，memory 才能在同一 workspace 的不同 conversation 共享。
- 创建 run、写入当前 user message、截取可见历史并冻结 memory 在一个事务内完成。最终快照按置顶和
  更新时间排序，最多 32 条且正文总计不超过 32000 字符；`run_memories` 就是实际送给模型的集合。
- 记忆正文与当前任务一起序列化为普通 user JSON，当前任务固定放在最后。
- 只有显式 API/UI 操作才能新增、编辑、置顶、停用、删除或清空；运行结果保存前必须可编辑确认。
  模型没有保存记忆的工具；数据库只保存用户可见消息，不保存推理、原始工具结果或密钥。
- memory 写操作和 run 创建都先锁 workspace，固定 `workspace -> conversation -> run` 顺序；同一
  workspace 有活动 run 时，新增、编辑、删除和清空全部拒绝。运行结果来源只接受同 workspace 且
  状态为 `completed` 的 run。
- 首版不使用 embedding 或 pgvector 检索。PostgreSQL 是 Web 的强依赖；数据库异常会返回结构化错误
  或阻止启动，不声称在持久化失效后仍能维持 Web 会话一致性。

## 5. 状态机与协议不变量

状态：

```text
INITIALIZING
  -> REQUESTING_MODEL
  -> EXECUTING_TOOLS -> REQUESTING_MODEL -> ...
  -> MODEL_FINISHED | FAILED | CANCELLED | BUDGET_EXHAUSTED
```

`MODEL_FINISHED` 只表示模型正常停止调用工具，不表示编程任务已通过验收。外部验收结果单独记录为 `verified=true/false/unknown`。

主循环：

```text
加入系统消息和用户任务
循环（预算未耗尽）：
    检查剩余时间/token预算
    检查完整历史和剩余时间/token预算
    请求 DeepSeek
    校验 choice、finish_reason 和消息字段，暂不提交到对话历史
    若 finish_reason == tool_calls：
        提交完整 assistant 消息
        校验并顺序处理每个 tool_call
        为每个 call ID 追加恰好一个 tool result
        继续循环
    否则若 finish_reason == stop 且无 tool_calls 且 content 非空：
        提交完整 assistant 消息
        MODEL_FINISHED
    否则若 finish_reason == insufficient_system_resource：
        只记诊断事件，丢弃未完成响应并原样重试上一次请求
    否则：
        只记运行诊断，不污染消息历史；按决策表失败
```

必须满足：

1. 每个 tool call ID 唯一，并恰好对应一个 `role: tool` 结果。
2. 下一次模型请求前，同轮全部 tool calls 都必须获得执行、拒绝或取消结果。
3. 普通工具失败不取消其他独立调用；只有用户取消、全局预算耗尽或致命策略决定才取消剩余调用。
4. 工具参数必须是严格 JSON object；拒绝数组、标量、未知字段、重复 ID、`NaN` 和 `Infinity`。
5. thinking tool turn 的 `reasoning_content` 按原样保存在 assistant 消息并回传；不显示、不写事件日志。API 返回的 tool-call `content=null` 在回放时规范化为 `""`。
6. assistant 中的 `content`、`reasoning_content` 和全部 `tool_calls` 均由项目显式序列化，不能依赖 SDK 对额外字段的隐式保留。
7. 多工具调用只按顺序执行，不并发。修改工具带乐观并发 hash；状态改变后不满足 hash 的后续写操作会失败并要求模型重读。
8. 工具名、规范化参数和去除耗时字段后的结果连续三次完全相同时，只向第三次结果附加恢复提示；不修改原结果状态，也不提前终止运行。

### 5.1 `finish_reason` 决策表

| 结束原因 | 必须满足 | 控制器行为 |
|---|---|---|
| `tool_calls` | 非空、合法、唯一的 tool calls | 执行/拒绝每个调用并继续 |
| `stop` | 无 tool calls，`content` 非空 | `MODEL_FINISHED` |
| `length` | 无论是否有部分内容 | 不执行可能截断的工具参数；以 `truncated_response` 失败 |
| `content_filter` | - | 以明确原因失败 |
| `insufficient_system_resource` | - | 不提交 assistant 消息；原样有限重试上一次请求 |
| 字段与 reason 矛盾 | - | `protocol_error` |

## 6. 工具合同

统一结果：

```json
{"ok": true, "data": {}, "meta": {}}
```

或：

```json
{"ok": false, "error": {"code": "...", "message": "...", "retryable": false}}
```

### 6.1 P0 五个工具

#### `list_files`

- 相对目录、可选 glob、最大条目数。
- 稳定排序，默认最多 500 项。
- 不跟随目录 symlink/junction；跳过 `.git`、虚拟环境、缓存和 trace 目录。

#### `read_file`

- 相对路径、可选起止行。
- 支持 UTF-8 和 UTF-8-SIG；拒绝二进制、受保护文件和超大文件。
- 返回内容、编码/BOM、换行风格、SHA-256 和截断信息。
- 默认最多约 20K 字符，超出时要求分段读取。

#### `write_file`

- 只创建不存在的新文件，不提供由模型自行声明的覆盖开关。
- 同目录临时文件写入并 `flush/fsync` 后，用 fail-if-exists 的原子发布操作创建目标；当前
  Windows/Python 路径使用同卷 `os.link(temp, target)` 再删除临时链接。目标已存在时必须
  失败，不能退化为会覆盖的 `os.replace`；任何失败都清理临时文件。

#### `replace_text`

- 参数包括相对路径、`old_text`、`new_text`、期望匹配次数和最近一次读取得到的 `expected_sha256`。
- 默认要求恰好匹配一次；hash 不符、0 次或多次均不写文件。
- 保留原 UTF-8 BOM 与 CRLF/LF；与 `write_file` 共用原子写路径。

#### `run_command`

- 参数：`argv: list[str]`、相对 `cwd`、超时。
- `shell=False`、stdin=`DEVNULL`、清理后的环境、stdout/stderr 分离、返回 exit code 和 duration。
- 输出先写有界临时存储，再只读取头尾，不能先全量读进内存后截断。
- 按 bytes 限制，优先 UTF-8，失败时使用系统编码并替换非法字节。
- Windows 超时采用经测试的尽力进程树清理；不宣称对所有孙进程有强保证。

### 6.2 P1 工具

`search_text` 已作为第六个工具实现。它在工作区 UTF-8 文件中执行单行字面文本搜索，支持相对目录、
glob、大小写开关、结果上限和最多三行上下文。扫描文件数、总字节数、单文件大小和输出字符数均有
独立上限；稳定排序，不跟随目录链接，并复用 `Workspace` 的受保护路径规则。它不通过 shell 或
外部 `rg` 执行，在三档权限中均属于自动执行的只读工具。

## 7. Windows 路径与受保护文件

文件工具只接受相对路径。至少拒绝：

- `..` 越界；
- 绝对路径、UNC、`\` 根路径、`\\?\`、`\\.\`；
- 盘符相对路径，如 `C:foo`；
- NTFS ADS，如 `file.txt:stream`；
- `CON/NUL/PRN/AUX/COM1/LPT1` 等设备名；
- 结尾空格或点；
- 解析后位于 workspace 外的现有 symlink/junction；
- `.git` 内部、trace 目录和虚拟环境写入；
- `.env`、`.env.local`、私钥/证书等真实凭据文件的读取和写入；允许 `.env.example`。

对不存在的目标，先严格解析最近的现有 parent，再检查边界。实际写入前再次校验，以降低 TOCTOU 风险。恶意 reparse point 与并发替换不是首版能够完全消除的安全风险，文档必须明确。

## 8. 命令策略与真实安全边界

命令分为：

- `ALLOW`：固定的测试和编译检查，如当前 Conda 环境的 `sys.executable -m pytest/unittest/compileall`。
- `CONFIRM`：其他可识别、非提权、非 shell 的本地命令，包括看似只读但可能受仓库 hooks、diff driver 或配置影响的 `git status/diff`。用户可逐条确认；`--yes` 只在可信、可回滚的演示副本中自动批准此类命令。
- `DENY`：显式 shell 宿主（PowerShell/cmd/bash/wsl）、提权、远端 Git 修改、明显破坏宿主机或项目历史的命令。

`--yes` 不能绕过 `DENY`。`.bat/.cmd` 具有 shell 语义，归入确认或拒绝。`python -c`、`python -m pip`、工作区脚本执行和网络工具不会被误判为普通只读测试。

可执行文件使用清理后的 PATH 解析为绝对位置，防止工作目录内同名 `python.exe`/`git.exe` 抢占；测试优先固定为当前 `sys.executable -m pytest`。

必须诚实说明：

- `shell=False`、cwd 和命令分类都不是 OS 沙箱。
- 被批准的 Python/可执行程序仍可能访问当前 Windows 用户有权限访问的资源。
- 文件工具能够强约束自身路径，但一般 subprocess 的宿主机副作用只能 best effort 降低，不能完整证明“工作区外绝无写入”。
- 固定任务的验收只检查文件工具边界、预设哨兵路径、命令 cwd、敏感环境剥离和预期 diff，不声称审计整个宿主机。
- 发给模型的任务、源码片段和命令输出会离开本机并发送到 DeepSeek；不得用于未经授权的敏感代码。
- 恶意仓库内容可能提示注入；system prompt 和最小权限只能缓解，不能根除。

## 9. 上下文、预算和终止

本次运行的 system、user、assistant 和 tool 历史完整保留。上下文规模通过有限模型轮次、有限工具轮次、工具输出限长和 API 返回的 token 总预算控制，不做动态摘要或复杂裁剪。

上下文管理包括：

1. 持久可见历史以一条紧凑 JSON user 消息加入上下文；本次运行完整保存 system、user、assistant 和 tool 消息。
2. 单个文件、搜索结果和命令输出硬限长。
3. 每次模型响应后累计 API 返回的 `usage`；首版不引入本地 tokenizer，也不在请求前伪造精度不明的 token 估算。
4. 达到已观测的累计 token 硬上限时停止；提供方上下文错误按 API 错误处理。
5. 模型调用、工具调用、总时间和单工具均有硬预算。

候选默认值先按演示规模保守设定，并在正式录制前用 D1-D3 live test 复核：

- 最多 16 次模型请求；
- 最多 40 次工具调用；
- 总墙钟 8 分钟；
- 单命令 120 秒；
- 单 API 请求显式超时；
- 累计 token 上限和 `max_tokens` 以真实 usage 为依据设置。

每次等待时间取“该操作上限”和“剩余总预算”的较小值。`core` 通过通用
`ToolExecutor.execute(..., timeout_seconds=remaining)` 传递剩余时间，不识别具体工具名；
工具注册表再把该上限应用到 `run_command`，从而保持依赖倒置。

终止原因：

- `model_final`
- `max_model_calls`
- `max_tool_calls`
- `token_budget_exceeded`
- `wall_time_exceeded`
- `api_fatal_error`
- `content_filtered`
- `truncated_response`
- `protocol_error`
- `user_cancelled`
- `internal_invariant_violation`

## 10. 错误与重试

### API

- SDK `max_retries=0`。
- 400/401/402/403/422：不重试。
- 429/500/503、连接失败、读取超时、`insufficient_system_resource`：最多 3 次指数退避并加入小 jitter。
- 不自动切换到更贵模型。
- 重试不超过剩余墙钟预算。

### 工具

- 非法 JSON、未知工具、字段错误、路径越界、被拒命令、非零退出码均作为结构化 tool result 回填，允许模型自纠。
- 有副作用的工具不由控制器盲目自动重试。
- 当前只检测可证明的“完全重复工具交换”，不声称理解任务是否取得语义进展。检测器仅保存最多
  128 个 SHA-256 指纹，不保留参数或结果正文；从第三次相同交换开始附加 `progress_warning`，提示
  模型改变策略。它不会自动重试、抑制工具或终止运行，最终停止仍由硬轮次、工具、token 和时间预算保证。

## 11. 诊断事件，而非安全审计日志

终端和 JSONL 共用一个简单 `emit()`，P0 只有：

- `run_started`
- `model_completed`
- `tool_started`
- `tool_completed`
- `run_finished`

事件采用字段 allowlist，只保存相对路径、工具名、成功状态、退出码、耗时、截断标志、usage 和终止原因。原始 argv 只保存脱敏摘要；不保存请求头、密钥、`reasoning_content`、完整文件内容或完整命令输出。

该轨迹用于调试和解释，可能被本地进程删除或篡改，也无法证明没有发生其他行为；它不是不可抵赖的审计证据。真正验收由独立测试程序完成。

## 12. P0 测试矩阵

### 12.1 无 API 单测

- 假模型完成“读文件 -> 修改 -> 运行测试 -> final”的状态机。
- tool-call ID 配对、同轮多工具、非法 JSON、未知工具和冲突字段。
- `finish_reason` 全决策表。
- 相对路径、`..`、绝对路径、现有 symlink/junction、Windows 特殊路径、受保护文件。
- 读取编码/限长；create-only 写入；hash 乐观锁；失败不留下半文件。
- 命令成功、非零退出、基本超时、按 bytes 输出限长和敏感环境剥离。
- 最大模型调用、工具调用、token/时间预算和空最终回复。
- reasoning 原样回传但不进入日志。

### 12.2 离线协议 fixture

- 固定 DeepSeek 响应对象验证请求体和 assistant 显式序列化。
- 同轮多个 tool calls 全部得到一个结果。
- 400/401 不重试；429/5xx/资源不足有限重试。
- usage、finish reason、模型 ID 和 fingerprint 解析。

### 12.3 D1 真实 API 纵向 smoke

API key 可用后，当天先完成：

```text
用户任务 -> DeepSeek 请求读取测试文件 -> 本地 read_file ->
tool result 回填（含完整 reasoning history）-> 模型 final
```

该 smoke 连续通过 3 次后才扩展复杂工具，避免 D4 才发现模型 schema 或 reasoning 协议错误。

### 12.4 正式端到端任务

冻结为日期边界回归修复：

> 修复日志统计 CLI 的 `--to YYYY-MM-DD`：包含当日 23:59，排除次日 00:00；补回归测试且不改变其他行为。

每次从干净基线复制到新临时目录。agent 看不到的验收程序检查：

- 原测试与固定隐藏边界测试；
- 修改文件集合、文本格式和无关改动；
- 文件工具越界/受保护路径哨兵。

P0：5 次至少成功 4 次，且录制前连续成功 3 次。<br>
P1：在固定日期、模型别名和配置下观察到 8/10，并分别报告“包含 API 故障”和“排除 API 故障”的结果。小样本不能宣称普遍生产稳定性。

第二个 Markdown JSON 功能任务只作为有余力时的 P1 一次性泛化检查，不阻塞提交。

### 12.5 当前真实闭环证据（2026-08-27）

已使用官方 API 的 `deepseek-v4-flash` 从干净的 `examples/date_boundary_bug`
副本完成一次正式端到端任务：14 次模型调用、27 次本地工具调用、37.9 秒结束。
过程中实际触发并恢复了 `stale_file` 乐观锁冲突、测试非零退出和 `DENY` 命令拒绝；
最终候选测试为 5 项，并由 Agent 工作区外的 verifier 复核以下四项全部通过：候选测试、
新增回归测试、当日末包含且次日零点排除、未过滤行为保持不变。

这是一条已复核的真实成功样本，不等同于上节的稳定性门槛。正式录制前仍需从全新副本
连续成功 3 次；未完成该步骤前不宣称达到 4/5、8/10 或生产稳定性。

## 13. 依赖和环境

Agent 核心的唯一第三方运行依赖是已验证并固定版本的 `openai`。Web extra 固定
`fastapi`、`uvicorn`、`sqlalchemy`、`psycopg` 与 `alembic`；数据库镜像采用 PostgreSQL 17
的 pgvector 发行镜像，但首版不创建向量列、不启用 embedding 或向量检索。前端使用 Vue、
Vue Router 与 Pinia，完整构建/测试依赖由 `frontend/package-lock.json` 固定。

依赖单一真源为 `pyproject.toml`。`environment.yml` 只创建 Python 3.11 + pip 并从当前项目安装 editable 依赖，避免同时维护两套版本号。

开发机使用 Conda 创建独立 `coding-agent` 环境，不升级 base、不修改全局 PATH、不复用旧环境；`environment.yml` 同时安装 CLI、Web 与测试依赖。

API key 不提供命令行参数。Web 服务从进程环境或本机 `backend/.env` 读取；CLI、live smoke
和 demo 脚本只读取当前进程的 `DEEPSEEK_API_KEY`。真实 `.env` 被读取保护和 `.gitignore`
双重排除，只允许提交含占位符的 `.env.example`，前端永远不接收 API key。

## 14. 仓库、AI 使用和提交合规

- GitHub 仓库必须在题目发布后由用户账号新建，公开、非 fork、非旧模板历史。
- 从设计、环境、工具、循环、协议、测试到文档保留真实递进提交。
- 已推送提交不 amend/rebase/squash/force-push。
- 截止后不再推送；关闭会自动提交的机器人。
- 最终用未登录窗口验证仓库可访问。
- `tmp/`、真实配置、轨迹、视频、ZIP、缓存和虚拟环境均不入库。
- 提交前扫描当前树和完整 Git 历史中的 key；误泄漏时先作废 key，再处理仓库。

开发阶段允许使用 AI。项目将如实声明：

> 开发过程中使用 Codex/ChatGPT 辅助需求分析、代码生成、测试和审查；作者决定需求与架构，逐项验证并理解全部提交，对所有设计和实现负责。运行时核心循环、本地工具执行、上下文管理和错误策略均由本项目实现，未使用现成 agent 产品、agent 框架或服务端托管代码/文件工具。

可在 `AI_USAGE.md` 记录 AI 参与范围和人工验证方式；不能把深度 AI 参与描述成“仅少量建议”。

## 15. 提交物检查

1. 公开 GitHub 仓库 URL 写入提交用 `README.txt`。
2. `README.txt` 不超过 1000 汉字，至少包含仓库地址、运行方法和特色功能；仓库的 `README.md` 不能替代它。
3. 视频为 MP4、小于 2 分钟、小于 200 MB，既展示真实编程任务闭环，也简要解释实现。
4. 最终 ZIP 以真实姓名命名，压缩包根层只有 `README.txt` 和视频，不套多余目录。
5. 在未登录环境检查公开仓库；密钥扫描覆盖 Git 全历史、`README.txt`、视频和最终 ZIP。
6. 检查视频时长、编码、体积和无密钥画面。
7. 提交到 `https://table.nju.edu.cn/dtable/forms/283d6c7d-475a-4f41-8baf-d3f45966ef2d/`；可重复提交，以最后一次为准。
8. 截止时间为北京时间 2026-09-03 00:00；此后不再向仓库推送任何提交。

## 16. 实施顺序与优先级

### D1

- 确认新 Conda 环境、API key/余额；GitHub 由用户在项目完成后自行处理。
- 实现最小 DeepSeek adapter、单工具 loop 和假模型测试。
- 当天跑通真实“读取文件 -> 回填 -> final”三次。

### D2

- 完成五个 P0 工具、路径边界、命令策略和核心单测。

### D3

- 完成完整状态机、finish reason、预算、错误策略、reasoning 协议和五事件轨迹。
- 当天首次完整跑通正式日期任务。

### D4

- 只修正式任务暴露的问题，运行 5 次并达到 4/5。
- 达标后才允许增加 `search_text` 或第二任务。

### D5

- 上午最终回归和录制；中午后冻结核心逻辑。
- 下午完成 README、AI 声明、面试提纲和视频剪辑。

### D6

- 只做故障修复、密钥/公开访问/视频/ZIP 检查和必要重录，不扩功能。

### P1（仅在 P0 提前稳定后）

- 已实现 `search_text`；
- 已实现完全重复工具交换的建议性检测；
- 更丰富 token/成本统计；
- Windows 子进程树和 junction 的更多测试；
- 第二个真实任务；
- 8/10 固定任务观察结果。

### 仍明确不做的 P2

- 多智能体、规划器/执行器分层；
- 面向公网、多用户或带账户体系的 Web 服务，以及复杂 TUI；
- RAG、向量检索、模型自动写入记忆、MCP、插件和浏览器；
- Responses API 托管工具、Files API、Code Interpreter；
- 模型生成的动态摘要，以及后端重启后继续执行中断的 run；持久会话和事件可以查看，但不恢复进程；
- streaming tool-call 拼装；
- 多模型自动路由和自动切换；
- 自动 Git commit/push；
- 完整 shell 兼容层；
- Docker/VM 级安全沙箱；
- 未实测的跨平台安全承诺。

## 17. 已确认事项与后续输入

1. 项目名 `Coding Agent`、发行包/仓库根目录名、Conda 环境名均为 `coding-agent`。
2. GitHub 远端仓库与最终上传由用户处理；开发阶段只维护本地提交，Agent 和 Web 运行流程不执行 Git 远端操作。
3. DeepSeek 账号已有可用 API key 和余额；key 不通过聊天发送，真实联调时只从本机环境变量读取。
4. 最终 ZIP 使用的真实姓名在提交阶段再提供。
