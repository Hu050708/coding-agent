# ClearLoop

ClearLoop 是一个从零实现的轻量编程智能体，也是一个仅供本机使用的可视化执行控制台。
模型负责选择工具，本项目自己维护消息历史、解析 tool calls、校验参数、执行本地工具、
处理审批与取消，并根据预算和协议状态决定循环何时结束。

默认通过 DeepSeek 官方 Chat Completions API 使用 `deepseek-v4-flash`。运行时不依赖现成
Agent 框架、Agent SDK、MCP、远程代码执行或远程文件工具。

## 目录

根目录只保留两个业务目录：

```text
agent_project/
├─ backend/                 # Python、FastAPI、Agent 核心、SQLite 记忆、测试与文档
├─ frontend/                # Vue 3、TypeScript、Vite 本机控制台
├─ README.md
└─ .gitignore
```

后端只有一个 Python 导入命名空间 `clearloop`：

```text
FastAPI / CLI
  ├─ runs       运行、SSE、审批、取消与容量管理
  ├─ memory     工作区记忆、检索、SQLite 与提示构造
  └─ core       Agent 状态机、完整历史、预算与终止
       ├─ providers    DeepSeek 协议适配
       ├─ tools        文件与命令工具
       ├─ security     工作区和命令边界
       └─ diagnostics  allowlist JSONL 轨迹
```

前端按 `app / features / shared` 分层，运行控制与项目记忆分别位于独立 feature 中，
不把 API、状态和页面样式堆在单个组件里。

## 环境安装

要求 Python 3.11、Conda、Node.js 22 和 npm。已有环境时，在 PowerShell 中执行：

```powershell
Set-Location E:\code\agent_project\backend
conda env update -n clearloop-agent -f environment.yml
conda activate clearloop-agent
python -m pip install -e ".[dev,web]"

Set-Location E:\code\agent_project\frontend
npm ci
```

首次创建环境可将 `conda env update` 换成：

```powershell
conda env create -f environment.yml
```

后端从 `backend/.env` 读取本机配置。参考 `backend/.env.example`，至少提供：

```dotenv
DEEPSEEK_API_KEY=replace-with-your-own-key
CLEARLOOP_ALLOWED_ROOT=E:\code
```

`CLEARLOOP_ALLOWED_ROOT` 必须是已存在的绝对目录，WebUI 只能选择它下面的工作区。不要把
真实密钥写进截图、视频、终端命令或公开文件。

## 启动 WebUI

使用两个终端。

终端 1：

```powershell
Set-Location E:\code\agent_project\backend
conda activate clearloop-agent
clearloop-web
```

终端 2：

```powershell
Set-Location E:\code\agent_project\frontend
npm run dev
```

浏览器打开 <http://127.0.0.1:5173/>。FastAPI 文档位于
<http://127.0.0.1:8000/api/docs>。结束时在两个终端分别按 `Ctrl+C`。

后端和前端都只绑定 `127.0.0.1`。如果修改 `CLEARLOOP_WEB_PORT`，还要同步修改
`frontend/vite.config.ts` 的代理目标。

## 项目记忆

第一版记忆遵循四条明确规则：

- 只在同一个经过规范化校验的工作区内共享；
- 新任务默认读取一次已启用记忆，运行期间使用不可变快照；
- 只有用户在界面中确认后才写入，不允许模型自行保存；
- 后端重启后仍保留，存储故障只会让本次运行降级为“无记忆”，不会阻止 Agent 执行。

同一工作区有任务运行时，记忆管理保持只读；记忆写操作进行时也不会启动该工作区的新任务。
这两个方向由后端原子互斥，避免运行中的代码通过本机 API 绕过确认流程。

记忆支持偏好、事实、决策和备注，可编辑、置顶、停用、删除或按工作区清空。运行结果的
“保存为项目记忆”会先打开可编辑确认框，不会自动保存完整回复、推理、工具输出、源码或任务。

SQLite 默认位于 `%LOCALAPPDATA%\ClearLoop\clearloop.db`，不放在 Agent 可操作的工作区内；
可用 `CLEARLOOP_DATA_DIR` 指定其他本机绝对目录，但必须位于
`CLEARLOOP_ALLOWED_ROOT` 之外。提供给模型的记忆被标记为不可信参考，
不能覆盖当前任务、安全策略、审批、预算或工作区边界。

## CLI

安装后可在任意目录运行：

```powershell
clearloop --workspace E:\path\to\project "修复日期边界问题，补回归测试并运行测试"
```

CLI 与真实 demo 只读取当前终端进程中的 `DEEPSEEK_API_KEY`，不会读取
`backend/.env`；`.env` 是 Web 服务的本机配置入口。

默认逐条确认非白名单命令。`--yes` 只能批准策略判定为 `CONFIRM` 的命令，不能绕过
`DENY`。使用 `clearloop --help` 查看模型、预算和运行选项。

## 验证

后端：

```powershell
Set-Location E:\code\agent_project\backend
conda activate clearloop-agent
python -m pytest
python -m compileall -q src
python -m clearloop --help
clearloop-web --help
```

前端：

```powershell
Set-Location E:\code\agent_project\frontend
npm test
npm run typecheck
npm run build
```

## 安全边界

工作区路径校验、受保护文件、命令分类、环境变量清理、确认审批和本机绑定能降低风险，
但它们不是操作系统沙箱。被批准的 Python 或其他程序仍拥有当前 Windows 用户的权限。
发送给模型的任务、源码片段和工具结果会离开本机并到达 DeepSeek，不应处理未获授权的
敏感代码。

WebUI 不应通过端口转发、反向代理或修改监听地址暴露到局域网或公网。API 和 SSE 不公开
模型推理、完整工具输出或记忆内容；本机用户仍需妥善保护 `backend/.env`、记忆数据库和
诊断轨迹。

完整设计见 [backend/docs/DESIGN.md](backend/docs/DESIGN.md)，AI 使用声明见
[backend/AI_USAGE.md](backend/AI_USAGE.md)。
