# Coding Agent

Coding Agent 是一个本地编程智能体，提供命令行和 Web 两种入口。模型负责选择下一步操作；项目负责维护上下文、解析工具调用、校验权限、执行本地工具并控制终止。

默认使用 DeepSeek 官方 Chat Completions API 和 `deepseek-v4-flash`。运行时不依赖 Agent 框架、Agent SDK、MCP、服务端文件工具或远程代码执行。

## 主要能力

- 显式 Agent 循环：完整处理模型回复、工具调用、工具结果和终止状态。
- 八个本地工具：目录浏览、文件读取、文本搜索、目录创建、文件创建、精确替换、文件删除和命令执行。
- 工作区边界：拒绝绝对路径、父目录穿越、受保护文件和越界链接。
- 文件并发保护：修改和删除必须携带最近读取结果的 SHA-256。
- 三档权限：运行开始时冻结，由后端执行。
- Web 工作台：持久会话、审批、取消、运行时间线和 SSE 断线重放。
- 工作区记忆：只由用户确认写入，每次运行使用创建时冻结的快照。
- 独立评测：Agent 只操作候选副本，工作区外 verifier 判断结果。

## 架构

```text
CLI ──────────────────────────────────────┐
                                          v
Vue -> FastAPI -> 应用服务 -> RunManager -> Agent -> DeepSeek
                    |              |          |
                    v              v          `-> 本地工具与安全策略
                PostgreSQL      SSE 事件
```

后端统一使用 `coding_agent` 命名空间：

```text
backend/src/coding_agent/
├─ agents/          # Agent 核心、模型适配器、工具、安全策略和运行管理
├─ router/          # FastAPI 路由
├─ services/        # 工作区、会话、运行、记忆和评测用例
├─ repository/      # PostgreSQL 事务与查询
├─ models/          # SQLAlchemy 表模型
├─ schemas/         # API 请求与响应
├─ database/        # 连接、迁移和启动恢复
├─ cli.py           # CLI 入口
└─ main.py          # Web 应用入口
```

项目根目录：

```text
.
├─ backend/
├─ frontend/
├─ compose.yml
├─ DOCKER_DEPLOY.md
└─ README.md
```

## Docker 启动

只需安装 Docker Desktop 或 Docker Engine。

```powershell
Copy-Item .env.docker.example .env
```

编辑根目录 `.env`，至少填写：

```dotenv
DEEPSEEK_API_KEY=你的密钥
CODING_AGENT_POSTGRES_PASSWORD=至少32位且仅含字母数字下划线和连字符的密码
CODING_AGENT_WORKSPACE_PATH=E:/code
```

启动服务：

```powershell
docker compose up -d --build
docker compose ps
```

访问地址：

- Web：<http://127.0.0.1:8080/>
- API 文档：<http://127.0.0.1:8080/api/docs>
- 健康检查：<http://127.0.0.1:8080/api/v1/health>

部署和排错见 [DOCKER_DEPLOY.md](DOCKER_DEPLOY.md)。

## 本地开发

### 后端

```powershell
Set-Location backend
conda env create -f environment.yml
conda activate coding-agent
Copy-Item .env.example .env
```

编辑 `backend/.env`，配置 DeepSeek、允许的工作区根目录和 PostgreSQL。然后启动数据库和 API：

```powershell
docker compose --env-file .env -f deploy/compose.yml up -d
coding-agent-web
```

### 前端

```powershell
Set-Location frontend
npm ci
npm run dev
```

开发地址为 <http://127.0.0.1:5173/>。

### CLI

CLI 不依赖 PostgreSQL、FastAPI 或前端，也不会读取 `backend/.env`。密钥必须来自当前进程环境。

```powershell
$env:DEEPSEEK_API_KEY="你的密钥"
coding-agent --workspace E:\path\to\project "修复问题，补充回归测试并运行测试"
```

## 权限模式

| 模式 | 文件修改 | 文件删除 | 命令 |
|---|---|---|---|
| `ask` | 逐次确认 | 逐次确认 | 逐次确认 |
| `agent` | 工作区内自动执行 | 需要确认 | 安全检查自动执行，其他命令按策略确认 |
| `workspace_full` | 工作区内自动执行 | 工作区内自动执行 | 除硬拒绝命令外自动执行 |

所有模式都遵守工作区边界、受保护路径、工具参数合同和命令 `DENY` 规则。

## 会话与记忆

PostgreSQL 保存工作区、会话、可见消息、运行、事件、审批和记忆。隐藏推理、原始供应商响应和完整工具输出不写入数据库。

运行创建事务同时完成以下操作：

1. 创建运行和当前用户消息；
2. 截取有界的可见会话历史；
3. 冻结本次使用的记忆快照；
4. 固定权限模式和模型。

记忆按工作区隔离，最多装载 32 条，正文合计不超过 32,000 字符。模型没有写记忆工具。

## 评测

在 `backend/` 目录运行三类任务、每类三次：

```powershell
$env:DEEPSEEK_API_KEY="你的密钥"
python -m evaluation.run_benchmark --model deepseek-v4-flash --repeats 3
```

每轮都从新的任务副本开始，并由 Agent 工作区外的 verifier 验收。评测设计见 [backend/evaluation/README.md](backend/evaluation/README.md)。

仓库保存了一份固定结果：提交 `536c94158978afc68ab0a273635a94807bba5135` 在 2026-08-29 完成 9 次试验，独立验收和 Agent 端到端结果均为 9/9。该结果只对应报告记录的提交、模型和任务集。

- [中文报告](backend/docs/evaluation-results/benchmark-20260829T140452Z/BENCHMARK_REPORT.md)
- [机器可读汇总](backend/docs/evaluation-results/benchmark-20260829T140452Z/summary.json)

## 验证

后端：

```powershell
Set-Location backend
conda activate coding-agent
python -m pytest
python -m compileall -q src
python -m coding_agent --help
coding-agent-web --help
```

前端：

```powershell
Set-Location frontend
npm test
npm run typecheck
npm run build
```

## 安全边界

- 文件工具只处理当前工作区，但获准执行的程序仍拥有当前运行账户的权限。
- `shell=False`、命令分类和环境变量清理不能替代操作系统沙箱。
- 任务、源码片段和工具结果会发送到 DeepSeek，不应处理未经授权的敏感代码。
- Web 只用于本机或 SSH 隧道访问，不应直接暴露到局域网或公网。
- API Key、数据库密码、`.env`、运行临时目录和视频不得提交到仓库。

## 文档

- [后端开发与源码入口](backend/README.md)
- [实现设计](backend/docs/DESIGN.md)
- [面试答辩要点](backend/docs/INTERVIEW_NOTES.md)
- [两分钟视频方案](backend/docs/VIDEO_PLAN.md)
- [Docker 部署](DOCKER_DEPLOY.md)
- [评测说明](backend/evaluation/README.md)

## 开发声明

开发过程中使用 Codex/ChatGPT 辅助需求分析、实现和审查；作者负责设计决策、代码验证和最终提交。运行时的 Agent 核心由本项目实现。
