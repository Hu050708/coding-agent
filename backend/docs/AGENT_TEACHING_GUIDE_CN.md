# Coding Agent 核心原理与源码教学

> 面向第一次系统学习智能体的同学。本教程以当前项目源码为准，重点解释 Agent 为什么能够连续工作、每一步保存了什么数据、工具为什么能安全执行，以及如何在面试中讲清楚自己的设计。
>
> 建议先完整读一遍第 1～6 章，再打开源码跟着第 7 章的案例逐步调试。后端接口、数据库和前端只讲它们如何接入 Agent，不展开通用的 FastAPI、Vue 语法。

---

## 0. 先记住一句话

这个项目不是“调用一次大模型并显示答案”，而是一个由我们自己编写的循环：

1. 把任务、历史消息和可用工具发给模型；
2. 模型决定是回答，还是调用一个或多个工具；
3. 本地程序检查并执行工具；
4. 把真实执行结果加入消息历史，再发给模型；
5. 重复以上过程，直到模型给出最终回答，或预算、超时、取消、协议错误等条件触发终止。

最核心的源码是：

- [`Agent.run`](../src/coding_agent/agents/agent.py#L190)：整个智能体循环；
- [`DeepSeekAdapter`](../src/coding_agent/agents/providers/deepseek.py#L247)：调用 DeepSeek 并整理返回值；
- [`ToolRegistry`](../src/coding_agent/agents/tools/registry.py#L47)：管理和执行本地工具；
- [`AgentConfig`](../src/coding_agent/agents/config.py#L11)：模型次数、工具次数、Token 和时间预算；
- [`AgentContextBuilder`](../src/coding_agent/agents/context.py#L135)：整理历史会话和记忆；
- [`RunResult`](../src/coding_agent/agents/contracts.py#L284)：一次运行的最终结果。

可以先把它理解成下面这台“有反馈的机器”：

```text
用户任务
   │
   ▼
Agent.run 组装消息和工具说明
   │
   ▼
DeepSeek：下一步应该做什么？
   │
   ├── 返回最终文本 ───────────────► 结束
   │
   └── 返回 tool_calls
            │
            ▼
       本地工具真实执行
            │
            ▼
       工具结果写回消息历史
            │
            └──────────────────────► 再问 DeepSeek
```

这里最容易犯的错误，是把“模型生成了计划”误认为“Agent 已经做完了事情”。在本项目中，文件是否被修改、测试是否运行、命令是否成功，都必须来自本地工具的真实结果。

---

## 1. 学完后应该能回答什么

学完本教程后，至少应该能够不看稿回答下面的问题：

1. 普通聊天机器人和 Coding Agent 有什么区别？
2. 为什么需要一个循环，不能只调用模型一次？
3. 模型如何知道有哪些工具、每个工具需要什么参数？
4. 模型返回的 `tool_calls` 是怎样在本机执行的？
5. 为什么工具执行结果还要再次发给模型？
6. 消息历史里依次存了哪些角色和数据？
7. `finish_reason="stop"` 和 `finish_reason="tool_calls"` 分别表示什么？
8. 为什么 `read_file` 返回哈希，`replace_text` 又要求传回这个哈希？
9. 三档权限有什么区别？它们为什么不等于操作系统沙箱？
10. 模型 API 失败、工具失败、测试失败和整个 Agent 失败有什么区别？
11. 如何防止 Agent 无限循环或无限花费 Token？
12. 为什么模型说“已经修复”不代表评测一定通过？
13. 当前 9/9 评测证明了什么，又不能证明什么？
14. 为什么项目符合“不能使用现成 Agent 框架”的题目要求？

如果这些问题能讲清楚，面试官继续追问到具体代码时，就可以顺着本教程中的代码位置展开。

---

## 2. 题目到底要求我们自己完成什么

原题的核心不是做一个漂亮的聊天页面，而是独立实现一个可以完成编程任务的 Agent。题目允许使用模型厂商的基础 API 客户端和原生 Tool Calling，但不允许使用 Agent 框架代替核心逻辑。

### 2.1 题目要求与当前代码的对应关系

| 题目要求 | 本项目如何实现 | 主要代码位置 |
| --- | --- | --- |
| 与大模型交互 | 使用 DeepSeek 官方兼容接口，发送消息与工具说明 | [`providers/deepseek.py`](../src/coding_agent/agents/providers/deepseek.py) |
| 自主读取文件 | `list_files`、`read_file`、`search_text` | [`tools/filesystem.py`](../src/coding_agent/agents/tools/filesystem.py)、[`tools/search.py`](../src/coding_agent/agents/tools/search.py) |
| 自主修改文件 | `make_directory`、`write_file`、`replace_text`、`delete_file` | [`tools/filesystem.py`](../src/coding_agent/agents/tools/filesystem.py) |
| 自主执行命令 | `run_command`，使用参数数组并关闭 shell | [`tools/command.py`](../src/coding_agent/agents/tools/command.py#L127) |
| 自己维护历史与上下文 | 维护 system、user、assistant、tool 消息；裁剪历史；冻结记忆快照 | [`agent.py`](../src/coding_agent/agents/agent.py)、[`context.py`](../src/coding_agent/agents/context.py) |
| 自己解析模型输出 | 把厂商响应整理成 `ModelCompletion`、`AssistantMessage`、`ToolCall` | [`providers/deepseek.py`](../src/coding_agent/agents/providers/deepseek.py#L202) |
| 自己执行工具并回填结果 | `ToolRegistry.execute` 返回统一 JSON，再由主循环加入历史 | [`tools/registry.py`](../src/coding_agent/agents/tools/registry.py#L148)、[`agent.py`](../src/coding_agent/agents/agent.py#L490) |
| 自己控制循环终止 | 检查完成原因、次数、Token、时间、取消和协议错误 | [`agent.py`](../src/coding_agent/agents/agent.py#L300) |
| 自己处理错误 | API 重试、工具结构化失败、命令非零退出、终止原因 | [`agent.py`](../src/coding_agent/agents/agent.py)、[`contracts.py`](../src/coding_agent/agents/contracts.py#L20) |
| 密钥不能写进代码 | 从 `DEEPSEEK_API_KEY` 环境变量读取 | [`cli.py`](../src/coding_agent/cli.py#L203)、[`settings/settings.py`](../src/coding_agent/settings/settings.py) |

### 2.2 为什么基础 API 客户端不算 Agent 框架

项目依赖中的 `openai` 包只负责 HTTP 请求、鉴权、超时和响应对象转换。它没有替我们决定：

- 下一轮要发哪些历史消息；
- 什么时候执行工具；
- 本地工具如何读写文件；
- 命令是否需要审批；
- 如何判断循环结束；
- 如何统计预算；
- 工具失败后是否继续；
- 如何生成安全追踪记录。

这些都由项目自己的源码完成。因此面试时可以这样回答：

> 我使用厂商基础客户端作为网络传输层，但 Agent 的状态、主循环、工具实现、权限判断、结果回填、预算和终止逻辑都由项目自行实现，没有把任务交给 LangChain、AutoGen、Agents SDK 等框架执行。

代码证据：[`DeepSeekAdapter.complete`](../src/coding_agent/agents/providers/deepseek.py#L320) 只发出一次模型请求；真正反复调用它的是 [`Agent.run`](../src/coding_agent/agents/agent.py#L190)。

---

## 3. 初学者必须掌握的基础概念

### 3.1 大语言模型不是执行器

大语言模型输入一组文本和结构化说明，输出下一段文本或工具调用意图。它本身不能直接修改本机文件。

例如模型返回：

```json
{
  "name": "write_file",
  "arguments": {
    "path": "hello.py",
    "content": "print('Hello, world!')\n"
  }
}
```

这只是“希望调用 `write_file`”的数据。真正写文件的是本地 Python 函数。

代码位置：

- 模型返回值中的工具调用数据：[`ToolCall`](../src/coding_agent/agents/contracts.py#L67)；
- 找到并调用本地处理函数：[`ToolRegistry.execute`](../src/coding_agent/agents/tools/registry.py#L148)；
- 实际创建文件：[`write_file`](../src/coding_agent/agents/tools/filesystem.py#L212)。

### 3.2 消息角色

发给模型的历史通常包含四种角色：

| 角色 | 谁产生 | 作用 |
| --- | --- | --- |
| `system` | Agent 程序 | 规定身份、工作方式和安全原则 |
| `user` | 用户或上下文整理器 | 当前任务，也可以包含被标记为数据的旧会话和记忆 |
| `assistant` | 模型 | 最终文本，或带 `tool_calls` 的工具请求 |
| `tool` | 本地程序 | 某个工具调用的真实执行结果，必须对应具体 `tool_call_id` |

代码位置：

- 系统提示词：[`DEFAULT_SYSTEM_PROMPT`](../src/coding_agent/agents/agent.py#L35)；
- 工具调用形式的 assistant 消息：[`AssistantMessage.as_history_dict`](../src/coding_agent/agents/contracts.py#L90)；
- 主循环加入 assistant 和 tool 消息：[`Agent.run`](../src/coding_agent/agents/agent.py#L465)。

### 3.3 Token

Token 是模型处理文本时使用的计量单位，不完全等于汉字数或单词数。一次请求通常有：

- `prompt_tokens`：输入消息、工具说明占用的 Token；
- `completion_tokens`：模型输出占用的 Token；
- `total_tokens`：两者之和。

本项目把每次模型请求的用量累计到 [`TokenUsage`](../src/coding_agent/agents/contracts.py#L119)，并用 `max_total_tokens` 限制整次任务。

### 3.4 Tool Calling

Tool Calling 的含义不是模型执行函数，而是模型按照预先声明的 JSON 结构返回“函数名 + 参数”。本地程序需要完成四步：

1. 把工具名称、用途、参数结构发给模型；
2. 解析模型返回的工具调用；
3. 检查参数并执行本地函数；
4. 把执行结果作为 `tool` 消息回填。

本项目对应代码：

- 工具说明：[`tools/schemas.py`](../src/coding_agent/agents/tools/schemas.py)；
- 参数解析：[`strict_json_object`](../src/coding_agent/agents/tool_protocol.py#L32)；
- 执行：[`ToolRegistry.execute`](../src/coding_agent/agents/tools/registry.py#L148)；
- 回填：[`Agent.run`](../src/coding_agent/agents/agent.py#L490)。

### 3.5 状态

“状态”就是程序在某一时刻必须记住的数据。一次 Agent 运行中最重要的状态包括：

```text
messages           当前完整消息历史
model_calls        已请求模型多少次
tool_calls         已执行工具多少次
usage              已消耗多少 Token
seen_tool_call_ids 已见过的工具调用 ID
repeat_detector    完全相同工具交换出现了几次
change_check       修改后是否做过成功检查
started_at         运行开始时间
```

这些状态主要在 [`Agent.run`](../src/coding_agent/agents/agent.py#L190) 的局部变量中维护。一轮模型请求结束后不会丢失，而是用于决定下一轮还能否继续。

### 3.6 循环为什么必要

模型第一次看到任务时通常不知道工作区里有什么。它需要：

```text
先列文件 → 再读相关文件 → 决定修改 → 写入修改 → 运行测试 → 根据测试结果继续修复或结束
```

每一步的新事实只有工具执行后才知道，所以必须把结果回填并再次调用模型。没有循环，就只能完成“猜测式的一次回答”，无法依据真实工作区逐步工作。

---

## 4. Agent 相关目录怎么读

建议先忽略前端页面，从下面这棵目录开始：

```text
backend/src/coding_agent/
├─ agents/
│  ├─ agent.py                 # 核心循环，最重要
│  ├─ config.py                # 次数、Token、时间等预算
│  ├─ context.py               # 历史会话和记忆如何进入模型上下文
│  ├─ contracts.py             # 运行中使用的数据结构和接口
│  ├─ change_check.py          # 修改代码后是否执行过成功检查
│  ├─ progress.py              # 识别完全重复的工具交换
│  ├─ tool_protocol.py         # 工具参数和工具结果的统一 JSON 格式
│  ├─ providers/
│  │  └─ deepseek.py           # DeepSeek 请求与响应整理
│  ├─ tools/
│  │  ├─ schemas.py            # 8 个工具的参数说明
│  │  ├─ registry.py           # 工具注册、审批、执行和错误转换
│  │  ├─ filesystem.py         # 文件列表、读取、创建、替换、删除
│  │  ├─ search.py             # 文本搜索
│  │  ├─ command.py            # 命令执行
│  │  └─ contracts.py          # 工具参数检查辅助函数
│  ├─ security/
│  │  ├─ workspace.py          # 工作区边界、路径和原子文件操作
│  │  ├─ permission_policy.py  # ask / agent / workspace_full
│  │  ├─ command_policy.py     # 命令允许、确认、禁止规则
│  │  ├─ workspace_policy.py   # Web 可选择哪些工作区
│  │  └─ approval.py           # 审批请求的数据结构
│  ├─ runtime/
│  │  ├─ agent_runner.py       # 为一次 Web 运行组装 Agent
│  │  ├─ run_manager.py        # 后台运行、状态、取消、并发
│  │  ├─ approval_broker.py    # Agent 线程与网页人工确认之间的桥梁
│  │  └─ event_buffer.py       # 保存前端可读取的实时事件
│  └─ diagnostics/
│     └─ trace.py              # 安全 JSONL 诊断记录
├─ services/
│  ├─ run_service.py           # 数据库会话与 Agent 运行的连接层
│  └─ memory_service.py        # 由用户确认的工作区记忆
└─ cli.py                      # CLI 入口与依赖组装
```

### 4.1 推荐阅读顺序

不要一上来逐文件从头读到尾，按下面顺序更容易形成整体认识：

1. [`tests/integration/test_offline_loop.py`](../tests/integration/test_offline_loop.py)：先看一个完整但很短的 Agent 工作示例；
2. [`agents/agent.py`](../src/coding_agent/agents/agent.py)：理解循环；
3. [`agents/contracts.py`](../src/coding_agent/agents/contracts.py)：理解循环里的数据；
4. [`agents/tools/schemas.py`](../src/coding_agent/agents/tools/schemas.py)：看模型知道哪些工具；
5. [`agents/tools/registry.py`](../src/coding_agent/agents/tools/registry.py)：看工具如何被执行；
6. [`agents/tools/filesystem.py`](../src/coding_agent/agents/tools/filesystem.py) 和 [`command.py`](../src/coding_agent/agents/tools/command.py)：看真实操作；
7. [`agents/providers/deepseek.py`](../src/coding_agent/agents/providers/deepseek.py)：看厂商响应如何进入核心循环；
8. [`agents/security/`](../src/coding_agent/agents/security/)：理解安全边界；
9. [`agents/runtime/`](../src/coding_agent/agents/runtime/)：理解 Web 如何运行同一个核心；
10. [`evaluation/`](../evaluation/)：理解怎么证明 Agent 真能完成任务。

### 4.2 当前 Web 长期数据从哪里来

当前 Web 版本的会话、运行、事件、审批和记忆由 PostgreSQL 持久化，并通过 Alembic 管理数据库版本。主要连接代码是：

- [`services/run_service.py`](../src/coding_agent/services/run_service.py)；
- [`services/memory_service.py`](../src/coding_agent/services/memory_service.py)；
- [`main.py`](../src/coding_agent/main.py)；
- [`database/migrations.py`](../src/coding_agent/database/migrations.py) 和 [`backend/alembic/`](../alembic/)。

`agents/memory/` 现在只定义运行时使用的记忆加载状态摘要，不再包含本地 SQLite 仓储。
记忆正文由 PostgreSQL 中的 `memory_entries` 保存，创建运行时再冻结到 `run_memories`；
`AgentRunner` 只接收这份不可变快照，不会按工作区再次查询其他存储。

---

## 5. 三层结构：模型、Agent、工具

可以把项目最核心的部分分成三层。

### 5.1 模型层：给出下一步决定

DeepSeek 接收消息和工具说明，返回两类结果之一：

- 最终文本：认为任务可以结束；
- 工具调用：需要读取、修改或运行命令以获取新事实。

代码位置：[`DeepSeekAdapter.complete`](../src/coding_agent/agents/providers/deepseek.py#L320)。

### 5.2 Agent 层：控制流程

Agent 不负责具体读文件，也不负责 HTTP 底层细节。它负责：

- 维护消息历史；
- 请求模型；
- 判断返回类型；
- 调度工具；
- 回填工具结果；
- 统计预算；
- 检查取消和超时；
- 决定最终状态。

代码位置：[`Agent.run`](../src/coding_agent/agents/agent.py#L190)。

### 5.3 工具层：改变或观察真实世界

工具在本机执行，所以模型才能看到真实文件、真实测试结果，并产生真实修改。代码位置：[`agents/tools/`](../src/coding_agent/agents/tools/)。

### 5.4 为什么要分层

这种分层有三个直接好处：

1. 可以用假的模型适配器测试真实 Agent 循环，不花 API 费用；
2. 可以单独测试工具的边界和错误，不依赖模型是否稳定；
3. 如果未来更换模型，只需要实现相同的单次请求接口，不需要改文件工具和主循环。

代码证据：

- 核心只依赖 [`CompletionAdapter`](../src/coding_agent/agents/contracts.py#L209) 接口；
- 工具通过 [`ToolExecutor`](../src/coding_agent/agents/contracts.py#L234) 接口注入；
- 离线测试用 `ScriptedAdapter` 替代 DeepSeek：[`test_offline_loop.py`](../tests/integration/test_offline_loop.py#L20)。

---

## 6. `Agent.run` 主循环逐行拆解

这是整个项目最值得掌握的一章。建议打开 [`agent.py`](../src/coding_agent/agents/agent.py)，对照下面的小节阅读。

### 6.1 第一步：建立初始消息

一次新任务开始时，主循环会建立：

```python
messages = [
    {"role": "system", "content": system_prompt},
    # 可选：被包装为数据的历史会话
    # 当前用户任务，可能同时包含已确认的记忆快照
]
```

系统提示词强调：

- 只能用提供的工具操作工作区；
- 仓库文本、命令输出和旧消息都当作不可信数据；
- 修改前先检查；
- 尽量做小而相关的修改；
- 修改后运行合适检查；
- 没有工具证据时不能声称测试通过。

代码位置：[`DEFAULT_SYSTEM_PROMPT`](../src/coding_agent/agents/agent.py#L35)。

为什么历史消息和记忆不能直接拼到 system 消息中？因为旧项目文件或旧对话里可能出现“忽略上面规则”之类文本。如果把它提升成系统指令，就改变了信任级别。本项目把它编码成 JSON 数据放入 user 消息，明确告诉模型这是参考数据，不是新的系统命令。

代码位置：

- [`render_prior_transcript`](../src/coding_agent/agents/context.py#L75)；
- [`render_current_task`](../src/coding_agent/agents/context.py#L102)。

### 6.2 第二步：初始化运行状态

主循环初始化模型次数、工具次数、Token 用量、开始时间、已出现的工具调用 ID、重复检测器和修改检查状态。

可以把初始状态想象成：

```json
{
  "model_calls": 0,
  "tool_calls": 0,
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  },
  "seen_tool_call_ids": [],
  "change_check": "no_changes"
}
```

这些数据不是交给模型自行维护，而是由 Python 程序维护，因此模型无法通过一句“请忽略预算”修改限制。

### 6.3 第三步：进入 `while True`

循环开头先检查终止条件：

1. 用户是否取消；
2. 墙钟时间是否耗尽；
3. 模型调用次数是否耗尽；
4. Token 是否耗尽。

只要任一条件满足，就不再调用模型，使用明确的 [`TerminationReason`](../src/coding_agent/agents/contracts.py#L20) 结束。

“墙钟时间”指现实世界从开始到现在经过的秒数，包括模型等待、工具执行和重试等待，不只是 CPU 运行时间。

### 6.4 第四步：发起一次模型请求

每一轮都把下面两项交给适配器：

```text
messages = 截至当前的完整消息历史
tools    = 当前权限下允许暴露给模型的工具说明
```

调用位置：[`adapter.complete`](../src/coding_agent/agents/agent.py#L330)。

工具说明每一轮都传，是因为 API 请求本身是无状态的。服务器不会替本地程序永久记住上一轮消息和工具；我们必须把当前所需状态重新发送。

### 6.5 第五步：处理模型 API 错误

错误分两类：

| 类型 | 示例 | 当前处理 |
| --- | --- | --- |
| 短暂错误 | 网络断开、超时、429、500、503 | 在限定次数内退避后重试 |
| 致命错误 | 参数错误、鉴权错误、无法识别的响应 | 结束本次运行 |

DeepSeek 适配器判断错误是否可重试，Agent 核心拥有重试次数和退避节奏。这样网络层负责识别错误，流程层负责决定还能重试几次。

代码位置：

- 错误分类：[`DeepSeekAdapter.complete`](../src/coding_agent/agents/providers/deepseek.py#L320) 捕获异常并写入 `AdapterRequestError.retryable`；
- 重试循环：[`Agent.run`](../src/coding_agent/agents/agent.py#L330)；
- 退避计算：[`Agent._backoff`](../src/coding_agent/agents/agent.py#L630)。

DeepSeek 的 `insufficient_system_resource` 表示服务端暂时资源不足。该响应不会进入历史，因为它不是模型对任务的有效回答，程序会在预算内重新请求。

### 6.6 第六步：累计 Token 用量

收到有效模型响应后，主循环累计本轮 `prompt_tokens`、`completion_tokens` 和 `total_tokens`。下一轮开始前会再次检查总预算。

为什么不只限制模型调用次数？因为一次请求可能很短，也可能包含很长的代码和历史。次数相同，成本与上下文体积可能差很多，所以次数和 Token 都要限制。

### 6.7 第七步：根据 `finish_reason` 分支

当前核心关注以下情况：

| `finish_reason` | 含义 | Agent 行为 |
| --- | --- | --- |
| `stop` | 模型要给最终回答 | 确认没有工具调用且文本非空，然后结束 |
| `tool_calls` | 模型请求工具 | 校验调用，执行工具，回填后继续 |
| `length` | 输出达到长度上限 | 以 `truncated_response` 结束，不能把半截数据当有效调用 |
| `content_filter` | 内容被服务过滤 | 以 `content_filtered` 结束 |
| 其他未知值 | 与核心约定不一致 | 以 `protocol_error` 结束 |

关键原则：返回值内部必须自洽。

- `stop` 不能同时带工具调用；
- `stop` 必须有最终文本；
- `tool_calls` 必须至少有一个工具调用；
- 工具调用 ID 在整个运行中不能重复；
- 一整批工具调用不能超过剩余工具预算。

这些检查不是为了“猜模型想表达什么”，而是避免把不完整或冲突的响应错误执行。

### 6.8 第八步：先保存 assistant 工具请求

如果模型返回工具调用，程序先把完整的 assistant 消息加入 `messages`，包括：

- `role: assistant`；
- 可选的 `content`；
- `reasoning_content`；
- 一个或多个 `tool_calls`。

然后才逐个执行工具并加入对应的 `tool` 消息。

顺序必须是：

```text
assistant(tool_calls=[call_1, call_2])
tool(tool_call_id=call_1, ...)
tool(tool_call_id=call_2, ...)
```

如果遗漏 assistant 工具请求、回填顺序错误，或 `tool_call_id` 对不上，下一次模型请求的消息协议就会损坏。

### 6.9 第九步：严格解析工具参数

模型返回的 `arguments` 是 JSON 字符串。本项目要求：

- 顶层必须是 JSON 对象；
- 不能有重复键；
- 不能有 `NaN`、`Infinity` 等非标准值；
- 后续还要按具体工具检查参数名与参数类型。

代码位置：[`strict_json_object`](../src/coding_agent/agents/tool_protocol.py#L32)。

解析失败不会执行工具，而是生成一个结构化失败结果回填给模型。模型可以看到错误并改正下一次调用。

### 6.10 第十步：逐个执行工具

一个模型响应可以包含多个工具调用。当前实现按顺序执行，而不是并行执行，因为编程操作通常有依赖：

```text
创建目录 → 在目录中创建文件 → 运行引用该文件的测试
```

如果并行执行，后一步可能在前一步完成前开始，结果不稳定。

每个调用都会：

1. 检查取消和剩余时间；
2. 解析参数；
3. 交给 `ToolRegistry`；
4. 执行权限判断和必要审批；
5. 调用真实工具函数；
6. 把结果统一成 JSON；
7. 增加工具调用计数；
8. 加入对应的 `tool` 历史消息。

### 6.11 为什么失败的工具结果也要回填

工具失败不一定意味着整个任务失败。例如测试返回非零退出码，恰好是 Agent 发现 Bug 的证据。模型需要看到失败详情才能继续修复。

因此工具结果统一类似：

```json
{
  "ok": false,
  "error": {
    "code": "command_exit_nonzero",
    "message": "Command exited with a non-zero status."
  },
  "data": {
    "exit_code": 1,
    "stdout": "...",
    "stderr": "..."
  },
  "meta": {
    "duration_ms": 1350
  }
}
```

这条消息进入历史后，模型下一轮可以决定再次读文件、修复代码或换一种测试命令。

代码位置：

- 统一错误：[`tool_error`](../src/coding_agent/agents/tool_protocol.py)；
- 统一正常与失败结果：[`normalize_tool_result`](../src/coding_agent/agents/tool_protocol.py#L156)；
- 命令失败数据：[`run_command`](../src/coding_agent/agents/tools/command.py#L127)。

### 6.12 一批工具执行到一半取消怎么办

即使在一批工具中途收到取消，协议上已经存在的每个 `tool_call_id` 仍需要一个对应结果。当前实现会为未执行的剩余调用生成取消结果，而不是直接丢下半个 assistant 工具回合。

这是一个很好的面试点：取消不仅要停止副作用，还要维持消息历史结构完整。

### 6.13 第十一步：检测重复但不武断终止

程序会对“工具名 + 规范化参数 + 去除易变字段后的结果”计算指纹。如果完全相同的工具交换从第三次起再次出现，会在结果 `meta` 中加入调整策略的提示。

代码位置：

- 指纹和次数：[`RepeatedToolExchangeDetector`](../src/coding_agent/agents/progress.py#L33)；
- 添加提示：[`add_progress_warning`](../src/coding_agent/agents/tool_protocol.py#L185)。

当前策略只是提示，不直接终止。原因是相同读取有时有合理用途，简单按次数杀死任务容易误伤。真正的硬停止仍由工具次数、模型次数、Token 和墙钟时间负责。

### 6.14 第十二步：记录修改后的检查状态

[`ChangeCheck`](../src/coding_agent/agents/change_check.py#L50) 观察成功的文件修改和检查类命令，给出：

| 状态 | 含义 |
| --- | --- |
| `no_changes` | 没有成功修改文件 |
| `needs_check` | 有修改，但还没有运行检查 |
| `outdated` | 检查后又发生修改，旧检查不能覆盖新代码 |
| `passed` | 最近修改之后有成功检查 |
| `failed` | 最近检查失败 |

它用于给运行结果增加客观信号，但它不是工作区外的独立评测器。Agent 运行一个很弱的命令并成功，不代表功能必然正确；正式评测还需要外部 verifier。

### 6.15 第十三步：下一轮或结束

工具结果全部写入历史后，循环回到开头：

- 先检查取消、时间和预算；
- 再把更新后的完整历史发给模型；
- 模型基于新事实决定下一步。

只有模型返回自洽的 `stop + 最终文本`，才得到 `MODEL_FINISHED / model_final`。这表示模型停止调用工具，不表示外部评测已经通过。

---

## 7. 完整案例：生成一个简单 Python 程序

下面用固定示例展示一次任务内部到底发生什么。用户输入：

> 请帮我生成一个简单的 Python 程序，文件名为 `hello.py`，运行后输出 `Hello, Coding Agent!`，并检查它可以正常运行。

实际模型每次生成的措辞和调用顺序可能不同，但数据流遵循同一规则。

### 7.1 运行开始时保存的状态

```json
{
  "task": "请帮我生成一个简单的 Python 程序……",
  "messages": [
    {
      "role": "system",
      "content": "You are a local coding agent ..."
    },
    {
      "role": "user",
      "content": "请帮我生成一个简单的 Python 程序……"
    }
  ],
  "model_calls": 0,
  "tool_calls": 0,
  "total_tokens": 0,
  "seen_tool_call_ids": [],
  "change_check": "no_changes"
}
```

代码实现：[`Agent.run`](../src/coding_agent/agents/agent.py#L190)。

### 7.2 第一轮：模型先检查工作区

Agent 把初始消息和 8 个工具说明发给 DeepSeek。模型可能返回：

```json
{
  "finish_reason": "tool_calls",
  "assistant": {
    "role": "assistant",
    "content": "",
    "tool_calls": [
      {
        "id": "call_001",
        "type": "function",
        "function": {
          "name": "list_files",
          "arguments": "{\"path\":\".\",\"max_depth\":2}"
        }
      }
    ]
  }
}
```

此时模型没有列目录，它只是提出调用。主循环解析参数，`ToolRegistry` 找到 `list_files`，本地执行后得到：

```json
{
  "ok": true,
  "data": {
    "path": ".",
    "entries": [
      {"path": "README.md", "type": "file"}
    ]
  },
  "meta": {
    "truncated": false
  }
}
```

消息历史变为：

```text
0 system    系统规则
1 user      当前任务
2 assistant tool_calls=[call_001: list_files]
3 tool      tool_call_id=call_001，目录的真实结果
```

计数变化：

```text
model_calls: 0 → 1
tool_calls:  0 → 1
```

代码实现：

- 工具说明：[`LIST_FILES_SCHEMA`](../src/coding_agent/agents/tools/schemas.py)；
- 目录读取：[`list_files`](../src/coding_agent/agents/tools/filesystem.py#L27)；
- assistant 与 tool 消息入历史：[`Agent.run`](../src/coding_agent/agents/agent.py#L465)。

### 7.3 第二轮：模型请求创建文件

第二次请求会重新发送上面的 4 条历史消息。模型现在知道 `hello.py` 不存在，可能返回：

```json
{
  "finish_reason": "tool_calls",
  "assistant": {
    "tool_calls": [
      {
        "id": "call_002",
        "type": "function",
        "function": {
          "name": "write_file",
          "arguments": "{\"path\":\"hello.py\",\"content\":\"print('Hello, Coding Agent!')\\n\"}"
        }
      }
    ]
  }
}
```

本地执行前会经过：

```text
JSON 参数检查
  → 工具是否存在
  → 当前权限是否允许暴露和调用
  → 是否需要用户审批
  → 路径是否位于工作区
  → 是否命中受保护文件
  → 文件是否已经存在
  → 原子创建文件
```

如果当前是 `ask` 权限，`write_file` 需要人工批准；如果是 `agent` 或 `workspace_full`，普通工作区创建可以自动通过。无论哪种模式，都不能越过工作区，也不能写入 `.env`、`.git` 或私钥等受保护目标。

成功结果类似：

```json
{
  "ok": true,
  "data": {
    "path": "hello.py",
    "bytes_written": 30,
    "sha256": "……"
  },
  "meta": {}
}
```

状态变化：

```text
messages:      新增 assistant(call_002) 和 tool(call_002)
model_calls:   1 → 2
tool_calls:    1 → 2
change_check:  no_changes → needs_check
```

代码实现：

- 创建工具：[`write_file`](../src/coding_agent/agents/tools/filesystem.py#L212)；
- 原子创建：[`Workspace.atomic_create`](../src/coding_agent/agents/security/workspace.py#L457)；
- 修改状态：[`ChangeCheck.observe`](../src/coding_agent/agents/change_check.py)。

### 7.4 第三轮：模型运行程序验证

模型看到文件创建成功后，请求：

```json
{
  "finish_reason": "tool_calls",
  "assistant": {
    "tool_calls": [
      {
        "id": "call_003",
        "type": "function",
        "function": {
          "name": "run_command",
          "arguments": "{\"argv\":[\"python\",\"hello.py\"],\"cwd\":\".\",\"timeout_seconds\":30}"
        }
      }
    ]
  }
}
```

注意：任意 Python 程序可能执行任意代码，所以命令策略会要求确认，而不是把它当成固定的安全测试命令自动执行。经用户批准后，工具才启动进程。

成功结果可能是：

```json
{
  "ok": true,
  "data": {
    "argv": ["python", "hello.py"],
    "cwd": ".",
    "exit_code": 0,
    "stdout": "Hello, Coding Agent!\n",
    "stderr": "",
    "duration_ms": 42
  },
  "meta": {
    "stdout_truncated": false,
    "stderr_truncated": false
  }
}
```

如果命令输出不对或退出码非零，结果会以 `ok: false` 回填，模型还可以继续修改。只有真实退出码为 0，并且输出符合任务要求，模型才有证据进行总结。

状态变化：

```text
model_calls:   2 → 3
tool_calls:    2 → 3
change_check:  needs_check → passed
```

代码实现：

- 命令策略：[`classify_command`](../src/coding_agent/agents/security/command_policy.py#L227)；
- 命令执行：[`run_command`](../src/coding_agent/agents/tools/command.py#L127)；
- 环境清理：[`Workspace.sanitized_environment`](../src/coding_agent/agents/security/workspace.py#L628)。

### 7.5 第四轮：模型给出最终文本

第四次模型请求包含前面所有消息和真实输出。模型可能返回：

```json
{
  "finish_reason": "stop",
  "assistant": {
    "role": "assistant",
    "content": "已创建 hello.py，并运行验证成功。程序输出：Hello, Coding Agent!"
  }
}
```

主循环确认：

- `finish_reason` 是 `stop`；
- 没有夹带工具调用；
- 最终内容非空。

然后生成 `RunResult`：

```json
{
  "status": "model_finished",
  "reason": "model_final",
  "model_calls": 4,
  "tool_calls": 3,
  "change_check": "passed",
  "verified": "unknown",
  "final_content": "已创建 hello.py……"
}
```

为什么 `verified` 仍然是 `unknown`？因为核心 Agent 只知道自己运行了某个命令，不知道工作区外的正式验收标准。正式 benchmark 的 verifier 才能给出独立验收结论。

### 7.6 这个案例里每一轮模型看到了什么

| 模型轮次 | 请求前已有事实 | 模型决定 | 新增事实 |
| --- | --- | --- | --- |
| 1 | 只有任务和工具能力 | 列出工作区文件 | 知道 `hello.py` 不存在 |
| 2 | 知道目录现状 | 创建 `hello.py` | 文件真实创建并得到哈希 |
| 3 | 知道文件创建成功 | 运行程序 | 得到退出码和标准输出 |
| 4 | 知道输出正确 | 给最终回答 | 运行结束 |

这张表就是 Agent 的本质：每轮用工具取得新事实，再根据新事实决策。

### 7.7 对照项目中的离线真实测试

[`test_fake_model_drives_real_search_read_edit_test_loop`](../tests/integration/test_offline_loop.py#L50) 使用假模型安排下面的固定步骤：

```text
search_text
  → read_file
  → replace_text
  → run_command(pytest)
  → 最终回答
```

模型是假的，所以结果可复现；搜索、读取、修改和测试工具是真的，所以它能验证 Agent 主循环确实把模型决定转成了本地动作。这比只测试单个函数更接近完整运行，同时又不依赖网络和 API 余额。

---

## 8. DeepSeek 适配器：一次请求是怎样完成的

[`providers/deepseek.py`](../src/coding_agent/agents/providers/deepseek.py) 的职责可以概括为“发一次请求，整理一次响应”。

### 8.1 输入

`complete` 接收：

```python
complete(
    messages,               # 当前完整消息历史
    tools,                  # 工具说明
    timeout_seconds=...,    # 本轮剩余允许时间
)
```

适配器复制输入后调用兼容 Chat Completions 的客户端，并使用当前模型设置。核心循环并不依赖厂商返回对象的各种细节，只依赖整理后的 `ModelCompletion`。

### 8.2 输出整理

厂商响应会被转换为：

```python
ModelCompletion(
    finish_reason="tool_calls" or "stop" or ...,
    assistant=AssistantMessage(...),
    usage=TokenUsage(...),
    model="...",
)
```

代码位置：[`normalize_completion`](../src/coding_agent/agents/providers/deepseek.py#L202)。

整理层会检查：

- 响应是否正好包含一个 choice；
- 工具调用是否有 ID、函数名和参数；
- Token 用量是否为有效整数；
- assistant 的文本、推理内容和工具调用能否转换；
- finish reason 是否能交给核心处理。

### 8.3 为什么保留 `reasoning_content`

DeepSeek 推理模型可能在 assistant 消息中返回 `reasoning_content`。当一个工具回合进入下一轮历史时，当前实现会保留厂商要求的 assistant 字段，以维持多轮工具调用协议。

但它不会写入安全 trace，也不会通过 Web 的安全结果摘要永久保存完整推理。原因是详细推理可能体积很大，也可能包含不适合暴露的内容。

代码位置：

- assistant 历史序列化：[`AssistantMessage.as_history_dict`](../src/coding_agent/agents/contracts.py#L90)；
- Web 安全结果：[`_safe_outcome`](../src/coding_agent/agents/runtime/agent_runner.py#L343)。

### 8.4 为什么关闭客户端自己的自动重试

适配器创建客户端时使用 `max_retries=0`，由 Agent 核心控制重试。否则可能出现两层重试：客户端内部重试若干次，Agent 又重试若干次，实际请求数量和时间就难以准确统计。

面试回答：

> 我把重试控制放在 Agent 流程层，因为只有这一层同时知道剩余模型次数、Token 预算、墙钟时间和取消状态。传输层只负责判断某类异常是否值得重试。

### 8.5 非流式请求的取舍

当前核心使用非流式 Chat Completions。优点是状态更简单：每次拿到一个完整 assistant 响应后再校验和执行，不需要拼接被分片的工具参数。

代价是长响应期间前端不能逐 Token 显示文本，只能显示运行事件。对于题目要求，正确实现完整工具循环比增加流式协议更重要。

---

## 9. 工具体系：模型说明、注册中心、真实实现

每个工具有三部分，不要把它们混为一谈。

### 9.1 第一部分：给模型看的说明

[`tools/schemas.py`](../src/coding_agent/agents/tools/schemas.py) 用 JSON Schema 描述工具：

```json
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "读取工作区内的 UTF-8 文本文件……",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {"type": "string"},
        "start_line": {"type": "integer"},
        "end_line": {"type": "integer"}
      },
      "required": ["path"],
      "additionalProperties": false
    }
  }
}
```

Schema 的作用是帮助模型按正确结构生成参数，但不能把它当成安全边界。模型仍可能输出错误 JSON，所以本地还必须验证。

### 9.2 第二部分：注册和调度

[`ToolRegistry`](../src/coding_agent/agents/tools/registry.py#L47) 建立“工具名 → 本地处理函数”的映射，并统一完成：

- 当前权限是否暴露该工具；
- 工具名是否存在；
- 参数能否转成 JSON 数据；
- 是否需要人工审批；
- 调用是否超过剩余时间；
- 工具异常如何转为结构化结果。

这样 `Agent.run` 不需要写 8 个 `if name == ...`，添加或替换工具时边界更清楚。

### 9.3 第三部分：真实本地函数

真实函数负责文件系统或进程操作。例如：

- `read_file` 打开并读取文件；
- `replace_text` 检查旧文本和哈希后替换；
- `run_command` 创建子进程并收集 stdout、stderr。

### 9.4 当前 8 个工具

| 工具 | 用途 | 是否改变工作区 | 主要实现 |
| --- | --- | --- | --- |
| `list_files` | 查看目录和文件 | 否 | [`list_files`](../src/coding_agent/agents/tools/filesystem.py#L27) |
| `read_file` | 读取 UTF-8 文本及哈希 | 否 | [`read_file`](../src/coding_agent/agents/tools/filesystem.py#L128) |
| `search_text` | 在文本文件中搜索字面量 | 否 | [`search_text`](../src/coding_agent/agents/tools/search.py#L30) |
| `make_directory` | 创建目录 | 是 | [`make_directory`](../src/coding_agent/agents/tools/filesystem.py#L189) |
| `write_file` | 只创建不存在的新文件 | 是 | [`write_file`](../src/coding_agent/agents/tools/filesystem.py#L212) |
| `replace_text` | 在已有文件中精确替换一次 | 是 | [`replace_text`](../src/coding_agent/agents/tools/filesystem.py#L255) |
| `delete_file` | 删除满足条件的普通文件 | 是 | [`delete_file`](../src/coding_agent/agents/tools/filesystem.py#L341) |
| `run_command` | 运行受策略控制的命令 | 可能 | [`run_command`](../src/coding_agent/agents/tools/command.py#L127) |

### 9.5 为什么没有一个“万能 shell 工具”

万能 shell 虽然代码少，但模型可以利用重定向、管道、命令替换等绕过文件边界，而且很难判断实际会执行什么。

本项目把常见文件操作拆成显式工具，命令则要求 `argv` 数组，并使用 `shell=False`。例如：

```json
{
  "argv": ["python", "-m", "pytest", "-q"],
  "cwd": ".",
  "timeout_seconds": 30
}
```

数组中的每项是一个确定参数，不会把 `|`、`>`、`$()` 当作 shell 语法解释。

### 9.6 工具错误为什么统一成 JSON

如果每个工具任意返回字符串，模型很难稳定判断“成功还是失败”“错误码是什么”“输出是否截断”。当前统一结构让模型和前端都能读取：

```text
ok      成功或失败
data    正常数据，或失败时仍有价值的数据
error   稳定错误码和简短说明
meta    时长、截断、重复提示等附加信息
```

代码位置：[`tool_protocol.py`](../src/coding_agent/agents/tool_protocol.py)。

---

## 10. 文件工具中的关键设计

### 10.1 所有路径都相对工作区

模型只能传工作区相对路径。下面这些输入会被拒绝：

```text
C:\Users\...       绝对路径
../outside.py       向上逃逸
.git/config         受保护路径
.env                可能包含密钥
key.pem             私钥或证书类文件
```

代码位置：

- 路径分段检查：[`Workspace.relative_parts`](../src/coding_agent/agents/security/workspace.py#L122)；
- 解析已有路径：[`Workspace.resolve_existing`](../src/coding_agent/agents/security/workspace.py#L214)；
- 受保护文件判断：[`workspace.py`](../src/coding_agent/agents/security/workspace.py)。

检查字符串前缀还不够，因为符号链接可能从工作区内部指向外部。实现还会检查解析后的真实路径和 Windows reparse point，避免通过链接绕过边界。

### 10.2 `write_file` 为什么只负责新文件

如果 `write_file` 同时可以无条件覆盖已有文件，模型一次错误调用就可能抹掉用户代码。当前把语义拆开：

- 新文件：`write_file`；
- 修改已有文件：先 `read_file`，再 `replace_text`；
- 删除已有文件：`delete_file`，并需要哈希。

不同意图使用不同工具，更容易审批和审计。

### 10.3 `read_file → expected_sha256 → replace_text`

这是文件修改中最值得讲的设计。

第一步，`read_file` 返回内容和 SHA-256：

```json
{
  "content": "def add(a, b):\n    return a - b\n",
  "sha256": "abc123..."
}
```

第二步，模型请求替换时必须带回读取时的哈希：

```json
{
  "path": "mathutil.py",
  "old_text": "return a - b",
  "new_text": "return a + b",
  "expected_sha256": "abc123..."
}
```

第三步，工具在真正替换前再次计算当前文件哈希：

- 相同：说明文件仍是模型刚才看到的版本，可以继续；
- 不同：说明用户或其他进程已经改过文件，拒绝覆盖，要求模型重新读取。

这叫“基于版本的并发保护”，不需要记术语也可以这样解释：

> 我要求模型证明它修改的是自己刚刚读到的那一版文件。如果读取后文件被别人改了，哈希会变化，本次修改会失败，从而避免覆盖用户的新改动。

代码位置：

- 读取和生成哈希：[`read_file`](../src/coding_agent/agents/tools/filesystem.py#L128)；
- 精确替换：[`replace_text`](../src/coding_agent/agents/tools/filesystem.py#L255)；
- 原子替换前再次校验：[`Workspace.atomic_replace`](../src/coding_agent/agents/security/workspace.py#L501)。

### 10.4 为什么 `old_text` 必须只出现一次

如果旧文本在文件中出现多次，模型可能不知道哪一处应该修改。当前要求精确匹配且唯一；否则返回错误，让模型读取更具体的上下文并提供更精确片段。

这样比“默认替换全部”更不容易产生大范围误改。

### 10.5 为什么使用原子写入

写文件时如果进程在写到一半崩溃，直接覆盖可能留下半个文件。原子写入通常先在同目录准备完整临时文件，再以文件系统的原子操作创建或替换目标。

本项目实现：

- 原子创建：[`Workspace.atomic_create`](../src/coding_agent/agents/security/workspace.py#L457)；
- 原子替换：[`Workspace.atomic_replace`](../src/coding_agent/agents/security/workspace.py#L501)。

“原子”不表示绝对不会发生任何系统级故障，而是对正常并发和进程中断提供比直接覆盖更清晰的成功/失败边界。

### 10.6 为什么只读取 UTF-8 文本

Coding Agent 的主要目标是源码和配置文本。对二进制、未知编码文件强行解码，容易产生乱码和破坏。当前 `read_file` 限定 UTF-8/UTF-8-SIG，并保留 BOM 与换行信息，修改时尽量维持原文件格式。

### 10.7 为什么有读取和搜索上限

工作区可能包含几万个文件或超大生成文件。若一次全部塞进模型：

- 消耗大量 Token；
- 响应变慢；
- 重要信息被噪声淹没；
- 可能超过模型上下文限制。

所以 `list_files`、`read_file`、`search_text` 都限制扫描规模和返回长度，并通过 `truncated` 告诉模型结果是否被截断。模型应该缩小路径或搜索范围，而不是反复请求整个仓库。

---

## 11. `run_command`：最强也最危险的工具

### 11.1 命令为什么使用 `argv`

工具参数是：

```json
{
  "argv": ["python", "-m", "pytest", "-q"],
  "cwd": ".",
  "timeout_seconds": 30
}
```

而不是：

```json
{"command": "python -m pytest -q | something > file"}
```

真实启动使用 `subprocess.Popen(..., shell=False)`。这降低了 shell 注入和重定向绕过文件工具的风险。

代码位置：[`run_command`](../src/coding_agent/agents/tools/command.py#L127)。

### 11.2 命令分类

[`command_policy.py`](../src/coding_agent/agents/security/command_policy.py) 把命令分成三类：

| 决定 | 含义 | 示例 |
| --- | --- | --- |
| `ALLOW` | 可以自动执行 | 当前 Python 的固定 `-m pytest`、`unittest`、`compileall` 安全形式；部分只读 Git 命令 |
| `CONFIRM` | 必须用户批准 | 任意 Python 脚本、未知可执行程序、可能有副作用的常规命令 |
| `DENY` | 无论权限模式都拒绝 | shell 主机、批处理、危险 Git 历史/远程操作、明显破坏或提权程序 |

不要把“自动允许 pytest”理解为所有以 `python` 开头的命令都安全。策略会检查当前解释器、`-m` 模块和后续参数。

### 11.3 三档权限不会绕过禁止规则

权限模式见 [`PermissionMode`](../src/coding_agent/agents/security/permission_policy.py)：

| 模式 | 普通文件修改 | 删除文件 | 需要确认的命令 | 禁止命令 |
| --- | --- | --- | --- | --- |
| `ask` | 每次确认 | 每次确认 | 确认 | 拒绝 |
| `agent` | 自动 | 确认 | 确认 | 拒绝 |
| `workspace_full` | 工作区内自动 | 工作区内自动 | 策略允许的范围内自动 | 仍拒绝 |

面试时要明确：`workspace_full` 不是“关闭安全”，只是减少工作区内正常操作的确认。工作区逃逸、受保护文件和命令硬禁止仍然生效。

### 11.4 子进程环境为什么要清理

父进程中可能有：

- `DEEPSEEK_API_KEY`；
- 数据库密码；
- 各种 Token；
- 会影响 Python 或 Git 行为的环境变量；
- 把工作区目录放在前面的 `PATH`。

如果原样传给模型启动的程序，工作区代码可能读取密钥，或用一个伪造的 `python.exe` 抢占真实解释器。当前构造最小环境，删除敏感变量，并从清理后的 PATH 解析可执行文件绝对路径。

代码位置：

- 敏感变量集合：[`command_policy.py`](../src/coding_agent/agents/security/command_policy.py)；
- 子进程环境：[`Workspace.sanitized_environment`](../src/coding_agent/agents/security/workspace.py#L628)；
- 可执行文件解析：[`Workspace.prepare_command`](../src/coding_agent/agents/security/workspace.py#L739)。

### 11.5 为什么分别读取 stdout 和 stderr

子进程的两个管道都有容量上限。如果程序大量写 stderr，而父进程只读 stdout，子进程可能因为 stderr 管道写满而阻塞。

当前使用两个读取线程同时排空 stdout 和 stderr，再由有界缓冲区保留头部和尾部，避免无限占用内存。

代码位置：

- 有界字节缓冲：[`_BoundedBytes`](../src/coding_agent/agents/tools/command.py)；
- 两个 drain 线程：[`run_command`](../src/coding_agent/agents/tools/command.py#L127)。

### 11.6 超时和取消

工具自己的 `timeout_seconds` 还会受到 Agent 剩余墙钟时间限制。假设用户给命令 120 秒，但整个 Agent 只剩 8 秒，本次命令不能再独占 120 秒。

运行过程中轮询：

- 用户是否取消；
- 命令截止时间是否到达；
- 进程是否退出。

超时或取消时会尽力终止进程树，并把结构化结果回填。

### 11.7 安全边界要诚实说明

当前实现提供工作区路径控制、命令策略、环境清理、审批和超时，但它不是操作系统级沙箱。一个被允许执行的任意程序仍然使用当前用户权限运行。

正确表述：

> 这是应用层安全策略，不是容器、虚拟机或低权限系统账户提供的强隔离。因此我对任意脚本和未知命令保留人工确认，并明确不把它宣传为系统沙箱。

这种诚实边界通常比夸大“绝对安全”更能体现工程判断。

---

## 12. 上下文、历史会话和长期记忆

这三个概念经常被初学者混淆。

### 12.1 当前运行消息历史

`Agent.run` 中的 `messages` 是本次运行正在使用的完整模型历史，包含：

- 本次系统提示；
- 运行开始时选入的旧会话；
- 当前任务；
- 本次运行产生的 assistant 工具调用；
- 本地工具结果；
- 最终 assistant 文本。

它随着每轮工具调用增长，只活在本次运行内，最后可进入 `RunResult.messages`。

### 12.2 可见的旧会话

Web 中用户可能在同一会话连续发多条消息。新运行开始前，会读取先前对用户可见的 user/assistant 消息，转换成 [`VisibleMessage`](../src/coding_agent/agents/context.py#L17)。

它刻意不包含：

- 旧运行的完整工具输出；
- 私有推理内容；
- 未限制体积的任意内部字段。

这样可以继续对话，同时避免历史无限膨胀或把内部细节长期重复发送。

### 12.3 长期记忆

长期记忆是用户确认后保存的工作区事实，例如：

```text
“本项目后端测试命令是 python -m pytest”
“不要修改 generated/ 目录”
“代码格式使用 4 空格缩进”
```

模型不能调用工具自行写入记忆。记忆由用户通过 Web 操作确认，再由 [`WorkspaceMemoryService`](../src/coding_agent/services/memory_service.py) 写入 PostgreSQL。

这样设计避免模型把一次错误猜测永久保存，污染以后所有任务。

### 12.4 为什么运行开始时冻结快照

一次运行开始时会冻结：

- 权限模式；
- 旧会话可见历史；
- 选中的记忆；
- 工作区路径；
- 当前任务。

运行中即使数据库里的记忆被改动，也不应该让本次模型上下文突然变化。冻结快照使一次运行的输入边界清楚，也更容易复现和解释。

代码位置：

- 快照数据结构：[`AgentContext`](../src/coding_agent/agents/context.py#L61)；
- Web 运行输入：[`RunSpec`](../src/coding_agent/agents/runtime/agent_runner.py)；
- 组装快照：[`ConversationRunService.create`](../src/coding_agent/services/run_service.py)。

### 12.5 历史如何裁剪

历史会话不能无限放入模型。`AgentContextBuilder` 按以下限制选择最新的完整后缀：

- 最多多少条可见消息；
- 历史总字符数；
- 单条消息最大字符数；
- 记忆条数；
- 记忆总字符数；
- 单条记忆最大字符数。

代码位置：[`AgentContextBuilder.build`](../src/coding_agent/agents/context.py#L138)。

为什么保留“最新完整后缀”？因为最近对话通常与当前追问最相关；从消息中间随便截一段，可能留下没有对应问题的答案。

### 12.6 当前默认上下文限制

默认值在 [`AgentConfig`](../src/coding_agent/agents/config.py#L11)：

| 项目 | 默认值 |
| --- | ---: |
| 旧会话最多消息数 | 48 |
| 旧会话总字符数 | 100,000 |
| 单条旧消息字符数 | 24,000 |
| 记忆最多条数 | 32 |
| 记忆总字符数 | 32,000 |
| 单条记忆字符数 | 4,000 |

这些是应用层字符限制，不是模型 Token 上下文的精确换算。总 Token 仍以厂商返回的用量为准。

### 12.7 记忆不等于 RAG

当前实现没有 embedding、向量数据库或语义检索。它只是从 PostgreSQL 取出用户确认的少量记忆，再按固定优先顺序和体积限制装入上下文。

面试时不要声称项目已经实现 RAG 或 pgvector 检索。可以说：

> 当前记忆重点解决可控和可解释：只有用户确认的数据可以进入长期记忆。语义检索是未来数据量变大后的扩展方向，不是本版必须功能。

---

## 13. 预算、终止和取消

没有预算的 Agent 可能因为模型反复读同一个文件、持续修复失败测试或网络重试而一直运行。当前项目同时使用四类硬预算。

### 13.1 默认预算

[`AgentConfig`](../src/coding_agent/agents/config.py#L11) 当前默认值：

| 预算 | 默认值 | 作用 |
| --- | ---: | --- |
| `max_model_calls` | 50 | 限制向模型发请求的次数 |
| `max_tool_calls` | 100 | 限制本地工具调用总数 |
| `max_total_tokens` | 1,000,000 | 限制模型累计 Token |
| `wall_time_seconds` | 600 秒 | 限制整次运行现实耗时 |
| `api_timeout_seconds` | 60 秒 | 限制单次 API 等待 |
| `max_transient_retries` | 3 | 限制每轮短暂 API 错误重试 |

代码使用冻结的 `AgentConfig`，运行中不能被模型修改。

### 13.2 为什么需要四种预算

只限制一个维度会留下漏洞：

- 只限模型次数：一轮可能消耗很多 Token；
- 只限 Token：工具可能长时间运行但不消耗 Token；
- 只限工具次数：模型可能反复请求但不调用工具；
- 只限时间：短时间内仍可能产生大量请求和费用。

组合限制能够更准确地约束成本和时间。

### 13.3 终止原因

[`TerminationReason`](../src/coding_agent/agents/contracts.py#L20) 让“为什么结束”成为稳定数据，而不只是错误字符串。常见原因包括：

| 原因 | 说明 |
| --- | --- |
| `model_final` | 模型返回了合法最终文本 |
| `max_model_calls` | 模型调用次数耗尽 |
| `max_tool_calls` | 工具调用次数耗尽 |
| Token 预算原因 | 累计 Token 达到上限 |
| 墙钟时间原因 | 整体时间达到上限 |
| `api_fatal` | 模型 API 发生不可重试错误 |
| `content_filtered` | 响应被内容策略过滤 |
| `truncated_response` | 模型响应被长度截断 |
| `protocol_error` | 模型响应或工具协议不自洽 |
| `user_cancelled` | 用户请求停止 |
| `internal_invariant` | 程序内部不应发生的状态被触发 |

### 13.4 状态和终止原因的区别

[`AgentStatus`](../src/coding_agent/agents/contracts.py#L11) 是大类，例如：

- `MODEL_FINISHED`；
- `FAILED`；
- `CANCELLED`；
- `BUDGET_EXHAUSTED`。

`TerminationReason` 是更具体的原因。例如模型次数和时间耗尽都属于 `BUDGET_EXHAUSTED`，但前端和评测可以根据 reason 区分是哪一项预算。

### 13.5 取消为什么是协作式的

Web 点击停止后，不会粗暴杀死整个后端进程，而是设置取消状态。Agent 在以下边界主动检查：

- 新一轮模型请求前；
- API 重试之间；
- 每个工具执行前；
- 命令运行轮询中；
- 一批工具调用之间。

代码位置：

- 核心取消检查：[`Agent._cancelled`](../src/coding_agent/agents/agent.py)；
- Web 运行状态：[`RunManager`](../src/coding_agent/agents/runtime/run_manager.py#L422)；
- 命令取消：[`run_command`](../src/coding_agent/agents/tools/command.py#L127)。

如果网络请求库不能立刻响应取消，最晚会受到单次 API timeout 和总墙钟时间约束。对本地子进程则会尽力终止进程树。

### 13.6 预算耗尽不是异常崩溃

预算耗尽是预期终态。它应该生成完整 `RunResult`，记录已用次数、Token、消息和修改检查状态，而不是抛出未处理异常导致前端永远显示“运行中”。

---

## 14. 错误处理：哪种失败应该结束，哪种应该继续

### 14.1 模型 API 短暂失败

网络超时、连接失败、429、500、503 通常可能恢复。程序在预算内退避重试，不把失败响应写进消息历史。

### 14.2 模型 API 致命失败

鉴权、请求格式等不可恢复错误继续重试没有意义。运行以明确原因结束。

### 14.3 模型协议错误

例如：

- `stop` 同时携带工具调用；
- `tool_calls` 却没有任何调用；
- 工具调用 ID 重复；
- 一批工具数量超过剩余预算；
- 工具参数 JSON 顶层不是对象。

有些参数错误可以作为工具失败结果回填，让模型改正；破坏整轮消息结构的冲突则直接以协议错误终止。

### 14.4 工具业务失败

例如：

- 文件不存在；
- `old_text` 不唯一；
- 哈希已经变化；
- 搜索无匹配；
- 命令退出码非零。

这些通常是模型需要的新事实，因此返回结构化工具结果，循环继续。

### 14.5 工具实现异常

工具函数抛出的已知 `ToolError`、工作区错误、编码错误、操作系统错误会被 `ToolRegistry` 转成稳定 JSON。意外异常也被隔离为工具失败，避免一个工具直接炸掉整个 Agent 进程。

代码位置：[`ToolRegistry.execute`](../src/coding_agent/agents/tools/registry.py#L148)。

### 14.6 测试失败不是 Agent 系统失败

`pytest` 返回 1，说明候选代码还没通过测试。`run_command` 会返回失败结果，但 Agent 主循环仍正常。模型看到失败后可以继续修复。

应区分：

```text
命令运行成功且退出码 0       工具成功
命令成功启动但测试退出码 1   工具返回业务失败，Agent 可继续
命令根本无法启动             工具执行失败，Agent 可换策略
模型 API 致命错误             整个 Agent 运行失败
```

### 14.7 追踪记录失败为什么不影响任务

诊断 trace 是辅助观察功能，不是完成用户任务的必要条件。如果写 trace 失败就让代码修改任务失败，主功能会被次要功能拖垮。因此 `Agent._emit` 对 trace 异常采用尽力而为的处理。

---

## 15. Web 运行链路：同一个 Agent 如何接到网页上

后端和前端不是面试重点，但需要知道网页没有另写一套 Agent。

### 15.1 一次 Web 请求的路径

```text
用户在 Vue 页面发送任务
  → FastAPI 接口
  → ConversationRunService
      ├─ 在 PostgreSQL 保存用户消息和运行记录
      ├─ 读取可见历史
      └─ 冻结已确认记忆
  → RunManager 创建后台运行
  → AgentRunner 组装一次 Agent
      ├─ Workspace
      ├─ DeepSeekAdapter
      ├─ ToolRegistry
      ├─ AgentConfig
      └─ AgentContext
  → Agent.run 执行核心循环
  → 事件和状态返回前端
  → 最终摘要持久化
```

主要代码：

- 业务入口：[`ConversationRunService.create`](../src/coding_agent/services/run_service.py)；
- 后台管理：[`RunManager.create`](../src/coding_agent/agents/runtime/run_manager.py#L505)；
- 单次组装：[`AgentRunner.run`](../src/coding_agent/agents/runtime/agent_runner.py#L214)；
- 核心循环：[`Agent.run`](../src/coding_agent/agents/agent.py#L190)。

### 15.2 为什么 `AgentRunner` 每次新建适配器和工具注册中心

一次运行拥有固定工作区、权限、上下文和取消函数。每次新建对象可以避免不同用户任务之间意外共享：

- HTTP 客户端状态；
- 工具工作区；
- 权限设置；
- 追踪输出；
- 运行 ID 和取消信号。

结束时关闭适配器，资源生命周期清楚。

### 15.3 `RunManager` 解决什么问题

核心 `Agent.run` 是同步循环；Web 不能让一个 HTTP 请求阻塞几分钟，所以 `RunManager` 用后台线程运行它，并管理：

- `starting`、`running`、`waiting_approval`、`cancelling` 等状态；
- 全局最大并发；
- 同一工作区同时只允许一个活跃写入运行；
- 用户取消；
- 最近运行保留；
- 完成后的回调和事件。

同一工作区限制一个活跃运行，可以减少两个 Agent 同时修改同一文件造成的冲突。文件哈希仍提供最后一道并发保护。

### 15.4 人工审批如何从线程到网页

Agent 工具调用是同步的：它需要立即得到“允许/拒绝”。网页操作是异步的：后端先发出待审批事件，等用户点击后再收到 HTTP 请求。

[`ApprovalBroker`](../src/coding_agent/agents/runtime/approval_broker.py#L71) 负责连接两者：

1. Agent 线程提交审批请求；
2. 运行状态变成 `waiting_approval`；
3. 前端通过事件看到命令摘要；
4. 用户允许或拒绝；
5. Broker 唤醒等待中的 Agent 线程；
6. 工具继续执行或返回拒绝结果。

审批有超时，也会响应取消，防止 Agent 永久卡在等待状态。

### 15.5 实时事件如何传给前端

[`EventBuffer`](../src/coding_agent/agents/runtime/event_buffer.py#L95) 保存带递增序号的有限事件队列。前端通过 SSE 获取新事件，用于显示：

- 运行开始；
- 模型完成一轮决定；
- 工具开始和结束；
- 等待审批；
- 操作被批准或拒绝；
- 运行完成或失败。

事件队列有最大长度，防止长任务无限占用内存。序号让前端知道自己读到了哪里。

### 15.6 PostgreSQL 保存什么，内存保存什么

可以按生命周期区分：

| 数据 | 主要位置 | 原因 |
| --- | --- | --- |
| 会话、用户消息、最终回答 | PostgreSQL | 服务重启后仍需存在 |
| 运行记录、审批、持久事件 | PostgreSQL | 页面回看和审计需要 |
| 用户确认的记忆 | PostgreSQL | 跨会话长期使用 |
| 当前 `messages` 完整工具历史 | Agent 运行内存 | 供当前循环继续推理 |
| 当前取消信号、等待条件 | RunManager/Broker 内存 | 只在活跃运行中有效 |
| SSE 最近事件缓冲 | EventBuffer 内存 | 快速推送，且长度受限 |

### 15.7 为什么 Web 最终结果不保存完整私有推理

[`_safe_outcome`](../src/coding_agent/agents/runtime/agent_runner.py#L343) 只保存安全摘要，不把完整 prompts、reasoning、工具 stdout/stderr 全部永久写入普通运行结果。这减少敏感源码和推理内容的长期暴露。

需要调试时使用经过字段白名单限制的 trace 和运行事件，而不是无条件保存所有内部数据。

---

## 16. CLI 运行链路

CLI 是最直接的 Agent 入口，而且不依赖 Web、PostgreSQL 或前端。

### 16.1 命令示例

```powershell
conda activate coding-agent
Set-Location E:\code\agent_project\backend
$env:DEEPSEEK_API_KEY="你的实际密钥"
coding-agent --workspace E:\path\to\demo "请生成 hello.py 并运行检查"
```

自动批准需要确认的常规命令时可加 `--yes`，但禁止命令仍然被拒绝：

```powershell
coding-agent --yes --workspace E:\path\to\demo "修复测试并运行 pytest"
```

### 16.2 CLI 四个组装步骤

[`run_cli`](../src/coding_agent/cli.py#L203) 做四件事：

1. 读取环境变量，检查任务、密钥和 API 地址；
2. 创建 `Workspace`、trace、`DeepSeekAdapter`、`ToolRegistry` 和 `AgentConfig`；
3. 调用 `Agent.run`；
4. 把最终状态映射成 stdout、stderr 和进程退出码。

它不包含主循环和具体工具逻辑，所以 CLI 和 Web 可以复用同一个核心。

### 16.3 stdout 和 stderr 为什么分开

- stdout：只输出最终模型内容，方便脚本捕获；
- stderr：输出审批提示、诊断事件和最终统计。

评测系统可以分别保存两者，避免状态日志混入最终回答。

### 16.4 CLI 的密钥来源

CLI 只读取当前进程环境中的 `DEEPSEEK_API_KEY`，不自动加载 Web 的 `.env`。这样避免命令行工具无意读取另一套部署配置。

---

## 17. 诊断 Trace：能观察，但不泄露全部内容

### 17.1 Trace 记录什么

[`TraceWriter`](../src/coding_agent/agents/diagnostics/trace.py#L183) 使用 JSONL，也就是每行一个 JSON 事件。记录重点是流程事实，例如：

- 第几次模型调用；
- 模型返回的是工具调用还是最终回答；
- 调用了哪个工具；
- 工具成功还是失败；
- 用时和截断情况；
- 最终状态、终止原因和计数。

### 17.2 Trace 不记录什么

安全 trace 不应记录：

- API key；
- 完整任务提示；
- 完整源码；
- 私有推理内容；
- 完整 stdout/stderr；
- 任意未经允许的异常对象字段。

实现采用事件名和字段白名单，不是把任意 Python 对象直接序列化。

### 17.3 为什么 Trace 不是完整审计日志

它为了安全主动省略内容，因此适合回答“流程走到哪里、哪个工具失败、耗时多少”，不适合完整恢复每一行源码变化。正式评测另外保存候选工作区快照、文件哈希和外部验收结果。

### 17.4 运行检查器为什么能显示详细步骤

Web 公开事件由 [`BufferTrace`](../src/coding_agent/agents/runtime/event_buffer.py) 把内部事件转换成前端友好的事件类型。前端可以显示：

```text
模型完成一次决策
运行工具：read_file
工具返回成功
运行工具：replace_text
等待人工确认
操作已批准
运行命令：pytest
命令退出码：0
控制循环结束
```

这里显示的是经过清理的运行事实，不等于展示模型隐藏推理。

---

## 18. “修改后检查”与“外部验收”不是一回事

这是项目答辩中非常重要的区分。

### 18.1 模型最终回答

模型返回 `stop`，只能证明模型决定不再调用工具。它可能判断错误。

### 18.2 `ChangeCheck`

核心根据工具事实知道：文件是否被成功修改，最近修改之后是否运行过成功的检查命令。它比模型自述更客观，但仍不知道题目的全部隐藏验收条件。

### 18.3 外部 verifier

评测系统在 Agent 工作区之外执行验收脚本。Agent 看不到参考修复，也不能修改 verifier。只有 verifier 通过，才表示候选工作区满足该评测任务的独立条件。

```text
模型说“完成”
      │
      ▼
Agent change_check 看是否有成功检查
      │
      ▼
工作区外 verifier 检查真实最终代码
      │
      ▼
评测报告给出通过/失败
```

### 18.4 `RunResult.verified` 为什么默认 unknown

[`RunResult`](../src/coding_agent/agents/contracts.py#L284) 把 `verified` 与模型状态分开。普通 CLI 或 Web 运行没有外部 verifier，因此不能擅自写成通过。

这体现了一个重要工程原则：不知道就明确记录 unknown，不用模型语气代替证据。

---

## 19. 可复现评测系统怎么证明 Agent 能工作

评测代码位于 [`backend/evaluation/`](../evaluation/)。它不是让模型回答选择题，而是让 Agent 修改真实候选项目，再用外部脚本验收。

### 19.1 三类任务

任务目录由 [`evaluation/core/catalog.py`](../evaluation/core/catalog.py) 定义：

| 任务 | 类型 | 主要考察能力 |
| --- | --- | --- |
| `date_boundary` | 边界 Bug 修复 | 定位日期结束边界、修改核心逻辑、补回归测试 |
| `category_filter` | 跨文件功能开发 | 同时理解 CLI、Service 和核心逻辑并完成联动修改 |
| `config_precedence` | 回归修复 | 正确处理 `0`、`False`、空字符串等 falsy 值优先级 |

每类任务重复 3 次，所以完整评测共 9 轮。

### 19.2 每轮为什么从干净模板复制

如果第二轮沿用第一轮的已修复工作区，后续运行可能什么都不用做就通过，结果没有意义。因此每一轮都从同一原始模板复制出独立候选工作区。

### 19.3 Agent 能看到什么

Agent 可看到：

- 候选项目源码；
- `TASK.md` 中的任务描述；
- 自己运行工具得到的结果。

Agent 看不到：

- 工作区外 verifier 的实现；
- 参考修复覆盖层；
- 其他轮的候选修改；
- 主进程中的 API key 和评测秘密。

### 19.4 一轮评测的步骤

[`evaluation/core/runner.py`](../evaluation/core/runner.py) 大致执行：

1. 创建独立候选目录；
2. 复制固定任务模板；
3. 记录运行前文件快照和哈希；
4. 以 CLI 方式启动 Agent；
5. 保存 Agent stdout、stderr 和安全 trace；
6. 记录运行后工作区变化；
7. 在工作区外执行 verifier；
8. 汇总终止原因、修改检查和验收结果；
9. 写入 `trial.json`、`summary.json` 和 Markdown 报告。

### 19.5 为什么 verifier 要在 Agent 工作区外

如果测试脚本和答案都在工作区内，Agent 可能直接读取测试细节，甚至误改验收脚本。把 verifier 放在外部可以更接近真实交付：只检查最终代码，不让候选程序控制评分规则。

### 19.6 当前保存的正式结果

当前归档报告：[`benchmark-20260829T140452Z/BENCHMARK_REPORT.md`](evaluation-results/benchmark-20260829T140452Z/BENCHMARK_REPORT.md)。

关键结果：

```text
模型：deepseek-v4-flash
源码提交：536c94158978afc68ab0a273635a94807bba5135
源码状态：干净
外部验收：9/9
端到端成功：9/9
修改后检查通过：9/9
状态不一致：0
```

### 19.7 9/9 能证明什么

它能够支持以下结论：

- Agent 可以在三个不同类型的固定任务上读取、修改和验证代码；
- 每类任务从干净模板重复三次仍然通过；
- 最终工作区通过了 Agent 看不到的外部验收；
- 模型终态、修改检查和外部验收在这 9 轮中没有出现不一致；
- 结果对应明确源码提交，并且评测开始时源码状态干净。

### 19.8 9/9 不能证明什么

不能夸大为：

- 所有编程任务都能 100% 完成；
- 模型以后更新后仍然必然 9/9；
- 系统达到生产环境绝对安全；
- 三个任务覆盖了所有语言、框架和大型仓库；
- 单次小样本足以给出精确的通用成功率。

面试回答建议：

> 9/9 是固定版本、固定三类任务、每类三次的可复现实验结果，能证明核心闭环在这些任务上稳定工作，但样本量仍小。它是工程证据，不是对所有任务成功率的无限外推。

### 19.9 正式评测命令

```powershell
conda activate coding-agent
Set-Location E:\code\agent_project\backend
$env:DEEPSEEK_API_KEY="实际密钥"
python -m evaluation.run_benchmark --model deepseek-v4-flash --repeats 3
```

单任务调试：

```powershell
python -m evaluation.run_benchmark --task date_boundary --repeats 1
```

不要手工伪造 `summary.json`，也不要把参考修复通过当成 Agent 真实通过。

---

## 20. 测试体系：不用真实 API 也能验证核心

### 20.1 为什么要用假模型

真实模型输出有随机性、需要网络、会消耗费用，也可能因服务端状态波动。核心逻辑测试需要固定输入和固定预期，所以使用实现同一 `complete` 接口的假适配器。

代码位置：[`ScriptedAdapter`](../tests/integration/test_offline_loop.py#L20)。

### 20.2 离线端到端循环测试

[`test_offline_loop.py`](../tests/integration/test_offline_loop.py) 先创建一个有 Bug 的 `mathutil.py` 和测试文件，然后让假模型依次返回：

1. `search_text`；
2. `read_file`；
3. `replace_text`；
4. `run_command(pytest)`；
5. 最终回答。

断言包括：

- 最终状态是模型完成；
- 模型调用 5 次；
- 工具调用 4 次；
- 真实文件从减法变成加法；
- 每个工具结果 `ok` 为 true；
- 最后命令退出码为 0；
- 下一轮历史保留上一轮 assistant 所需字段；
- 模型收到 8 个工具说明。

### 20.3 核心边界测试

[`tests/core/test_agent.py`](../tests/core/test_agent.py) 重点覆盖：

- `stop` 与 `tool_calls` 分支；
- 截断和内容过滤；
- 工具调用 ID 唯一；
- 严格 JSON；
- 一批工具中某个失败后，后续调用仍有对应结果；
- 第三次完全重复只提示，不直接终止；
- API 短暂错误重试；
- 模型、工具、Token 和时间预算；
- trace 写入失败不破坏主任务。

### 20.4 工具和安全测试

继续阅读：

- [`tests/tools/`](../tests/tools/)：文件、搜索和命令工具；
- [`tests/security/`](../tests/security/)：路径、权限和命令分类；
- [`tests/application/`](../tests/application/) 和 [`tests/web/`](../tests/web/)：后台运行、审批、事件、取消和 Web 接口；
- [`tests/evaluation/`](../tests/evaluation/)：评测复制、验收、报告。

目录若因当前版本组织略有不同，可用下面命令定位：

```powershell
rg -n "class ScriptedAdapter|RepeatedToolExchange|waiting_approval|expected_sha256" backend/tests
```

### 20.5 本地测试命令

```powershell
conda activate coding-agent
Set-Location E:\code\agent_project\backend
python -m pytest
```

只运行离线主循环测试：

```powershell
python -m pytest tests/integration/test_offline_loop.py -q
```

只运行核心 Agent 测试：

```powershell
python -m pytest tests/core/test_agent.py -q
```

---

## 21. 一次 Bug 修复任务的更真实流程

“生成新文件”案例容易理解，但真实 Coding Agent 更常见的是修 Bug。假设任务是：

> `add(2, 3)` 错误返回 -1，请修复并运行测试。

合理流程是：

### 21.1 搜索定义

```json
{
  "name": "search_text",
  "arguments": {
    "query": "def add",
    "path": ".",
    "glob": "*.py"
  }
}
```

模型通过搜索缩小范围，而不是读取整个项目。

### 21.2 读取目标文件

```json
{
  "name": "read_file",
  "arguments": {"path": "mathutil.py"}
}
```

结果同时提供源码、行信息和 SHA-256。

### 21.3 精确修改

```json
{
  "name": "replace_text",
  "arguments": {
    "path": "mathutil.py",
    "old_text": "return left - right",
    "new_text": "return left + right",
    "expected_sha256": "读取时得到的哈希"
  }
}
```

### 21.4 运行测试

```json
{
  "name": "run_command",
  "arguments": {
    "argv": ["当前 Python 解释器", "-m", "pytest", "-q"],
    "cwd": ".",
    "timeout_seconds": 30
  }
}
```

### 21.5 测试失败后的自我修正

如果结果显示另一个测试失败，模型下一轮应：

1. 阅读失败堆栈；
2. 找到相关测试和实现；
3. 判断是修改不完整还是破坏原行为；
4. 重新读取当前文件，取得新哈希；
5. 再做小范围修改；
6. 重跑测试。

每次修改后哈希都会变化，所以不能复用第一次的 `expected_sha256`。这也是消息历史必须包含最新工具结果的原因。

### 21.6 最终回答应该包含什么

一个可信的最终回答至少说明：

- 修改了什么；
- 为什么能解决问题；
- 运行了什么检查；
- 检查的真实结果；
- 如果没有完成或有风险，明确说明。

系统提示词要求模型不能在没有工具证据时声称测试通过。

---

## 22. 常见误解与正确说法

### 22.1 “DeepSeek 帮我执行了本地文件操作”

错误。DeepSeek 只返回工具调用意图，本地工具由我们的 Python 代码执行。

### 22.2 “使用 OpenAI Python 包，所以用了 OpenAI Agent SDK”

错误。项目使用的是基础兼容 API 客户端，不是 Agents SDK；核心循环完全自写。

### 22.3 “模型最后说成功，所以任务通过”

错误。模型最终文本、`ChangeCheck`、外部 verifier 是三个层级。

### 22.4 “workspace_full 可以执行任何命令”

错误。硬禁止命令、工作区边界和受保护文件仍生效。

### 22.5 “命令策略就是操作系统沙箱”

错误。它是应用层限制，被批准的进程仍使用当前用户权限。

### 22.6 “重复工具调用三次后任务会自动终止”

错误。当前实现从第三次起给模型添加调整策略提示，但不直接终止；硬预算兜底。

### 22.7 “项目现在有 6 个工具”

错误。当前源码有 8 个工具，新增了 `make_directory` 和 `delete_file` 等完整文件操作能力。以 [`schemas.py`](../src/coding_agent/agents/tools/schemas.py) 和离线测试断言为准。

### 22.8 “长期记忆由模型自动学习写入”

错误。模型没有写记忆工具；记忆必须由用户确认。

### 22.9 “当前已经实现向量检索/RAG”

错误。当前是有数量和体积限制的确认记忆快照，没有 embedding 或 pgvector 检索。

### 22.10 “前端展示的运行步骤就是模型完整思维过程”

错误。页面展示工具名、审批、结果状态、时长等安全事实，不展示完整隐藏推理。

### 22.11 “所有工具失败都应该立刻结束”

错误。文件不存在、测试失败、哈希变化等可能是模型继续工作的必要反馈。只有不可恢复的流程错误才结束运行。

### 22.12 “为了安全加越多校验越好”

也不准确。校验应该服务于明确边界：协议完整、工作区限制、并发写保护、资源预算和敏感信息。无依据地堆重复校验会让逻辑难以维护。本项目尽量在一个明确层次负责一个问题。

---

## 23. 面试高频问题与参考回答

下面不是要求背诵的标准答案，而是帮助建立回答结构。回答时应结合代码和取舍，不要只说名词。

### 23.1 你的 Agent 核心循环是什么？

参考回答：

> 运行开始时我建立 system、历史和当前任务消息，并初始化模型次数、工具次数、Token 与墙钟预算。每轮先检查取消和预算，再把完整消息与当前工具 schema 发给 DeepSeek。返回 `stop` 时校验最终文本并结束；返回 `tool_calls` 时先保存完整 assistant 工具请求，逐个严格解析参数、经过权限策略执行本地工具，再按 tool call ID 回填结构化结果。工具结果成为下一轮的新事实，循环直到模型完成或明确终止条件触发。

代码证据：[`Agent.run`](../src/coding_agent/agents/agent.py#L190)。

### 23.2 为什么不能只调用模型一次？

> 第一次调用只有任务描述，没有工作区真实情况。读文件、修改和测试都会产生新事实，模型必须看到工具反馈才能决定下一步。一次调用只能生成计划或猜测，不能形成“观察—行动—反馈”的闭环。

### 23.3 模型如何调用你的函数？

> 我把 8 个工具的名称、描述和 JSON 参数结构作为原生 tool calling schemas 发给模型。模型返回工具名和 arguments 字符串，本地先做严格 JSON 和参数检查，再由 ToolRegistry 映射到真实函数。执行结果统一成 JSON tool 消息，通过 tool_call_id 回填。

代码证据：[`schemas.py`](../src/coding_agent/agents/tools/schemas.py)、[`registry.py`](../src/coding_agent/agents/tools/registry.py)。

### 23.4 为什么设计 `ToolRegistry`？

> 它把核心循环和具体工具解耦。Agent 只依赖统一执行接口，注册中心集中处理工具查找、权限、审批、超时和异常转换；文件工具只关心文件操作。这样测试、扩展和安全边界都更清楚。

### 23.5 为什么工具失败还要继续？

> 测试失败、文件不存在、哈希冲突都可能是模型需要的新事实。只要消息协议仍完整，就把结构化失败结果回填，让模型修正。API 鉴权失败或响应结构冲突等不可恢复错误才结束整个运行。

### 23.6 如何防止无限循环？

> 使用模型次数、工具次数、累计 Token 和墙钟时间四类硬预算；单次 API 和命令还有自己的 timeout。完全相同工具交换从第三次起提示模型改变策略，但不武断终止，最终由硬预算兜底。

### 23.7 为什么重复调用不直接终止？

> 相同读取在文件可能变化或需要复查时不一定错误，单靠次数终止容易误伤。我把它作为软进度信号，同时保留工具次数和总时间作为确定的硬上限。

### 23.8 如何避免覆盖用户刚改的代码？

> 读取文件时返回 SHA-256，修改和删除必须带回 expected hash。真正替换前再次计算当前哈希，若不同就拒绝并要求重新读取；写入本身使用原子替换。Web 还限制同一工作区只有一个活跃 Agent。

代码证据：[`filesystem.py`](../src/coding_agent/agents/tools/filesystem.py)、[`workspace.py`](../src/coding_agent/agents/security/workspace.py)。

### 23.9 三档权限怎么设计？

> `ask` 对修改和命令逐次确认；`agent` 自动批准普通工作区修改，但删除和风险命令确认；`workspace_full` 减少工作区内允许操作的确认。三档都不能越过工作区，也不能绕过命令硬禁止。权限在运行开始时冻结。

### 23.10 你的安全方案有什么边界？

> 当前提供应用层工作区隔离、链接检查、受保护文件、命令分类、shell=False、环境清理、审批、超时和输出限制。它不是系统调用级沙箱，被允许执行的代码仍用当前用户权限，所以任意脚本和未知命令需要确认。生产化可进一步用容器或低权限账户隔离执行器。

### 23.11 为什么不把完整推理显示给前端？

> 运行可观测性主要依赖工具调用、结果状态、耗时和终止原因这些事实。完整推理可能包含敏感信息、体积大且不稳定，所以安全 trace 和持久结果只保留白名单字段。

### 23.12 如何证明不是套壳？

> 可以直接展示 `Agent.run` 的循环、DeepSeek 单次适配器、工具 schema、ToolRegistry、本地文件和命令实现、预算和终止原因，再运行使用假模型驱动真实工具的离线集成测试。基础客户端只做 HTTP，请求循环和本地执行都在项目源码里。

### 23.13 评测为什么可信？

> 每轮从同一干净模板复制，Agent 只能看到任务和候选代码，外部 verifier 与参考修复在工作区外。最终以 verifier 检查候选工作区，而不是模型自述评分。报告还记录源码提交、dirty 状态、trace 和文件变化。

### 23.14 9/9 是否说明系统已经完美？

> 不是。它说明固定提交和模型下，三个固定任务各重复三次都通过独立验收。任务覆盖 Bug 修复、多文件开发和 falsy 配置回归，但样本仍小，模型别名和服务状态也会变化。它是当前版本的证据，不是对所有任务的保证。

### 23.15 为什么现在不用多 Agent 或复杂 RAG？

> 题目核心是把单 Agent 的上下文、工具、执行、回填、终止和错误处理做完整。多 Agent 会增加协调和评测变量，RAG 在当前少量人工确认记忆下收益有限。我优先保证闭环透明、可测试、可解释，后续只有真实失败数据证明需要时才扩展。

### 23.16 如果要进一步提升，你会做什么？

可以回答有明确边界的方向：

1. 把命令执行器放入低权限容器，提升真正隔离；
2. 增加上下文压缩，但保留工具调用成对消息的完整性；
3. 对更多语言和大型仓库扩展公开评测任务；
4. 用固定模型版本和多次重复计算更可靠的成功率、耗时和成本；
5. 增加“测试是否覆盖本次修改”的更精确检查，而不是只看检查命令退出码。

不要为了显得高级，声称已经实现这些尚未存在的功能。

---

## 24. 五分钟项目讲解稿

下面是一份可根据现场时间压缩的口头讲解。

### 第 1 分钟：目标与限制

> 这个项目是一个从零实现的 Coding Agent。它通过 DeepSeek 官方基础 API 使用原生 Tool Calling，但没有使用 Agent 框架。项目自己维护消息历史、解析模型输出、执行本地工具、回填结果，并处理预算、终止和错误。CLI 可以脱离 Web 和数据库独立运行。

### 第 2 分钟：核心循环

> 用户任务进入 `Agent.run` 后，程序先建立系统消息和当前上下文。每轮把消息历史和工具 schema 发给模型。模型如果返回工具调用，本地程序严格解析参数，由 ToolRegistry 经过权限策略执行文件或命令工具，再把真实结果作为 tool 消息发回模型；如果返回合法最终文本则结束。这个循环使模型能够根据真实工作区逐步行动，而不是一次猜答案。

### 第 3 分钟：工具与安全

> 当前有 8 个工具，包括目录、读取、搜索、创建目录、创建文件、精确替换、删除和命令。路径必须在工作区内，受保护文件和链接逃逸被拒绝。修改已有文件需要读取时的 SHA-256，避免覆盖并发变化。命令使用 argv 和 shell=False，按允许、确认、禁止分类，并清理敏感环境变量。三档权限不会绕过硬禁止。不过这是应用层策略，不宣传成操作系统沙箱。

### 第 4 分钟：可靠性和可观察性

> 运行同时受模型次数、工具次数、Token 和墙钟时间限制。短暂 API 错误可以退避重试，工具业务失败会结构化回填，让模型自我修正。完全重复调用只提示改变策略，硬预算负责兜底。Web 通过 RunManager 后台执行同一核心，支持取消、人工审批和 SSE 事件；安全 trace 记录流程事实但不保存密钥、完整源码和私有推理。

### 第 5 分钟：测试与评测

> 离线测试用 ScriptedAdapter 模拟固定模型决策，但执行真实搜索、读写和 pytest，因此不需要网络也能验证完整循环。正式 benchmark 每轮从干净模板开始，覆盖边界 Bug、多文件功能和配置回归，外部 verifier 对 Agent 不可见。当前归档版本在三个任务各三次中取得 9/9，但我把它限定为该固定样本和版本的实验结果，不夸大为所有任务都能成功。

---

## 25. 现场代码演示路线

如果面试官让打开代码，不要随机翻文件。按下面顺序演示。

### 25.1 第一屏：主循环

打开 [`Agent.run`](../src/coding_agent/agents/agent.py#L190)，依次指出：

1. 初始消息和状态；
2. `while True`；
3. 预算和取消检查；
4. `adapter.complete`；
5. finish reason 分支；
6. assistant 工具请求入历史；
7. 严格解析和 `registry.execute`；
8. tool 结果入历史；
9. `finish` 生成 `RunResult`。

### 25.2 第二屏：工具说明与执行

先打开 [`schemas.py`](../src/coding_agent/agents/tools/schemas.py)，说明这是给模型看的能力说明；再打开 [`ToolRegistry.execute`](../src/coding_agent/agents/tools/registry.py#L148)，说明这是本地调度边界。

### 25.3 第三屏：并发写保护

打开 [`read_file`](../src/coding_agent/agents/tools/filesystem.py#L128) 和 [`replace_text`](../src/coding_agent/agents/tools/filesystem.py#L255)，展示哈希如何从读取结果进入修改参数。

### 25.4 第四屏：命令策略

打开 [`classify_command`](../src/coding_agent/agents/security/command_policy.py#L227) 和 [`run_command`](../src/coding_agent/agents/tools/command.py#L127)，强调 argv、shell=False、确认、超时、环境清理。

### 25.5 第五屏：离线完整测试

打开 [`test_offline_loop.py`](../tests/integration/test_offline_loop.py)，展示假模型的 5 个固定响应和真实文件断言。这是“核心不是套壳”的直观证据。

### 25.6 第六屏：评测报告

打开 [`BENCHMARK_REPORT.md`](evaluation-results/benchmark-20260829T140452Z/BENCHMARK_REPORT.md)，说明模板复制、三类任务、3 次重复、外部验收和固定提交。

---

## 26. 新手实操练习

这些练习按难度递增。先自己回答或跟踪，再看源码。

### 练习 1：手画一次消息历史

任务：生成 `hello.py` 并运行。

要求写出每一步消息角色：

```text
system
user
assistant(tool_calls=list_files)
tool(list_files result)
assistant(tool_calls=write_file)
tool(write_file result)
assistant(tool_calls=run_command)
tool(run_command result)
assistant(final content)
```

检查点：每个 `tool` 是否有对应 `tool_call_id`？

### 练习 2：判断哪些错误应继续

分别判断：

1. `read_file` 文件不存在；
2. pytest 退出码 1；
3. API 返回 401；
4. API 暂时返回 503；
5. 模型用同一个 tool call ID 两次；
6. 用户点击停止。

参考：1、2 通常回填并继续；3 致命结束；4 在预算内重试；5 协议错误；6 协作式取消。

### 练习 3：跟踪离线测试

运行：

```powershell
python -m pytest tests/integration/test_offline_loop.py -q
```

然后在 `ScriptedAdapter.complete`、`Agent.run` 的模型调用处、`ToolRegistry.execute` 设置断点，观察 `messages` 每轮怎样增长。

### 练习 4：观察哈希冲突

1. 调用或单步执行 `read_file`，记录 SHA-256；
2. 在外部手工修改目标文件；
3. 使用旧哈希请求 `replace_text`；
4. 观察工具拒绝覆盖；
5. 重新读取后用新哈希修改。

理解目标：为什么“先读后改”仍需要防止读写之间的变化。

### 练习 5：画出权限判断

对以下操作分别判断三档模式结果：

- 读取普通源码；
- 创建普通 `.py` 文件；
- 删除普通文件；
- 运行固定 pytest；
- 运行任意 `python hello.py`；
- 写 `.env`；
- 执行危险 Git 历史操作。

最后对照 [`permission_policy.py`](../src/coding_agent/agents/security/permission_policy.py) 和 [`command_policy.py`](../src/coding_agent/agents/security/command_policy.py)。

### 练习 6：区分三种“成功”

给出以下场景并判断：

```text
模型说已完成；文件确实有修改；没有运行测试；外部 verifier 失败。
```

正确描述应是：模型运行以 `model_final` 结束，`change_check` 为 `needs_check`，外部验收失败，整体不能算端到端成功。

### 练习 7：解释一个真实评测 trial

从归档目录选一个 `trial.json`，找出：

- 任务名和第几次重复；
- Agent 终止原因；
- 模型和工具调用次数；
- Token 用量；
- 工作区修改了哪些文件；
- `change_check` 状态；
- verifier 结果；
- 是否存在状态不一致。

用自己的话写一段 200 字解释，不只抄字段名。

---

## 27. 调试时怎样快速定位问题

### 27.1 页面一直转圈

按顺序判断：

1. 后端进程是否仍存在；
2. Web 运行状态是 `running`、`waiting_approval` 还是 `cancelling`；
3. 是否有待人工确认；
4. 最新事件停在模型请求还是命令执行；
5. 单次 API timeout 和总墙钟预算是否生效；
6. 数据库运行记录是否已经终态但 SSE 没更新。

对应代码：[`run_manager.py`](../src/coding_agent/agents/runtime/run_manager.py)、[`approval_broker.py`](../src/coding_agent/agents/runtime/approval_broker.py)、[`event_buffer.py`](../src/coding_agent/agents/runtime/event_buffer.py)。

### 27.2 模型不断调用同一个工具

查看 trace 中：

- 工具名和参数是否完全相同；
- 结果是否也相同；
- 是否已经出现 `progress_warning`；
- 模型是否因输出截断没看到关键数据；
- 工具结果是否提供足够错误信息；
- 剩余工具和时间预算。

不要第一反应就增加更多功能，应先依据真实重复数据判断是提示词、结果信息还是任务本身导致。

### 27.3 模型说测试通过但实际失败

检查：

- 是否真的调用 `run_command`；
- 命令退出码是否为 0；
- 测试是否在正确 `cwd`；
- 修改后是否又发生文件变更，导致 `change_check=outdated`；
- 外部 verifier 检查的是不是更完整的要求。

### 27.4 文件修改总是失败

常见原因：

- `write_file` 目标已存在；
- `replace_text` 的 `old_text` 不存在或出现多次；
- `expected_sha256` 已过期；
- 路径命中受保护规则；
- 文件不是 UTF-8；
- 用户拒绝审批。

结构化工具错误码应该足以让模型区分这些情况。

### 27.5 命令需要确认

这通常不是卡死。检查运行状态是否为 `waiting_approval`，前端应在输入区域展示命令摘要和允许/拒绝操作。批准只对当前操作生效，不应静默提升整个会话权限。

### 27.6 API 请求失败

检查：

- 当前进程是否设置 `DEEPSEEK_API_KEY`；
- 模型 ID 和 base URL；
- 网络和账户余额；
- 异常属于短暂错误还是鉴权等致命错误；
- 重试次数和墙钟时间是否已耗尽。

不要把密钥打印到 trace、终端截图或提交历史中。

---

## 28. 设计取舍：为什么当前版本没有继续堆功能

### 28.1 没有多 Agent

单 Agent 已经需要处理完整消息协议、工具、预算、取消和验收。多 Agent 会增加角色通信、共享状态、冲突修改和预算分配问题。没有真实评测证明单 Agent 的主要失败来自“缺少多个角色”前，不应优先增加复杂度。

### 28.2 没有复杂 RAG

当前记忆数据量小，并且强调用户确认。直接按优先级加载更透明。只有记忆规模大到固定装载不足时，向量检索才有明确收益。

### 28.3 没有操作系统沙箱

系统级隔离需要容器、低权限用户、文件挂载策略和资源限制，跨 Windows 环境实现成本高。本版诚实采用应用层策略和人工确认，满足题目重点；部署时 Docker 容器可以进一步隔离服务，但 Agent 执行用户工作区时仍要清楚挂载和权限边界。

### 28.4 没有流式工具调用

流式需要拼接被拆分的工具名和 JSON arguments，并处理半截流、断线恢复和 UI 状态。非流式更容易确保每轮响应完整、自洽和可测试。

### 28.5 没有让模型自动写记忆

自动写入容易把临时错误、恶意仓库文本或模型猜测变成长期事实。当前由用户确认，牺牲一点自动化，换取可控性。

### 28.6 没有因为重复调用直接终止

重复是进度信号，不总是死循环。软提示配合四类硬预算，比单一启发式终止更稳妥。

---

## 29. 重要数据结构速查

### 29.1 `ToolCall`

代码：[`ToolCall`](../src/coding_agent/agents/contracts.py#L67)。

```text
id         厂商给出的调用 ID，用于匹配 tool 结果
name       工具名
arguments  原始 JSON 字符串
```

### 29.2 `AssistantMessage`

代码：[`AssistantMessage`](../src/coding_agent/agents/contracts.py#L90)。

```text
content            可见最终文本或工具回合附带文本
reasoning_content  厂商返回的推理字段，按协议用于后续请求
tool_calls         本轮一个或多个工具调用
```

### 29.3 `TokenUsage`

代码：[`TokenUsage`](../src/coding_agent/agents/contracts.py#L119)。

```text
prompt_tokens
completion_tokens
total_tokens
```

支持把每轮用量累计成整个运行用量。

### 29.4 `ModelCompletion`

代码：[`ModelCompletion`](../src/coding_agent/agents/contracts.py#L193)。

```text
finish_reason
assistant
usage
model
```

核心循环只依赖这个统一形式，不直接到处读取厂商响应对象。

### 29.5 `AgentContext`

代码：[`AgentContext`](../src/coding_agent/agents/context.py#L61)。

```text
prior_messages   运行开始时冻结的可见旧会话
memory           运行开始时冻结的用户确认记忆
```

### 29.6 `RunResult`

代码：[`RunResult`](../src/coding_agent/agents/contracts.py#L284)。

```text
status          终态大类
reason          具体终止原因
final_content   最终模型文本
messages        本次循环最终消息历史
usage           累计 Token
model_calls     模型调用次数
tool_calls      工具调用次数
change_check    修改后检查状态
verified        外部验收状态，普通运行通常 unknown
```

### 29.7 `RunSpec`

代码：[`RunSpec`](../src/coding_agent/agents/runtime/agent_runner.py)。

用于 Web 后台运行，保存一次任务的固定输入：运行 ID、工作区、任务、权限、历史和记忆快照。

---

## 30. 术语表

| 术语 | 简单解释 | 项目中的位置 |
| --- | --- | --- |
| LLM | 根据上下文生成下一步输出的大语言模型 | DeepSeek |
| Prompt | 发给模型的文字指令或数据 | system/user 消息 |
| Context | 本轮请求中模型能看到的全部消息与工具说明 | `messages + tools` |
| Tool Calling | 模型输出结构化的工具名和参数 | `ToolCall` |
| Agent Loop | 模型决定、工具执行、结果回填的反复过程 | `Agent.run` |
| Adapter | 把具体厂商 API 整理成核心统一形式 | `DeepSeekAdapter` |
| Schema | 描述工具参数形状的 JSON 说明 | `tools/schemas.py` |
| Registry | 从工具名找到真实函数并统一执行 | `ToolRegistry` |
| Snapshot | 运行开始时固定的一份历史、记忆或配置 | `AgentContext`、`RunSpec` |
| SHA-256 | 根据文件内容计算的固定长度摘要 | `read_file` / `replace_text` |
| Atomic write | 要么完整成功，要么不把半截内容作为新文件 | `Workspace.atomic_*` |
| Wall time | 从开始到当前现实经过的总时间 | `wall_time_seconds` |
| Retry | 短暂错误后在限制内再次请求 | `Agent._backoff` |
| Timeout | 单个操作允许等待的最长时间 | API 和命令参数 |
| Cancellation | 用户请求停止，循环在安全边界协作退出 | `RunManager` / `Agent` |
| SSE | 服务端向网页持续推送事件的连接 | `EventBuffer` 与 API |
| Verifier | Agent 工作区外检查最终代码的脚本 | `evaluation` |
| Idempotency | 重复提交同一请求时避免重复创建运行 | `run_service.py` 请求 ID |

---

## 31. 学习安排建议

### 第一天：理解闭环

1. 阅读第 0～7 章；
2. 手画消息历史；
3. 阅读 `test_offline_loop.py`；
4. 跟着断点观察 `messages`；
5. 能口述“模型不执行工具，本地程序执行工具”。

### 第二天：理解工具与安全

1. 阅读第 8～14 章；
2. 逐个查看 8 个 schema；
3. 跟踪 `read_file → replace_text`；
4. 对三档权限做表格；
5. 能诚实说明命令策略不是系统沙箱。

### 第三天：理解 Web、评测和面试表达

1. 阅读第 15～25 章；
2. 打开一次真实 trial 和报告；
3. 按五分钟讲解稿录一遍；
4. 随机回答第 23 章问题；
5. 按现场代码演示路线完整走一遍。

### 第四天：只练追问

让同学或老师连续追问“为什么”：

- 为什么历史由本地保存？
- 为什么不能信任模型最终文本？
- 为什么哈希变化要拒绝修改？
- 为什么工具失败还能继续？
- 为什么需要四类预算？
- 为什么当前不做多 Agent？

回答每个“为什么”时，都应该包含：当前实现、解决的问题、代价或边界、代码证据。

---

## 32. 最终自测清单

讲解前逐项确认。

### 核心原理

- [ ] 能画出“模型 → 工具 → 结果 → 模型”的循环；
- [ ] 能说出四种消息角色；
- [ ] 能解释 `stop` 和 `tool_calls`；
- [ ] 能说明工具调用只是意图，不是执行；
- [ ] 能指出 `Agent.run` 是主循环。

### 工具与安全

- [ ] 能说出当前 8 个工具；
- [ ] 能解释 schema、registry、真实函数三层；
- [ ] 能解释 SHA-256 防止覆盖并发变化；
- [ ] 能解释 `argv + shell=False`；
- [ ] 能区分 ask、agent、workspace_full；
- [ ] 能说明权限模式不会越过硬禁止；
- [ ] 能说明当前不是操作系统沙箱。

### 稳定性

- [ ] 能说出模型、工具、Token、墙钟四类预算；
- [ ] 能区分短暂 API 错误和致命错误；
- [ ] 能解释测试失败为何回填给模型；
- [ ] 能解释重复调用当前只提示不终止；
- [ ] 能解释取消如何维持工具消息完整。

### 上下文与记忆

- [ ] 能区分本次消息历史、旧会话、长期记忆；
- [ ] 能说明记忆必须由用户确认；
- [ ] 能说明当前没有向量 RAG；
- [ ] 能解释为什么运行开始时冻结快照。

### 评测

- [ ] 能区分模型完成、修改后检查和外部验收；
- [ ] 能解释每轮为何复制干净模板；
- [ ] 能说出三类评测任务；
- [ ] 能准确描述 9/9 的适用边界；
- [ ] 能指出归档报告和源码提交。

### 演示

- [ ] 能独立运行离线主循环测试；
- [ ] 能按照第 25 章顺序打开代码；
- [ ] 能在 5 分钟内完整介绍项目；
- [ ] 不展示 API key、数据库密码或真实 `.env`；
- [ ] 不声称尚未实现的多 Agent、RAG、系统沙箱或自动记忆。

---

## 33. 最后总结

这个项目最重要的价值不在页面数量，而在于它把一个 Coding Agent 的核心链路完整地写了出来：

```text
固定运行输入
  → 维护消息历史
  → 调用 DeepSeek
  → 解析工具请求
  → 本地安全执行
  → 回填真实结果
  → 根据新事实继续决策
  → 预算、错误或最终文本触发终止
  → 独立评测检查最终代码
```

学习时始终抓住三个判断：

1. **这一步是谁做的？** 模型决定，还是本地程序执行？
2. **这一步依据什么事实？** 模型猜测，还是工具真实结果？
3. **这一步怎样证明？** 最终文本、修改检查，还是外部 verifier？

能围绕这三个问题把代码讲清楚，就真正理解了这个项目，而不是只会运行它。
