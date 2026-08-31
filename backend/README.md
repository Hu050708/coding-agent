# Coding Agent 后端

后端包含 Agent 核心、DeepSeek 适配器、本地工具、安全策略、CLI、FastAPI、PostgreSQL 持久化和评测系统。Python 导入命名空间统一为 `coding_agent`。

CLI 与 Web 共用同一个 Agent 核心。CLI 可独立运行；Web 依赖 PostgreSQL。

## 目录

```text
src/coding_agent/
├─ agents/
│  ├─ agent.py              # 主循环、预算和终止
│  ├─ config.py             # 运行配置
│  ├─ contracts.py          # 模型、工具和结果合同
│  ├─ context.py            # 有界会话历史与记忆上下文
│  ├─ providers/deepseek.py # DeepSeek 请求与响应
│  ├─ tools/                # 八个本地工具
│  ├─ security/             # 工作区、权限和命令策略
│  ├─ runtime/              # Web 运行、审批、取消和事件
│  └─ diagnostics/          # 脱敏 JSONL trace
├─ router/                  # FastAPI 路由
├─ services/                # 应用用例
├─ repository/              # 数据访问与事务
├─ models/                  # SQLAlchemy 模型
├─ schemas/                 # API 数据结构
├─ database/                # 连接、迁移和启动恢复
├─ cli.py
└─ main.py
```

其他目录：

```text
alembic/       # 数据库迁移
evaluation/    # 可复现评测
tests/         # 离线、集成、Web 和持久化测试
examples/      # 演示任务
scripts/       # 演示脚本
docs/          # 设计和答辩文档
```

## 阅读顺序

1. `tests/integration/test_offline_loop.py`：假模型驱动真实搜索、读取、修改和测试。
2. `agents/config.py`、`agents/contracts.py`：运行预算和数据合同。
3. `agents/agent.py`：模型请求、工具执行、结果回填和终止。
4. `agents/providers/deepseek.py`：供应商请求与响应规范化。
5. `agents/tools/`：工具 schema、参数校验和实现。
6. `agents/security/`：路径、权限和命令策略。
7. `agents/context.py`：会话历史和记忆如何进入上下文。
8. `agents/runtime/`：Web 运行、审批、取消和事件。
9. `services/`、`repository/`、`models/`：应用服务和 PostgreSQL。

完整设计见 [docs/DESIGN.md](docs/DESIGN.md)。

## 环境

要求 Python 3.11 或 3.12。

首次创建环境：

```powershell
conda env create -f environment.yml
conda activate coding-agent
```

已有环境更新依赖：

```powershell
python -m pip install -e ".[dev,web]"
```

复制配置：

```powershell
Copy-Item .env.example .env
```

至少设置：

```dotenv
DEEPSEEK_API_KEY=你的密钥
CODING_AGENT_ALLOWED_ROOT=E:\code
CODING_AGENT_POSTGRES_PASSWORD=强密码
CODING_AGENT_DATABASE_URL=postgresql+psycopg://coding_agent:编码后的密码@127.0.0.1:5434/coding_agent
```

数据库密码写入 URL 时必须进行 URL 编码。真实 `.env` 不得提交。

## 启动 Web

先启动 PostgreSQL：

```powershell
docker compose --env-file .env -f deploy/compose.yml up -d
```

再启动 API：

```powershell
coding-agent-web
```

API 默认地址为 <http://127.0.0.1:8000>，文档位于 <http://127.0.0.1:8000/api/docs>。

前端在仓库的 `frontend/` 目录启动：

```powershell
npm ci
npm run dev
```

## 运行 CLI

CLI 只读取当前进程中的 `DEEPSEEK_API_KEY`，不读取 `backend/.env`。

```powershell
$env:DEEPSEEK_API_KEY="你的密钥"
coding-agent --workspace E:\path\to\project "修复问题并运行测试"
```

`--yes` 自动执行非禁止操作，但不能绕过命令 `DENY` 和工作区边界。

## 测试

```powershell
python -m pytest
python -m compileall -q src
python -m coding_agent --help
coding-agent-web --help
```

真实 API 冒烟测试默认跳过。明确允许消耗 API 额度时执行：

```powershell
$env:CODING_AGENT_RUN_LIVE="1"
python -m pytest tests/live/test_deepseek_smoke.py
```

## 评测

```powershell
python -m evaluation.run_benchmark --model deepseek-v4-flash --repeats 3
```

评测说明见 [evaluation/README.md](evaluation/README.md)，答辩提纲见 [docs/INTERVIEW_NOTES.md](docs/INTERVIEW_NOTES.md)。
