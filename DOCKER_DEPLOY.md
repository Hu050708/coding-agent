# Docker 三容器部署

- `frontend`：Nginx 提供 Vue 静态页面，并把 `/api` 转发给后端；
- `backend`：运行 FastAPI、Coding Agent 和 Alembic 迁移；
- `postgres`：保存工作区、会话、运行事件、审批和记忆。

后端和 PostgreSQL 不开放宿主机端口。唯一入口为
`http://127.0.0.1:8080`，适合本机演示或通过 SSH 隧道访问远程服务器。

## 1. 准备环境变量

在仓库根目录执行：

```powershell
Copy-Item .env.docker.example .env
```

如果已经按旧命令创建了 `.env.docker`，可以直接复制，不需要重新填写：

```powershell
Copy-Item .env.docker .env
```

编辑仓库根目录的 `.env`，至少设置：

```dotenv
DEEPSEEK_API_KEY=实际密钥
CODING_AGENT_POSTGRES_PASSWORD=数据库密码
CODING_AGENT_WORKSPACE_PATH=E:/code
```

数据库密码只能使用字母、数字、下划线和连字符，因为同一个值会写入 PostgreSQL 配置和
数据库连接 URL。不要提交 `.env`。

工作区路径必须是宿主机上已经存在的目录：

- Windows Docker Desktop：`E:/code`
- Linux：`/home/user/code`
- macOS：`/Users/user/code`

Docker Desktop 首次挂载该路径时可能要求文件共享权限。后端容器只能把这个目录下的路径
注册为工作区。

## 2. 构建并启动

```powershell
docker compose up -d --build
docker compose ps
```

三个服务均显示 `healthy` 后访问：

- Web：<http://127.0.0.1:8080/>
- API 文档：<http://127.0.0.1:8080/api/docs>
- 健康检查：<http://127.0.0.1:8080/api/v1/health>

后端会在接收请求前自动执行 Alembic `upgrade head`。数据库不可用或迁移失败时，后端会
保持未就绪，不会回退到 SQLite 或内存数据库。

## 3. 查看日志

```powershell
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f postgres
```

检查解析后的 Compose 配置时不要把输出发送给他人，因为环境变量展开后可能包含密钥：

```powershell
docker compose config
```

## 4. 停止和更新

停止容器但保留数据库、运行诊断和工作区文件：

```powershell
docker compose down
```

代码更新后重新构建：

```powershell
docker compose up -d --build
```

不要在普通停止流程中使用 `docker compose down -v`。`-v` 会删除 PostgreSQL 和运行诊断
命名卷，属于不可恢复的数据删除操作。

## 5. 持久化范围

| 数据 | 保存位置 | 删除容器后是否保留 |
|---|---|---|
| 会话、消息、事件、审批、记忆 | `coding_agent_postgres_data` | 保留 |
| 安全 trace 与运行诊断 | `coding_agent_runtime_data` | 保留 |
| Agent 修改的项目文件 | 宿主机 `CODING_AGENT_WORKSPACE_PATH` | 保留 |
| Vue 静态资源 | frontend 镜像 | 重新构建 |
| 正式评测摘要 | backend 镜像 `/app/evaluation-results` | 随镜像发布 |

## 6. 常见问题

### frontend 一直等待 backend

```powershell
docker compose logs backend
docker compose logs postgres
```

重点检查数据库密码、DeepSeek 密钥、Alembic 迁移和 PostgreSQL 健康状态。

### 工作区目录为空或无法写入

确认 `CODING_AGENT_WORKSPACE_PATH` 指向已存在目录。Windows 使用正斜杠；Linux 可把
根目录 `.env` 中的 `CODING_AGENT_UID` 和 `CODING_AGENT_GID` 改成当前用户 ID 后重新构建。

### 8080 端口被占用

修改根目录 `.env`：

```dotenv
CODING_AGENT_HTTP_PORT=8081
```

然后重新执行启动命令并访问 `http://127.0.0.1:8081`。
