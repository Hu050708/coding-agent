# Coding Agent

Coding Agent 是一个从零实现的轻量编程智能体，以及一个仅供本机浏览器访问的
FastAPI + Vue 工作台。模型负责选择工具；本项目自己维护上下文、解析 tool calls、
校验参数、执行本地文件/命令工具、处理审批和取消，并根据预算与协议状态终止循环。
内置目录浏览与创建、文件读取/搜索/创建/替换/删除和命令执行八个工具；完全相同的工具交换从
第三次起会收到调整策略提示，但不会被误判为任务失败或提前终止。

默认通过 DeepSeek 官方 Chat Completions API 使用 `deepseek-v4-flash`。运行时不依赖
现成 Coding Agent、Agent 框架、Agent SDK、MCP、远程代码执行或远程文件工具。

## 目录与架构

```text
coding-agent/
├─ backend/                 # Python、Agent 核心、FastAPI、PostgreSQL、测试与文档
├─ frontend/                # Vue 3、TypeScript、Vite、Pinia、Vue Router
├─ README.md
└─ .gitignore
```

后端只有一个 Python 导入命名空间 `coding_agent`，主要边界如下：

```text
CLI ────────────────────────────────┐
                                    v
FastAPI -> services -> runs -> Agent core -> DeepSeek client
              |             |          |
              v             v          `-> local tools + security policy
          data          safe SSE
              |
              `-> PostgreSQL: workspace / conversation / run / message /
                              event / approval / memory
```

CLI 直接装配同一个 Agent core，不依赖 Web、Docker 或数据库。Web 是外层编排：工作区
选择、会话和可见消息、运行状态、安全事件、审批与工作区记忆由 PostgreSQL 持久化；
活动执行仍由本机 `RunManager` 驱动。数据库只保存可见 user/assistant 消息和白名单事件，
不保存隐藏推理、原始提供方响应或完整工具输出。

前端按 `app / features / shared` 分层，workspace、conversation、chat、run、permission、
memory 各自维护 API、状态和组件，路由只使用数据库 ID，不在 URL 中暴露本机路径。

## 安装

要求 Python 3.11、Conda、Docker Desktop、Node.js 22 和 npm。在 PowerShell 中执行：

```powershell
Set-Location E:\code\coding-agent\backend
conda env create -f environment.yml
conda activate coding-agent
python -m pip install -e ".[dev,web]"

Set-Location E:\code\coding-agent\frontend
npm ci
```

环境已经存在时，将 `conda env create` 换成：

```powershell
conda env update -n coding-agent -f environment.yml
```

## 本机配置

Web 从未入库的 `backend/.env` 读取配置。以 `backend/.env.example` 为模板，至少填写：

```dotenv
DEEPSEEK_API_KEY=replace-with-your-own-key
CODING_AGENT_ALLOWED_ROOT=E:\code
CODING_AGENT_POSTGRES_PASSWORD=replace-with-a-strong-local-password
CODING_AGENT_DATABASE_URL=postgresql+psycopg://coding_agent:replace-with-a-strong-local-password@127.0.0.1:5434/coding_agent
```

数据库密码出现在 URL 中时要进行 URL 编码。`CODING_AGENT_ALLOWED_ROOT` 必须是已存在的
绝对目录；Web 的目录浏览器只能注册它下面的工作区。不要把真实密钥或密码写入仓库、
终端录屏、截图、提交用 README 或视频。

## 启动 WebUI

按“PostgreSQL → 后端 → 前端”的顺序使用三个终端。

终端 1，启动本项目独立数据库：

```powershell
Set-Location E:\code\coding-agent\backend
docker compose --env-file .env -f deploy/compose.yml up -d
```

该 Compose 只创建 `coding-agent-postgres`，使用独立卷
`coding_agent_postgres_data`，并将 PostgreSQL 绑定到 `127.0.0.1:5434`。它不会复用或
修改本机其他项目的容器和数据卷。

终端 2，启动后端：

```powershell
Set-Location E:\code\coding-agent\backend
conda activate coding-agent
coding-agent-web
```

后端启动时自动执行 Alembic 迁移。Web 强制使用 PostgreSQL；配置缺失、数据库不可达或
迁移失败都会明确阻止启动，不会静默退回 SQLite 或内存存储。

终端 3，启动前端：

```powershell
Set-Location E:\code\coding-agent\frontend
npm run dev
```

浏览器打开 <http://127.0.0.1:5173/>；FastAPI 文档位于
<http://127.0.0.1:8000/api/docs>。前后端和 PostgreSQL 都只绑定 loopback。

进入页面后，先从受限目录浏览器选择工作区，再创建会话并发送任务。同一工作区同一时刻
最多有一个活动运行；不同工作区可以并行。刷新或重连时，SSE 使用 PostgreSQL 中的安全
事件和 `Last-Event-ID` 续播；服务重启不会恢复进程中的执行，而会把未完成运行标记为
`interrupted` 并留下可重放事件。

## 三档运行权限

权限在每次运行创建时冻结，并由后端执行，不是前端标签：

- `ask`（请求批准）：读取自动执行，修改文件和运行命令前逐次询问；
- `agent`（帮我批准）：常规工作区修改和检查自动执行，删除文件与风险命令仍需询问；
- `workspace_full`（工作区完全访问）：自动执行工作区内所有非禁止操作。

所有模式都不能越出当前工作区，也不能绕过命令策略中的 `DENY`。

## 会话与工作区记忆

PostgreSQL 保存工作区、会话、可见消息、运行、可重放事件、审批和记忆。会话历史与工作区
记忆是两类数据：历史按会话回放；记忆只在同一工作区共享，且必须由用户在界面中明确
新增或确认，模型没有写记忆工具。

每次运行在创建事务中冻结一次实际送给模型的记忆集合：最多 32 条、正文合计不超过
32000 字符。运行期间不再查询新记忆。同一工作区有活动运行时，记忆新增、编辑、删除和
清空都会被后端拒绝，避免运行中的代码绕过确认。当前版本不做 embedding、pgvector 检索、
跨工作区画像或模型自动记忆。

## CLI

CLI 与 Web 相互独立，不需要启动 Docker、PostgreSQL、FastAPI 或前端：

```powershell
conda activate coding-agent
coding-agent --workspace E:\path\to\project "修复日期边界问题，补回归测试并运行测试"
```

CLI 只读取当前终端进程中的 `DEEPSEEK_API_KEY`，不会读取 `backend/.env`。默认逐条确认
非白名单命令；`--yes` 只能批准策略判定为 `CONFIRM` 的命令，不能绕过 `DENY`。

## 可复现 Agent 评测

项目内置 Bug 修复、多文件功能和配置回归三类合成任务。每次试验都会复制全新工作区，
运行同一个 Agent CLI，再由工作区外 verifier 验收；模型最终回答不作为成功依据。

```powershell
Set-Location E:\code\coding-agent\backend
python -m evaluation.run_benchmark --model deepseek-v4-flash --repeats 3
```

系统会生成逐轮 JSON、汇总 JSON 和中文 Markdown 报告，包含调用次数、Token、耗时、
工具失败、文件变化、终止原因和独立验收结果。详细说明见
[`backend/evaluation/README.md`](backend/evaluation/README.md)。

## 验证

后端：

```powershell
Set-Location E:\code\coding-agent\backend
conda activate coding-agent
python -m pytest
python -m compileall -q src
python -m coding_agent --help
coding-agent-web --help
```

前端：

```powershell
Set-Location E:\code\coding-agent\frontend
npm test
npm run typecheck
npm run build
```

## 安全与题目边界

工作区路径校验、受保护文件、权限模式、命令分类、敏感环境变量清理、审批和本机绑定能
降低风险，但它们不是操作系统沙箱。数据库容器只承载 PostgreSQL，也不是 Agent 执行
沙箱。被批准的 Python 或其他程序仍拥有当前 Windows 用户的权限，可能访问工作区外资源。

发送给模型的任务、源码片段和工具结果会离开本机并到达 DeepSeek，不应处理未获授权的
敏感代码。Web 不应通过端口转发、反向代理或修改监听地址暴露到局域网或公网。

本项目只使用官方 API 客户端完成 HTTP/数据对象适配；历史、上下文、工具 schema、本地执行、
模型响应解析、循环终止和错误处理均由项目实现。未使用现成 Agent、Agent 框架/SDK、Files
API、Code Interpreter 或服务端托管代码/文件工具。完整设计见
[backend/docs/DESIGN.md](backend/docs/DESIGN.md)，AI 使用声明见
[backend/AI_USAGE.md](backend/AI_USAGE.md)。
