# Coding Agent 后端

后端包含自主实现的编程智能体循环、DeepSeek 客户端、本地工具和权限、FastAPI
接口、业务服务、PostgreSQL 数据读写、运行管理、测试、评测任务及提交文档。
项目统一使用 `coding_agent` 导入命名空间。

CLI 和 Web 服务共享同一核心，但外层依赖不同。CLI 不需要 FastAPI、Docker 或
数据库；Web 服务使用专用 PostgreSQL 数据库，数据库缺失、不可用或无法迁移时
会明确启动失败。

## 新手阅读路线

如果你刚开始接触 Agent，不建议一上来遍历所有文件。先记住一条主线：用户提出任务，
模型决定是回复还是调用工具，工具返回结果，模型根据结果继续判断，直到生成最终答案。
本项目的核心调用链如下：

```text
CLI / Web 请求
    → 构建上下文
    → Agent 循环
    → DeepSeek 模型
    → 工具注册表
    → 文件、搜索或命令工具
    → 工具结果返回 Agent
    → 最终答案
```

建议按以下顺序阅读：

1. **先看可运行的完整示例**：阅读
   `tests/integration/test_offline_loop.py`。这个测试用假的模型响应驱动真实的搜索、读取、
   编辑和测试流程，不需要 API 密钥，最容易看清 Agent 的一次完整工作过程。
2. **认识配置和输入输出数据**：先阅读 `agents/config.py` 中的 `AgentConfig`，再阅读
   `agents/contracts.py` 中的 `ToolCall`、`ModelCompletion` 和 `RunResult`。前者规定一次
   Agent 运行的资源与上下文边界，后者定义模型、工具和 Agent 之间传递的数据。
3. **理解核心循环**：阅读 `agents/agent.py` 的 `Agent.run()`。可以按步骤关注：请求模型、
   解析工具调用、执行工具、把结果加入历史、检查终止条件。这里是整个项目最重要的文件。
4. **理解模型如何接入**：阅读 `agents/providers/deepseek.py`，看 DeepSeek 返回值如何被
   规范化为 `ModelCompletion`。模型供应商的细节被限制在这一层，不会渗透到核心循环。
5. **理解工具系统**：先看 `agents/tools/contracts.py` 和 `agents/tools/registry.py`，再看
   `filesystem.py`、`search.py`、`command.py`。前两个文件定义并调度工具，后三个文件实现
   具体能力。
6. **理解安全边界**：依次阅读 `agents/security/workspace.py`、
   `workspace_policy.py`、`permission_policy.py` 和 `command_policy.py`，了解路径为何不能
   越出工作区、不同权限模式如何决策，以及哪些命令始终禁止执行。
7. **理解上下文和记忆**：阅读 `agents/context.py` 与 `agents/memory/`。这里负责把会话历史、
   当前任务和经用户确认的记忆整理成提供给模型的上下文。
8. **最后看两个入口**：CLI 路线从 `cli.py` 的 `run_cli()` 开始；Web 路线从 `main.py` 的
   `create_app()` 开始，再沿 `router/` → `services/` → `repository/` 阅读。接口数据格式在
   `schemas/`，数据库表在 `models/`，连接和迁移在 `database/`。
   前四步掌握之前，可以暂时跳过 Web、数据库迁移和 SSE 事件重放细节。

每读完一层，建议马上查看同名测试目录。例如读完 `agents/tools/` 后查看 `tests/tools/`，
读完安全策略后查看 `tests/security/`。测试中的输入和断言通常比抽象接口更容易帮助新手
确认“这段代码究竟保证了什么”。更完整的架构说明见 `docs/DESIGN.md`，常见设计取舍见
`docs/INTERVIEW_NOTES.md`。

## 环境配置

1. 请在本目录中运行这三个 Python 命令，创建需要的conda环境，下载项目依赖的包：

```powershell
conda env create -f environment.yml
conda activate coding-agent
python -m pip install -e ".[dev,web]"
```

2. 请根据 `.env.example` 创建不纳入版本控制的 `.env`。其中必须包含
DeepSeek 密钥、允许的工作区根目录、高强度本地数据库密码，以及仅使用回环地址的
`postgresql+psycopg` URL。切勿提交 `.env`，也不要在日志、截图或视频中展示其值。

## 两种交互方式

### 命令行界面（cli）

命令行智能体不依赖数据库：

```powershell
coding-agent --workspace E:\code\your-project "请理解一下当前项目"
```

它只从当前进程环境中读取 `DEEPSEEK_API_KEY`，不会加载 Web 服务使用的 `.env` 文件。

### Web 服务

需要交付给其他机器时，推荐使用仓库根目录的三容器方案，参见
[`../DOCKER_DEPLOY.md`](../DOCKER_DEPLOY.md)。以下步骤保留为源码开发方式。

请按以下顺序启动各组件。

1. 创建专用 PostgreSQL 服务：

```powershell
docker compose --env-file .env -f deploy/compose.yml up -d
```

该 Compose 项目只会创建容器 `coding-agent-postgres`、命名卷
`coding_agent_postgres_data`、数据库和用户 `coding_agent`，并仅绑定回环地址
`127.0.0.1:5434`。

2. 仅监听回环地址的 API：

```powershell
conda activate coding-agent
coding-agent-web
```

API 默认地址为 `http://127.0.0.1:8000`，OpenAPI 文档位于 `/api/docs`。启动过程会
应用 Alembic 迁移、检查数据库，并将重启前仍活动的运行标记为 `interrupted`，同时
写入一条可重放事件。

3. 进入前端路径 `../frontend`，执行 `npm run dev` 启动 Vue 前端，然后访问
`http://127.0.0.1:5173/`。

## 权限模式

服务器会为每次运行冻结一种权限模式：

- `ask`：读取操作直接执行；文件变更和命令每次都需要审批；
- `agent`：工作区变更和常规检查直接执行；风险命令需要审批；
- `workspace_full`：工作区内所有未被禁止的操作均自动执行。

三种模式都遵守相同的工作区边界和不可绕过的命令禁止规则。

## 会话历史与记忆

会话消息和工作区记忆彼此独立。运行开始前，应用会原子创建运行和用户消息，截取
有界的可见历史，并冻结实际提供给模型的记忆集合。记忆快照最多包含 32 条记录，
正文总计不超过 32,000 个字符。模型不能写入记忆；用户必须通过明确的 API/UI 操作
创建或确认记忆。

记忆变更会锁定工作区；工作区存在活动运行时，记忆变更会被拒绝。当前版本不包含
嵌入、向量检索、跨工作区画像或由模型自动写入的记忆。

`CODING_AGENT_DATA_DIR` 现在只存放私有诊断跟踪，默认路径为
`%LOCALAPPDATA%\Coding Agent`，且必须位于 `CODING_AGENT_ALLOWED_ROOT` 之外；
PostgreSQL 是 Web 服务的持久化数据存储。

## 验证

```powershell
python -m pytest
python -m compileall -q src
python -m coding_agent --help
coding-agent-web --help
```

使用以下命令启动独立演示试验：找到项目里的bug并进行修改，使用tmp/demo-runs项目做测试

```powershell
python scripts/run_demo_trial.py
```

运行三类任务、每类三次的可复现评测：

```powershell
python -m evaluation.run_benchmark --model deepseek-v4-flash --repeats 3
```

每轮都从全新任务副本开始，并由 Agent 工作区外的 verifier 判定结果。结构化结果和中文
报告写入 `tmp/benchmark-runs/`；任务设计、失败分类和报告字段见
[`evaluation/README.md`](evaluation/README.md)。
