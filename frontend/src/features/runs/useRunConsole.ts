import { computed, reactive, ref } from 'vue'

import { apiClient, ApiRequestError } from './runApi'
import { openRunEventStream, type RunEventStreamCallbacks } from './runEventStream'
import type { ApiClient, RunEventEnvelope } from './types'
import {
  applyRunEvent,
  applyRunSnapshot,
  createRunConsoleState,
  isTerminalStatus,
  resetRunState,
} from './runState'

type StreamOpener = typeof openRunEventStream

export interface RunConsoleDependencies {
  api?: ApiClient
  openStream?: StreamOpener
  now?: () => number
  storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null
}

const LAST_RUN_KEY = 'clearloop.web.lastRunId'

function browserStorage(): Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    const localized: Record<string, string> = {
      workspace_invalid: '工作区路径格式无效。',
      workspace_not_absolute: '请输入绝对路径，例如 E:\\code\\my-project。',
      workspace_not_found: '工作区目录不存在。',
      workspace_not_directory: '工作区路径必须指向目录。',
      workspace_not_allowed: '该路径不在服务允许的根目录内。',
      provider_not_configured: '后端尚未配置 DeepSeek API Key。',
      workspace_busy: '该工作区已有一个任务正在运行。',
      run_capacity_reached: '本机运行数已达到上限，请等待当前任务结束。',
      memory_mutation_in_progress: '项目记忆正在更新，请等待操作完成后再开始运行。',
      run_not_found: '运行记录不存在或后端已重新启动。',
      approval_not_pending: '这项审批已失效或已处理。',
      approval_stale: '这项审批已过期，请刷新运行状态。',
      approval_already_resolved: '这项审批已经处理。',
      run_cancelling: '运行正在取消，无法再提交审批。',
      service_shutting_down: '后端服务正在关闭。',
    }
    return localized[error.code] ?? error.message
  }
  if (error instanceof Error && error.message) return error.message
  return '本机服务暂时无法完成请求。'
}

export function useRunConsole(dependencies: RunConsoleDependencies = {}) {
  const api = dependencies.api ?? apiClient
  const openStream = dependencies.openStream ?? openRunEventStream
  const now = dependencies.now ?? Date.now
  const storage =
    dependencies.storage === undefined
      ? browserStorage()
      : dependencies.storage
  const state = reactive(createRunConsoleState())
  const form = reactive({ workspace: '', task: '', useMemory: true })
  const clock = ref(now())
  let streamHandle: { close(): void } | null = null
  let clockTimer: ReturnType<typeof setInterval> | null = null
  let streamGeneration = 0
  let validationSequence = 0
  let validationController: AbortController | null = null
  let runGeneration = 0

  const active = computed(
    () => state.run !== null && !isTerminalStatus(state.run.status),
  )
  const canStart = computed(
    () =>
      form.workspace.trim().length > 0 &&
      form.task.trim().length > 0 &&
      !active.value &&
      state.action === 'idle',
  )
  const elapsedSeconds = computed(() => {
    if (!state.run) return 0
    if (state.run.duration_seconds !== null) return state.run.duration_seconds
    const start = state.run.started_at ?? state.run.created_at
    const timestamp = Date.parse(start)
    return Number.isFinite(timestamp) ? Math.max(0, (clock.value - timestamp) / 1000) : 0
  })

  function startClock(): void {
    if (clockTimer !== null) return
    clockTimer = setInterval(() => {
      clock.value = now()
    }, 1000)
  }

  function stopClock(): void {
    if (clockTimer !== null) clearInterval(clockTimer)
    clockTimer = null
  }

  function closeStream(): void {
    streamGeneration += 1
    streamHandle?.close()
    streamHandle = null
  }

  function rememberRun(runId: string): void {
    try {
      storage?.setItem(LAST_RUN_KEY, runId)
    } catch {
      // Storage is a convenience only; browser privacy settings must not stop a run.
    }
  }

  function forgetRun(): void {
    try {
      storage?.removeItem(LAST_RUN_KEY)
    } catch {
      // See rememberRun.
    }
  }

  function rememberedRunId(): string | null {
    try {
      const value = storage?.getItem(LAST_RUN_KEY)?.trim()
      return value || null
    } catch {
      return null
    }
  }

  async function checkHealth(): Promise<void> {
    state.health.phase = 'loading'
    state.health.message = null
    try {
      state.health.data = await api.health()
      state.health.phase = 'success'
    } catch (error) {
      state.health.data = null
      state.health.phase = 'error'
      state.health.message = errorMessage(error)
    }
  }

  async function validateWorkspace(): Promise<boolean> {
    const workspace = form.workspace.trim()
    const sequence = ++validationSequence
    validationController?.abort()
    validationController = null
    if (!workspace) {
      state.validation = {
        phase: 'error',
        checkedValue: null,
        data: null,
        message: '请输入工作区路径。',
      }
      return false
    }
    const controller = new AbortController()
    validationController = controller
    state.validation.phase = 'loading'
    state.validation.message = null
    try {
      const result = await api.validateWorkspace(workspace, controller.signal)
      if (sequence !== validationSequence || form.workspace.trim() !== workspace) return false
      state.validation = {
        phase: 'success',
        checkedValue: result.workspace,
        data: result,
        message: null,
      }
      form.workspace = result.workspace
      return true
    } catch (error) {
      if (sequence !== validationSequence || controller.signal.aborted) return false
      state.validation = {
        phase: 'error',
        checkedValue: workspace,
        data: null,
        message: errorMessage(error),
      }
      return false
    } finally {
      if (validationController === controller) validationController = null
    }
  }

  async function refreshRun(): Promise<void> {
    const runId = state.run?.run_id
    if (!runId) return
    const generation = runGeneration
    try {
      const run = await api.getRun(runId)
      if (generation !== runGeneration || state.run?.run_id !== runId) return
      applyRunSnapshot(state, run)
      if (isTerminalStatus(run.status)) {
        closeStream()
        stopClock()
        void checkHealth()
      }
    } catch (error) {
      if (generation !== runGeneration || state.run?.run_id !== runId) return
      state.message = errorMessage(error)
    }
  }

  async function restoreRun(): Promise<void> {
    const runId = rememberedRunId()
    if (!runId || state.run) return
    const generation = runGeneration
    try {
      const run = await api.getRun(runId)
      if (generation !== runGeneration || state.run || state.action !== 'idle') return
      applyRunSnapshot(state, run)
      form.workspace = run.workspace
      form.useMemory = run.memory.status !== 'disabled'
      // Replaying the bounded SSE buffer restores the visible execution trail
      // for both active and recently completed runs.
      connectStream(run.run_id)
      if (!isTerminalStatus(run.status)) {
        startClock()
      }
    } catch (error) {
      if (generation !== runGeneration || state.run || state.action !== 'idle') return
      if (error instanceof ApiRequestError && error.status === 404) {
        forgetRun()
        return
      }
      state.message = errorMessage(error)
    }
  }

  function handleEnvelope(envelope: RunEventEnvelope): void {
    applyRunEvent(state, envelope)
    if (envelope.event === 'stream.reset') void refreshRun()
    if (envelope.event === 'run.finished') void refreshRun()
  }

  function connectStream(runId: string): void {
    closeStream()
    const generation = streamGeneration
    const isCurrent = () => generation === streamGeneration && state.run?.run_id === runId
    state.stream = 'connecting'
    const callbacks: RunEventStreamCallbacks = {
      onOpen: () => {
        if (!isCurrent()) return
        state.stream = 'live'
      },
      onEvent: (envelope) => {
        if (!isCurrent()) return
        handleEnvelope(envelope)
      },
      onError: () => {
        if (!isCurrent()) return
        if (!state.run || isTerminalStatus(state.run.status)) {
          state.stream = 'closed'
          return
        }
        state.stream = 'reconnecting'
      },
    }
    streamHandle = openStream(runId, callbacks)
  }

  async function startRun(): Promise<void> {
    if (!canStart.value) return
    runGeneration += 1
    state.action = 'starting'
    state.message = null
    try {
      const workspaceIsCurrent =
        state.validation.phase === 'success' &&
        state.validation.checkedValue === form.workspace.trim()
      if (!workspaceIsCurrent && !(await validateWorkspace())) return
      resetRunState(state)
      const run = await api.createRun({
        workspace: form.workspace.trim(),
        task: form.task.trim(),
        use_memory: form.useMemory,
      })
      applyRunSnapshot(state, run)
      rememberRun(run.run_id)
      startClock()
      connectStream(run.run_id)
      void checkHealth()
    } catch (error) {
      state.message = errorMessage(error)
    } finally {
      state.action = 'idle'
    }
  }

  async function cancelRun(): Promise<void> {
    if (!state.run || !active.value || state.action !== 'idle') return
    state.action = 'cancelling'
    state.message = null
    try {
      applyRunSnapshot(state, await api.cancelRun(state.run.run_id))
    } catch (error) {
      state.message = errorMessage(error)
    } finally {
      state.action = 'idle'
    }
  }

  async function decideApproval(decision: 'approve' | 'reject'): Promise<void> {
    if (!state.run || !state.pendingApproval || state.action !== 'idle') return
    const approvalId = state.pendingApproval.approval_id
    state.action = decision === 'approve' ? 'approving' : 'rejecting'
    state.message = null
    try {
      await api.decideApproval(state.run.run_id, approvalId, decision)
      state.pendingApproval = null
      await refreshRun()
    } catch (error) {
      state.message = errorMessage(error)
    } finally {
      state.action = 'idle'
    }
  }

  function updateWorkspace(value: string): void {
    runGeneration += 1
    validationSequence += 1
    validationController?.abort()
    validationController = null
    form.workspace = value
    if (state.validation.checkedValue !== value.trim()) {
      state.validation = { phase: 'idle', checkedValue: null, data: null, message: null }
    }
  }

  function updateTask(value: string): void {
    runGeneration += 1
    form.task = value
  }

  function dispose(): void {
    runGeneration += 1
    validationSequence += 1
    validationController?.abort()
    validationController = null
    closeStream()
    stopClock()
  }

  return {
    state,
    form,
    active,
    canStart,
    elapsedSeconds,
    checkHealth,
    validateWorkspace,
    startRun,
    cancelRun,
    decideApproval,
    updateWorkspace,
    updateTask,
    refreshRun,
    restoreRun,
    dispose,
  }
}
