# 面试答辩要点

## 为什么这样分层

- `core` 依赖 `CompletionAdapter`、`ToolExecutor`、`TraceEmitter` 三个端口，因此假模型可覆盖整个循环，OpenAI SDK 不能渗入状态机。
- `deepseek.py` 只整理 Chat Completions 返回值，不能执行工具或决定重试循环。
- `tools` 负责合同、schema、分发和实现；`security` 负责路径、原子 IO 与命令策略；CLI 只是组合根。

## 为什么不用 streaming / strict / 模型摘要

- 非流式响应避免 reasoning 与 tool-call 增量拼装，使首版协议面可穷举测试。
- DeepSeek `/beta` strict 不是安全边界，普通模式仍必须本地验证 JSON、类型、未知字段和路径。
- thinking + tools 要完整回传本次运行中每个 assistant tool turn 的原始 `reasoning_content`。首版通过有限轮次、token 预算和工具输出限长控制上下文，不做模型摘要。

## 为什么文件生命周期拆成四个工具

- `make_directory` 幂等创建目录，可创建缺失父目录，但拒绝受保护路径和任一路径链接。
- `write_file` 只创建，通过同卷临时文件与 fail-if-exists 原子发布避免竞态覆盖。
- `replace_text` 必须携带最近读取的 SHA-256，且字面文本恰好匹配一次；状态改变就要求重读。Windows 不提供通用文件 CAS，最终替换前仍有极短 TOCTOU 窗口，不能夸大为绝对安全。
- `delete_file` 只删除普通文件，要求最近读取哈希并在删除前复核；`ask` 和 `agent` 都需审批，不开放递归目录删除。

## 为什么增加原生 search_text

- `list_files` 加分段 `read_file` 能完成搜索，但会产生更多模型轮次和无关上下文；让模型运行 `rg` 又把普通代码定位变成了命令策略问题。
- `search_text` 由项目在工作区内执行有界字面搜索，不依赖 shell；文件数、总字节、单文件、结果和输出均有限制，并复用现有链接与受保护路径规则。
- 首版没有加入正则表达式，因为符号定位的主要需求可由字面搜索覆盖，而正则会增加生成、转义和性能失败面。

## 为什么重复检测只提示、不终止

- 当前能可靠证明的是工具名、规范化参数和去除耗时字段后的结果完全相同，不能据此证明整个任务在语义上没有进展。
- 从第三次相同交换起向模型结果附加恢复提示，但不改变原始 `ok` 或错误码，不抑制工具，也不增加终止原因；硬调用次数、token 和墙钟预算仍保证最终停止。
- 检测器只保存有界 SHA-256 指纹，不保存参数、文件内容或命令输出。是否升级为自动终止要等批量真实任务数据，而不是凭直觉决定。

## 为什么命令不等于沙箱

- argv + `shell=False` 去掉管道、重定向和 shell 展开；策略再区分 ALLOW、CONFIRM、DENY，并剥离 API key 等环境变量。
- 但获准的 Python/可执行程序仍有当前用户权限，可能访问工作区外资源。真正强隔离需要容器、VM 或受限 OS 账户，不在首版范围。

## DeepSeek 协议关键点

- 默认 `deepseek-v4-flash`、thinking high、非流式 Chat Completions。
- V4 thinking + tools 不发送 `tool_choice`。tool turn 的 assistant 消息完整保留 `reasoning_content` 和全部 tool calls，`content=null` 回放为 `""`；reasoning 不显示、不写日志。
- `length/content_filter/协议冲突` 的部分消息不能入历史或执行；`insufficient_system_resource` 丢弃并在预算内原请求重试。
- `MODEL_FINISHED` 只表示模型停止调用工具，任务是否成功由独立 verifier 判断，`verified` 默认是 unknown。

## 为什么 Web 和记忆不进入 Agent core

- FastAPI、应用服务、PostgreSQL 和 RunManager 是本机 loopback 的传输、目录与编排层；CLI 和 Web
  最终都装配同一个 `Agent`，因此界面不是在现成 Agent 产品上套壳。CLI 不需要 Docker、数据库或 Web。
- Web 强制连接本项目独立的 `coding-agent-postgres`；数据库缺失、不可达或迁移失败会阻止 Web 启动，
  不会静默降级。PostgreSQL 持久化 workspace、conversation、可见 message、run、安全 event、approval
  和 memory，但没有隐藏推理、原始提供方响应或完整工具输出字段。
- 记忆按规范化 workspace 隔离。run、当前 user message、可见历史和实际 memory 集合在同一事务中冻结；
  最多 32 条、正文合计不超过 32000 字符。模型没有写记忆工具，结果必须由用户编辑确认后保存。
- run 创建与 memory 修改都先锁 workspace；同一 workspace 的活动 run 和记忆写入互斥，避免运行中的
  代码调用本机 API 绕过确认。首版不做 embedding、向量检索或跨工作区画像。

## 为什么选择 PostgreSQL 和数据库重放 SSE

- WebUI 需要长期保存工作区、会话、消息、审批和记忆；项目已移除早期的 SQLite 单文件记忆实现，
  PostgreSQL 能更直接地承载部分唯一索引、行锁和多工作区并发语义，因此由 SQLAlchemy 2、
  psycopg 3 与 Alembic 管理独立数据库。这是工程取舍，不是宣称 SQLite 无法保存这些实体。
- 同一 workspace 最多一个活动 run 既有应用层友好检查，也有 PostgreSQL 部分唯一索引兜底；
  `client_request_id` 使浏览器重试不会重复创建 user message 和 run。
- SSE 事件显式使用 `(run_id, seq)`。断线后按 `Last-Event-ID` 从数据库重放，进程内 EventBuffer 只负责
  唤醒实时连接。服务重启把旧活动 run 标为 `interrupted` 并追加事件，不声称继续执行旧进程。
- 数据库容器只隔离数据依赖，不隔离 Agent 执行。工具和批准的命令仍在当前 Windows 用户权限下运行。

## 三档权限为什么要按 run 冻结

- `ask` 对文件修改和命令逐次审批；`agent` 自动执行常规工作区操作，但删除文件和风险命令仍需审批；
  `workspace_full` 自动执行工作区内所有非禁止操作。三者都不能绕过 `DENY`、工作区边界、预算或取消。
- 权限值随 run 持久化并在后端构造 ToolRegistry 时生效，切换前端下拉框不会改变已经开始的 run。
- 这是应用级能力控制，不是 OS sandbox；被批准的程序仍可能访问当前用户有权访问的工作区外资源。

## 可能追问

- **为何顺序执行多工具？** 避免并发写入顺序不确定；hash 锁可让同轮后续陈旧写失败。首版可靠性优先于吞吐。
- **为何用官方 OpenAI 客户端不算 Agent SDK？** 它只承担 HTTP 与数据对象；历史、解析、工具、循环、预算和错误策略均为本项目代码。
- **如何证明不是模型自说完成？** 假模型协议测试验证状态机，真实 smoke 验证线上协议，正式 demo 用 agent 看不到的隐藏日志黑盒验收。
- **为什么不用 pgvector？** 当前没有冻结 embedding 提供方和模型；先用确定的置顶/更新时间顺序和 32k
  预算保存真实快照，避免为了“像 RAG”而引入无法解释的向量结果。镜像包含扩展不等于首版已使用向量检索。
