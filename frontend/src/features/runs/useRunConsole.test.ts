import { describe, expect, it, vi } from 'vitest'

import { ApiRequestError } from './runApi'
import type { RunEventStreamCallbacks } from './runEventStream'
import type { ApiClient, RunSummary } from './types'
import { useRunConsole } from './useRunConsole'

function runFixture(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: 'run-42',
    status: 'starting',
    workspace: 'E:\\code\\demo',
    created_at: '2026-08-27T09:30:00Z',
    started_at: null,
    finished_at: null,
    final_content: null,
    reason: null,
    error: null,
    model_calls: 0,
    tool_calls: 0,
    usage: {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      prompt_cache_hit_tokens: 0,
      prompt_cache_miss_tokens: 0,
    },
    duration_seconds: null,
    pending_approval: null,
    cancel_requested: false,
    memory: { status: 'pending', loaded_count: 0, loaded_ids: [] },
    ...overrides,
  }
}

function deferred<T>(): { promise: Promise<T>; resolve(value: T): void; reject(reason: unknown): void } {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve
    reject = nextReject
  })
  return { promise, resolve, reject }
}

describe('useRunConsole', () => {
  it('validates, creates, and subscribes to one run', async () => {
    const api: ApiClient = {
      health: vi.fn(),
      validateWorkspace: vi.fn(async (workspace: string) => ({
        valid: true as const,
        workspace,
        allowed_root: 'E:\\code',
      })),
      createRun: vi.fn(async () => runFixture()),
      getRun: vi.fn(async () => runFixture()),
      cancelRun: vi.fn(
        async (): Promise<RunSummary> => ({ ...runFixture(), status: 'cancelling' }),
      ),
      decideApproval: vi.fn(),
    }
    let callbacks: RunEventStreamCallbacks | null = null
    const close = vi.fn()
    const storage = {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    }
    const consoleState = useRunConsole({
      api,
      openStream: (_runId, nextCallbacks) => {
        callbacks = nextCallbacks
        return { close }
      },
      now: () => Date.parse('2026-08-27T09:30:00Z'),
      storage,
    })
    consoleState.updateWorkspace('E:\\code\\demo')
    consoleState.updateTask('修复边界测试')

    await consoleState.startRun()

    expect(api.validateWorkspace).toHaveBeenCalledWith('E:\\code\\demo', expect.any(AbortSignal))
    expect(api.createRun).toHaveBeenCalledWith({
      workspace: 'E:\\code\\demo',
      task: '修复边界测试',
      use_memory: true,
    })
    expect(consoleState.state.run?.run_id).toBe('run-42')
    expect(storage.setItem).toHaveBeenCalledWith('clearloop.web.lastRunId', 'run-42')
    expect(callbacks).not.toBeNull()

    consoleState.dispose()
    expect(close).toHaveBeenCalledOnce()
  })

  it('restores and reconnects an unfinished run after a page refresh', async () => {
    const restored = { ...runFixture(), status: 'running' as const }
    const api = {
      health: vi.fn(),
      validateWorkspace: vi.fn(),
      createRun: vi.fn(),
      getRun: vi.fn(async () => restored),
      cancelRun: vi.fn(),
      decideApproval: vi.fn(),
    } satisfies ApiClient
    const openStream = vi.fn(() => ({ close: vi.fn() }))
    const consoleState = useRunConsole({
      api,
      openStream,
      storage: {
        getItem: vi.fn(() => 'run-42'),
        setItem: vi.fn(),
        removeItem: vi.fn(),
      },
    })

    await consoleState.restoreRun()

    expect(api.getRun).toHaveBeenCalledWith('run-42')
    expect(consoleState.state.run?.status).toBe('running')
    expect(consoleState.form.workspace).toBe('E:\\code\\demo')
    expect(openStream).toHaveBeenCalledWith('run-42', expect.any(Object))
    consoleState.dispose()
  })

  it('ignores a stale workspace validation response after the path changes', async () => {
    const first = deferred<{ valid: true; workspace: string; allowed_root: string }>()
    const second = deferred<{ valid: true; workspace: string; allowed_root: string }>()
    const api = {
      health: vi.fn(),
      validateWorkspace: vi
        .fn()
        .mockImplementationOnce(() => first.promise)
        .mockImplementationOnce(() => second.promise),
      createRun: vi.fn(),
      getRun: vi.fn(),
      cancelRun: vi.fn(),
      decideApproval: vi.fn(),
    } satisfies ApiClient
    const consoleState = useRunConsole({ api, storage: null })

    consoleState.updateWorkspace('E:\\code\\old')
    const validatingOld = consoleState.validateWorkspace()
    consoleState.updateWorkspace('E:\\code\\new')
    const validatingNew = consoleState.validateWorkspace()
    second.resolve({ valid: true, workspace: 'E:\\code\\new', allowed_root: 'E:\\code' })
    await expect(validatingNew).resolves.toBe(true)
    first.resolve({ valid: true, workspace: 'E:\\code\\old', allowed_root: 'E:\\code' })
    await expect(validatingOld).resolves.toBe(false)

    expect(consoleState.form.workspace).toBe('E:\\code\\new')
    expect(consoleState.state.validation).toMatchObject({
      phase: 'success',
      checkedValue: 'E:\\code\\new',
    })
    consoleState.dispose()
  })

  it('does not let a late restore replace a newly created run', async () => {
    const restoredRequest = deferred<RunSummary>()
    const newRun = runFixture({ run_id: 'run-new', workspace: 'E:\\code\\new' })
    const api = {
      health: vi.fn(),
      validateWorkspace: vi.fn(async (workspace: string) => ({
        valid: true as const,
        workspace,
        allowed_root: 'E:\\code',
      })),
      createRun: vi.fn(async () => newRun),
      getRun: vi.fn(() => restoredRequest.promise),
      cancelRun: vi.fn(),
      decideApproval: vi.fn(),
    } satisfies ApiClient
    const openStream = vi.fn(() => ({ close: vi.fn() }))
    const consoleState = useRunConsole({
      api,
      openStream,
      storage: {
        getItem: vi.fn(() => 'run-old'),
        setItem: vi.fn(),
        removeItem: vi.fn(),
      },
    })

    const restoring = consoleState.restoreRun()
    consoleState.updateWorkspace('E:\\code\\new')
    consoleState.updateTask('启动新任务')
    await consoleState.startRun()
    restoredRequest.resolve(runFixture({ run_id: 'run-old', status: 'running' }))
    await restoring

    expect(consoleState.state.run?.run_id).toBe('run-new')
    expect(openStream).toHaveBeenCalledTimes(1)
    expect(openStream).toHaveBeenCalledWith('run-new', expect.any(Object))
    consoleState.dispose()
  })

  it('does not let a late restore 404 forget a newly created run', async () => {
    const restoredRequest = deferred<RunSummary>()
    const storage = {
      getItem: vi.fn(() => 'run-old'),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    }
    const api = {
      health: vi.fn(),
      validateWorkspace: vi.fn(async (workspace: string) => ({
        valid: true as const,
        workspace,
        allowed_root: 'E:\\code',
      })),
      createRun: vi.fn(async () => runFixture({ run_id: 'run-new' })),
      getRun: vi.fn(() => restoredRequest.promise),
      cancelRun: vi.fn(),
      decideApproval: vi.fn(),
    } satisfies ApiClient
    const consoleState = useRunConsole({ api, storage })

    const restoring = consoleState.restoreRun()
    consoleState.updateWorkspace('E:\\code\\new')
    consoleState.updateTask('启动新任务')
    await consoleState.startRun()
    restoredRequest.reject(
      new ApiRequestError(404, { code: 'run_not_found', message: '旧运行不存在' }),
    )
    await restoring

    expect(consoleState.state.run?.run_id).toBe('run-new')
    expect(storage.setItem).toHaveBeenCalledWith('clearloop.web.lastRunId', 'run-new')
    expect(storage.removeItem).not.toHaveBeenCalled()
    consoleState.dispose()
  })

  it('keeps a created run visible even if inputs change while creation is in flight', async () => {
    const createdRequest = deferred<RunSummary>()
    const api = {
      health: vi.fn(),
      validateWorkspace: vi.fn(async (workspace: string) => ({
        valid: true as const,
        workspace,
        allowed_root: 'E:\\code',
      })),
      createRun: vi.fn(() => createdRequest.promise),
      getRun: vi.fn(),
      cancelRun: vi.fn(),
      decideApproval: vi.fn(),
    } satisfies ApiClient
    const consoleState = useRunConsole({ api, storage: null })
    consoleState.updateWorkspace('E:\\code\\original')
    consoleState.updateTask('原始任务')

    const starting = consoleState.startRun()
    await vi.waitFor(() => expect(api.createRun).toHaveBeenCalledOnce())
    consoleState.updateWorkspace('E:\\code\\changed')
    consoleState.updateTask('后续输入')
    createdRequest.resolve(runFixture({ run_id: 'run-created', workspace: 'E:\\code\\original' }))
    await starting

    expect(consoleState.state.run?.run_id).toBe('run-created')
    consoleState.dispose()
  })

  it('ignores a late refresh for the previous run', async () => {
    const lateRefresh = deferred<RunSummary>()
    const oldRun = runFixture({ run_id: 'run-old', status: 'completed' })
    const newRun = runFixture({ run_id: 'run-new', status: 'starting' })
    const api = {
      health: vi.fn(),
      validateWorkspace: vi.fn(async (workspace: string) => ({
        valid: true as const,
        workspace,
        allowed_root: 'E:\\code',
      })),
      createRun: vi.fn(async () => newRun),
      getRun: vi
        .fn()
        .mockResolvedValueOnce(oldRun)
        .mockImplementationOnce(() => lateRefresh.promise),
      cancelRun: vi.fn(),
      decideApproval: vi.fn(),
    } satisfies ApiClient
    const consoleState = useRunConsole({
      api,
      storage: {
        getItem: vi.fn(() => 'run-old'),
        setItem: vi.fn(),
        removeItem: vi.fn(),
      },
    })
    await consoleState.restoreRun()
    consoleState.updateTask('新任务')
    const refreshing = consoleState.refreshRun()
    await consoleState.startRun()
    lateRefresh.resolve(runFixture({ run_id: 'run-old', status: 'failed' }))
    await refreshing

    expect(consoleState.state.run?.run_id).toBe('run-new')
    expect(consoleState.state.run?.status).toBe('starting')
    consoleState.dispose()
  })

  it('ignores queued events and errors from a closed run stream', async () => {
    const firstRun = runFixture({ run_id: 'run-first', status: 'starting' })
    const secondRun = runFixture({ run_id: 'run-second', status: 'starting' })
    const api = {
      health: vi.fn(),
      validateWorkspace: vi.fn(async (workspace: string) => ({
        valid: true as const,
        workspace,
        allowed_root: 'E:\\code',
      })),
      createRun: vi.fn().mockResolvedValueOnce(firstRun).mockResolvedValueOnce(secondRun),
      getRun: vi.fn(),
      cancelRun: vi.fn(),
      decideApproval: vi.fn(),
    } satisfies ApiClient
    const streams: RunEventStreamCallbacks[] = []
    const consoleState = useRunConsole({
      api,
      storage: null,
      openStream: (_runId, callbacks) => {
        streams.push(callbacks)
        return { close: vi.fn() }
      },
    })
    consoleState.updateWorkspace('E:\\code\\demo')
    consoleState.updateTask('第一项任务')
    await consoleState.startRun()
    if (consoleState.state.run) consoleState.state.run.status = 'completed'
    consoleState.updateTask('第二项任务')
    await consoleState.startRun()
    streams[1]?.onOpen()

    streams[0]?.onEvent({
      seq: 99,
      event: 'run.finished',
      timestamp: '2026-08-27T10:00:00Z',
      data: { status: 'failed' },
    })
    streams[0]?.onError()

    expect(consoleState.state.run?.run_id).toBe('run-second')
    expect(consoleState.state.run?.status).toBe('starting')
    expect(consoleState.state.timeline).toEqual([])
    expect(consoleState.state.stream).toBe('live')
    consoleState.dispose()
  })

  it('explains that a run must wait for an in-flight memory mutation', async () => {
    const api = {
      health: vi.fn(),
      validateWorkspace: vi.fn(async (workspace: string) => ({
        valid: true as const,
        workspace,
        allowed_root: 'E:\\code',
      })),
      createRun: vi.fn(async () => {
        throw new ApiRequestError(409, {
          code: 'memory_mutation_in_progress',
          message: 'Memory mutation in progress',
        })
      }),
      getRun: vi.fn(),
      cancelRun: vi.fn(),
      decideApproval: vi.fn(),
    } satisfies ApiClient
    const consoleState = useRunConsole({ api, storage: null })
    consoleState.updateWorkspace('E:\\code\\demo')
    consoleState.updateTask('开始新任务')

    await consoleState.startRun()

    expect(consoleState.state.run).toBeNull()
    expect(consoleState.state.message).toBe('项目记忆正在更新，请等待操作完成后再开始运行。')
    consoleState.dispose()
  })
})
