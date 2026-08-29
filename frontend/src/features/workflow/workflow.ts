export type JsonValue = string | number | boolean | null | JsonValue[] | JsonObject

export interface JsonObject {
  [key: string]: JsonValue
}

export type SnapshotSection =
  | 'complete'
  | 'run'
  | 'agent_history'
  | 'approval'
  | 'workspace'
  | 'latest_event'

export interface DemoStep {
  id: string
  number: string
  title: string
  event: string
  actor: string
  summary: string
  changes: string[]
  state: JsonObject
}

export const demoTask = '请帮我生成一个简单的 Python 程序'

export const snapshotSections: Array<{ id: SnapshotSection; label: string }> = [
  { id: 'complete', label: '完整状态' },
  { id: 'run', label: '运行状态' },
  { id: 'agent_history', label: '消息历史' },
  { id: 'approval', label: '审批状态' },
  { id: 'workspace', label: '工作区' },
  { id: 'latest_event', label: '当前事件' },
]

const runId = 'demo-python-001'
const fileContent = [
  'def main():',
  '    print("Hello, world!")',
  '',
  'if __name__ == "__main__":',
  '    main()',
  '',
].join('\n')

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function event(seq: number, name: string, data: JsonObject): JsonObject {
  return {
    seq,
    event: name,
    timestamp: `2026-08-29T14:30:${String(seq).padStart(2, '0')}+08:00`,
    data,
  }
}

function buildDemoSteps(): DemoStep[] {
  const state: JsonObject = {
    run: {
      id: runId,
      status: 'starting',
      task: demoTask,
      model: 'deepseek-v4-flash',
      permission_mode: 'ask',
      use_memory: false,
      model_calls: 0,
      tool_calls: 0,
      usage: {
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
      },
      reason: null,
      final_content: null,
    },
    agent_history: [],
    approval: {
      pending: null,
      resolved: [],
    },
    workspace: {
      root: 'E:\\demo\\python-example',
      files: [],
      last_command: null,
    },
    latest_event: event(1, 'run.accepted', {
      run_id: runId,
      status: 'starting',
    }),
  }

  const steps: DemoStep[] = []
  const save = (
    id: string,
    number: string,
    title: string,
    eventName: string,
    actor: string,
    summary: string,
    changes: string[],
  ): void => {
    steps.push({ id, number, title, event: eventName, actor, summary, changes, state: clone(state) })
  }

  save('accepted', '01', '接收用户任务', 'run.accepted', 'Web 服务',
    '任务已登记，但 Agent 还没有调用模型或工具。',
    ['创建 run 记录', '保存任务、模型和权限模式'])

  state.run = { ...(state.run as JsonObject), status: 'running' }
  state.agent_history = [
    { role: 'system', content: '你是本地 Coding Agent。先检查工作区，进行最小修改，并验证结果。' },
    { role: 'user', content: demoTask },
  ]
  state.latest_event = event(3, 'memory.loaded', { status: 'disabled', loaded_count: 0 })
  save('context', '02', '准备模型上下文', 'memory.loaded', 'Agent 控制器',
    '控制器冻结运行输入，并把系统规则和当前任务放入消息历史。',
    ['run.status 变为 running', 'agent_history 新增 system 和 user 消息', '本次示例禁用长期记忆'])

  state.run = {
    ...(state.run as JsonObject),
    model_calls: 1,
    usage: { prompt_tokens: 312, completion_tokens: 74, total_tokens: 386 },
  }
  ;(state.agent_history as JsonValue[]).push({
    role: 'assistant',
    content: null,
    tool_calls: [{
      id: 'call_write_001',
      type: 'function',
      function: {
        name: 'write_file',
        arguments: JSON.stringify({ path: 'hello.py', content: fileContent }),
      },
    }],
  })
  state.latest_event = event(4, 'model.completed', {
    sequence: 1,
    model: 'deepseek-v4-flash',
    finish_reason: 'tool_calls',
    latency_ms: 862,
    usage: { prompt_tokens: 312, completion_tokens: 74, total_tokens: 386 },
  })
  save('write-decision', '03', '模型决定创建文件', 'model.completed', 'DeepSeek',
    '模型没有直接回答，而是请求调用 write_file 创建 hello.py。',
    ['model_calls 增加到 1', '记录 assistant tool_calls', '尚未产生文件'])

  state.run = { ...(state.run as JsonObject), status: 'waiting_approval', tool_calls: 1 }
  state.approval = {
    pending: {
      id: 'approval_write_001',
      tool_name: 'write_file',
      action_summary: '创建 hello.py',
      reason: 'ask 模式下，文件修改需要人工确认',
      status: 'pending',
    },
    resolved: [],
  }
  state.latest_event = event(6, 'approval.required', {
    run_id: runId,
    approval: {
      approval_id: 'approval_write_001',
      reason: 'ask 模式下，文件修改需要人工确认',
    },
  })
  save('write-approval', '04', '等待创建文件确认', 'approval.required', '权限策略',
    'write_file 被暂停，用户确认前不会修改工作区。',
    ['run.status 变为 waiting_approval', 'approval.pending 保存待确认操作', 'tool_calls 增加到 1'])

  state.run = { ...(state.run as JsonObject), status: 'running' }
  state.approval = {
    pending: null,
    resolved: [{ id: 'approval_write_001', decision: 'approve', resolution: 'approved_by_user' }],
  }
  state.workspace = {
    root: 'E:\\demo\\python-example',
    files: [{
      path: 'hello.py',
      status: 'created',
      bytes: fileContent.length,
      sha256: 'a7e4636f...demo',
      content: fileContent,
    }],
    last_command: null,
  }
  ;(state.agent_history as JsonValue[]).push({
    role: 'tool',
    tool_call_id: 'call_write_001',
    name: 'write_file',
    content: JSON.stringify({
      ok: true,
      data: { path: 'hello.py', bytes_written: fileContent.length },
      meta: {},
    }),
  })
  state.latest_event = event(8, 'tool.completed', {
    sequence: 1,
    tool_name: 'write_file',
    ok: true,
    duration_ms: 18,
    result_summary: '已创建 hello.py',
  })
  save('file-written', '05', '写入 hello.py', 'tool.completed', '本地工具',
    '用户批准后，本地工具创建文件，并把成功结果回填到消息历史。',
    ['approval.pending 清空', 'workspace.files 新增 hello.py', 'agent_history 新增 role=tool 结果'])

  state.run = {
    ...(state.run as JsonObject),
    model_calls: 2,
    usage: { prompt_tokens: 728, completion_tokens: 126, total_tokens: 854 },
  }
  ;(state.agent_history as JsonValue[]).push({
    role: 'assistant',
    content: null,
    tool_calls: [{
      id: 'call_command_001',
      type: 'function',
      function: {
        name: 'run_command',
        arguments: JSON.stringify({ argv: ['python', 'hello.py'], cwd: '.' }),
      },
    }],
  })
  state.latest_event = event(9, 'model.completed', {
    sequence: 2,
    model: 'deepseek-v4-flash',
    finish_reason: 'tool_calls',
    latency_ms: 641,
    usage: { prompt_tokens: 416, completion_tokens: 52, total_tokens: 468 },
  })
  save('command-decision', '06', '模型决定运行程序', 'model.completed', 'DeepSeek',
    '模型看到文件创建成功，下一步请求运行 python hello.py 验证结果。',
    ['model_calls 增加到 2', '累计 Token 更新', '消息历史新增 run_command 调用'])

  state.run = { ...(state.run as JsonObject), status: 'waiting_approval', tool_calls: 2 }
  state.approval = {
    pending: {
      id: 'approval_command_001',
      tool_name: 'run_command',
      action_summary: '运行 python hello.py',
      argv: ['python', 'hello.py'],
      cwd: '.',
      reason: 'ask 模式下，命令执行需要人工确认',
      status: 'pending',
    },
    resolved: (state.approval as JsonObject).resolved ?? [],
  }
  state.latest_event = event(11, 'approval.required', {
    run_id: runId,
    approval: {
      approval_id: 'approval_command_001',
      reason: 'ask 模式下，命令执行需要人工确认',
    },
  })
  save('command-approval', '07', '等待运行命令确认', 'approval.required', '权限策略',
    'run_command 被暂停，JSON 中可以看到完整 argv 和工作目录。',
    ['run.status 再次变为 waiting_approval', 'approval.pending 替换为命令审批', 'tool_calls 增加到 2'])

  state.run = { ...(state.run as JsonObject), status: 'running' }
  state.approval = {
    pending: null,
    resolved: [
      ...((state.approval as JsonObject).resolved as JsonValue[]),
      { id: 'approval_command_001', decision: 'approve', resolution: 'approved_by_user' },
    ],
  }
  state.workspace = {
    ...(state.workspace as JsonObject),
    last_command: {
      argv: ['python', 'hello.py'],
      cwd: '.',
      exit_code: 0,
      stdout: 'Hello, world!\n',
      stderr: '',
      duration_ms: 43,
    },
  }
  ;(state.agent_history as JsonValue[]).push({
    role: 'tool',
    tool_call_id: 'call_command_001',
    name: 'run_command',
    content: JSON.stringify({
      ok: true,
      data: { exit_code: 0, stdout: 'Hello, world!\n', stderr: '' },
      meta: { duration_ms: 43, truncated: false },
    }),
  })
  state.latest_event = event(13, 'tool.completed', {
    sequence: 2,
    tool_name: 'run_command',
    ok: true,
    exit_code: 0,
    duration_ms: 43,
    result_summary: 'exit 0 · Hello, world!',
  })
  save('command-completed', '08', '程序运行成功', 'tool.completed', '本地工具',
    '命令返回退出码 0 和标准输出，结果作为新的事实交给模型。',
    ['workspace.last_command 保存命令结果', 'agent_history 新增第二条 role=tool 消息', 'approval.pending 清空'])

  const finalContent = '已创建 `hello.py`。程序运行成功，输出为 `Hello, world!`。'
  state.run = {
    ...(state.run as JsonObject),
    model_calls: 3,
    usage: { prompt_tokens: 1169, completion_tokens: 168, total_tokens: 1337 },
    final_content: finalContent,
  }
  ;(state.agent_history as JsonValue[]).push({ role: 'assistant', content: finalContent })
  state.latest_event = event(14, 'model.completed', {
    sequence: 3,
    model: 'deepseek-v4-flash',
    finish_reason: 'stop',
    latency_ms: 518,
    usage: { prompt_tokens: 441, completion_tokens: 42, total_tokens: 483 },
  })
  save('model-final', '09', '模型给出最终回答', 'model.completed', 'DeepSeek',
    '模型看到命令成功后返回 final，本轮不再请求工具。',
    ['model_calls 增加到 3', 'run.final_content 写入回答', 'agent_history 新增最终 assistant 消息'])

  state.run = {
    ...(state.run as JsonObject),
    status: 'completed',
    reason: 'model_final',
    duration_ms: 2476,
  }
  state.latest_event = event(15, 'run.finished', {
    run_id: runId,
    status: 'completed',
    reason: 'model_final',
    model_calls: 3,
    tool_calls: 2,
    duration_seconds: 2.476,
    usage: (state.run as JsonObject).usage ?? {},
  })
  save('finished', '10', '保存运行终态', 'run.finished', 'Agent 控制器',
    '控制器保存终止原因和所有用量，本次示例运行结束。',
    ['run.status 变为 completed', 'run.reason 设置为 model_final', '发布最后一个 run.finished 事件'])

  return steps
}

export const demoSteps = buildDemoSteps()

export function sectionValue(state: JsonObject, section: SnapshotSection): JsonValue {
  if (section === 'complete') return state
  return state[section] ?? null
}
