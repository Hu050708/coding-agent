# Docker 部署

Compose 启动三个服务：

- `frontend`：Nginx 提供 Vue 页面并转发 `/api`；
- `backend`：FastAPI、Coding Agent 和 Alembic；
- `postgres`：保存工作区、会话、运行、事件、审批和记忆。

宿主机只开放 `127.0.0.1:8080`。后端和 PostgreSQL 仅在 Compose 网络内通信。

## 1. 配置

在仓库根目录执行：

```powershell
Copy-Item .env.docker.example .env
```

填写以下变量：

```dotenv
DEEPSEEK_API_KEY=你的密钥
CODING_AGENT_POSTGRES_PASSWORD=至少32位且仅含字母数字下划线和连字符的密码
CODING_AGENT_WORKSPACE_PATH=E:/code
```

`CODING_AGENT_WORKSPACE_PATH` 必须是宿主机上已存在的目录：

- Windows：`E:/code`
- Linux：`/home/user/code`
- macOS：`/Users/user/code`

Docker Desktop 首次挂载目录时可能要求文件共享权限。

可选变量：

```dotenv
CODING_AGENT_HTTP_PORT=8080
CODING_AGENT_UID=1000
CODING_AGENT_GID=1000
CODING_AGENT_BASE_URL=https://api.deepseek.com
CODING_AGENT_MODEL=deepseek-v4-flash
```

Linux 可将 UID、GID 改为当前用户的 `id -u`、`id -g`。

## 2. 启动

```powershell
docker compose up -d --build
docker compose ps
```

三个服务均显示 `healthy` 后访问：

- Web：<http://127.0.0.1:8080/>
- API 文档：<http://127.0.0.1:8080/api/docs>
- 健康检查：<http://127.0.0.1:8080/api/v1/health>

后端在接收请求前执行 Alembic 迁移。数据库不可用或迁移失败时，后端不会进入就绪状态。

## 3. 日志

```powershell
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f postgres
```

查看解析后的 Compose 配置时不要共享输出，其中可能包含展开后的密钥和密码：

```powershell
docker compose config
```

## 4. 停止与更新

停止服务并保留数据：

```powershell
docker compose down
```

代码更新后重新构建：

```powershell
docker compose up -d --build
```

不要在普通停止流程中使用 `docker compose down -v`。`-v` 会删除 PostgreSQL 和运行诊断卷。

## 5. 数据位置

| 数据 | 保存位置 | 重建容器后 |
|---|---|---|
| 会话、消息、运行、事件、审批、记忆 | `coding_agent_postgres_data` | 保留 |
| 私有运行诊断 | `coding_agent_runtime_data` | 保留 |
| Agent 修改的项目文件 | `CODING_AGENT_WORKSPACE_PATH` | 保留 |
| 前端静态文件 | frontend 镜像 | 重新构建 |

## 6. 远程服务器

服务只监听远程主机的回环地址。通过 SSH 隧道访问：

```powershell
ssh -L 8080:127.0.0.1:8080 user@server
```

随后在本机打开 <http://127.0.0.1:8080/>。不要修改端口绑定将服务直接暴露到公网。

## 7. 排错

### 后端未就绪

```powershell
docker compose logs backend
docker compose logs postgres
```

检查：

- DeepSeek API Key 是否填写；
- 数据库密码是否只含允许字符；
- PostgreSQL 健康检查是否通过；
- Alembic 迁移是否成功。

### 工作区为空或不可写

确认宿主机目录存在，并检查 Docker Desktop 文件共享权限。Linux 同时检查 UID、GID 与目录权限。

### 端口被占用

修改根目录 `.env`：

```dotenv
CODING_AGENT_HTTP_PORT=8081
```

重新启动后访问 `http://127.0.0.1:8081/`。

### 修改环境变量后未生效

重新创建容器：

```powershell
docker compose up -d --build --force-recreate
```
