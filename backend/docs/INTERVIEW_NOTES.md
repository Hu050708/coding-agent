# 面试答辩要点

## 为什么这样分层

- `core` 依赖 `CompletionAdapter`、`ToolExecutor`、`TraceEmitter` 三个端口，因此假模型可覆盖整个循环，OpenAI SDK 不能渗入状态机。
- `providers` 只把 Chat Completions 对象规范化，不能执行工具或决定重试循环。
- `tools` 负责合同、schema、分发和实现；`security` 负责路径、原子 IO 与命令策略；CLI 只是组合根。

## 为什么不用 streaming / strict / 动态摘要

- 非流式响应避免 reasoning 与 tool-call 增量拼装，使首版协议面可穷举测试。
- DeepSeek `/beta` strict 不是安全边界，普通模式仍必须本地验证 JSON、类型、未知字段和路径。
- thinking + tools 要完整回传 `reasoning_content`；运行中裁剪或伪造摘要容易破坏协议。首版通过有限轮次、工具输出硬限长和 token 总预算控制上下文。

## 为什么工具写入分成 create 与 replace

- `write_file` 只创建，通过同卷临时文件与 fail-if-exists 原子发布避免竞态覆盖。
- `replace_text` 必须携带最近读取的 SHA-256，且字面文本恰好匹配一次；状态改变就要求重读。Windows 不提供通用文件 CAS，最终替换前仍有极短 TOCTOU 窗口，不能夸大为绝对安全。

## 为什么命令不等于沙箱

- argv + `shell=False` 去掉管道、重定向和 shell 展开；策略再区分 ALLOW、CONFIRM、DENY，并剥离 API key 等环境变量。
- 但获准的 Python/可执行程序仍有当前用户权限，可能访问工作区外资源。真正强隔离需要容器、VM 或受限 OS 账户，不在首版范围。

## DeepSeek 协议关键点

- 默认 `deepseek-v4-flash`、thinking high、非流式 Chat Completions。
- tool turn 的 assistant 消息必须完整保留 `reasoning_content` 和全部 tool calls，下一请求原样回传；reasoning 不显示、不写日志。
- `length/content_filter/协议冲突` 的部分消息不能入历史或执行；`insufficient_system_resource` 丢弃并在预算内原请求重试。
- `MODEL_FINISHED` 只表示模型停止调用工具，任务是否成功由独立 verifier 判断，`verified` 默认是 unknown。

## 为什么 Web 和记忆不进入 Agent core

- FastAPI/RunManager 只是本机 loopback 传输与运行编排；CLI 和 Web 最终都装配同一个 `Agent`，因此界面不是在现成 Agent 产品上套壳。
- 记忆按规范化工作区隔离，只在运行开始读取一次不可变快照；模型没有写记忆工具，结果必须由用户在界面中编辑确认后保存。
- SQLite 放在 Agent 可操作根目录之外；同一工作区的运行与记忆写入双向互斥，避免运行中的代码调用本机 API 绕过确认。
- 记忆是可选辅助，数据库故障降级为 `unavailable`，不能改变核心任务、安全策略、审批、预算或工作区边界。

## 可能追问

- **为何顺序执行多工具？** 避免并发写入顺序不确定；hash 锁可让同轮后续陈旧写失败。首版可靠性优先于吞吐。
- **为何用官方 OpenAI 客户端不算 Agent SDK？** 它只承担 HTTP 与数据对象；历史、解析、工具、循环、预算和错误策略均为本项目代码。
- **如何证明不是模型自说完成？** 假模型协议测试验证状态机，真实 smoke 验证线上协议，正式 demo 用 agent 看不到的隐藏日志黑盒验收。
