项目名称：Coding Agent 编程智能体

Git仓库地址：https://github.com/Hu050708/coding-agent.git

一、运行方法
推荐使用 Docker Desktop 或 Docker Engine。进入仓库根目录，将 .env.docker.example 复制为 .env，填写 DEEPSEEK_API_KEY、至少32位的数据库密码和宿主机工作区路径，然后执行：

docker compose up -d --build

容器健康后访问 http://127.0.0.1:8080，API文档位于 http://127.0.0.1:8080/api/docs。系统由 Vue/Nginx 前端、FastAPI 后端和 PostgreSQL 组成，默认只允许本机访问。也可按 backend/environment.yml 创建环境，通过 coding-agent --workspace <项目目录> "编程任务" 独立运行CLI。

二、特色功能
项目未使用任何Agent框架，也未依赖服务端文件或代码执行工具。OpenAI Python客户端仅用于调用DeepSeek接口；对话历史与上下文、模型输出解析、Agent循环、工具定义与本地执行、预算、重试、终止和错误处理均由项目自行实现。

Agent提供目录浏览、文件读取、文本搜索、目录创建、文件创建、精确替换、文件删除和命令执行八个本地工具。调用会先校验严格JSON、唯一ID和整批预算，再顺序执行并把真实结果回填给模型。文件工具拒绝越界路径、链接和敏感文件，修改与删除使用SHA-256防止覆盖并发变化。Web支持三档权限、审批、取消、运行时间线、SSE断线重放、持久会话和用户确认的工作区记忆。

三、验证与说明
评测使用全新任务副本和工作区外verifier；固定3类任务各运行3次，独立验收及端到端结果均为9/9。模型最终回答只代表停止调用工具，不等同于任务已验证。命令策略不是操作系统级沙箱。开发中使用Codex/ChatGPT辅助，作者对全部设计与验证负责。真实凭据仅通过环境变量或未入库配置文件提供。