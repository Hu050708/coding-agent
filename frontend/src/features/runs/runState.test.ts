import { describe, expect, it } from 'vitest'

import type { RunEventEnvelope, RunSummary } from './types'
import { applyRunEvent, applyRunSnapshot, createRunConsoleState } from './runState'

function runFixture(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: 'run-27',
    status: 'running',
    workspace: 'E:\\code\\demo',
    created_at: '2026-08-27T09:30:00Z',
    started_at: '2026-08-27T09:30:01Z',
    finished_at: null,
    final_content: null,
    reason: null,
    error: null,
    model_calls: 1,
    tool_calls: 0,
    usage: {
      prompt_tokens: 10,
      completion_tokens: 4,
      total_tokens: 14,
      prompt_cache_hit_tokens: 0,
      prompt_cache_miss_tokens: 10,
    },
    duration_seconds: null,
    pending_approval: null,
    cancel_requested: false,
    memory: { status: 'loaded', loaded_count: 1, loaded_ids: ['memory-1'] },
    ...overrides,
  }
}

function eventFixture(overrides: Partial<RunEventEnvelope> = {}): RunEventEnvelope {
  return {
    seq: 1,
    event: 'model.completed',
    timestamp: '2026-08-27T09:30:02Z',
    data: {},
    ...overrides,
  }
}

describe('run console state', () => {
  it('keeps only allowlisted presentation fields and never stores reasoning', () => {
    const state = createRunConsoleState()
    applyRunSnapshot(state, runFixture())
    applyRunEvent(
      state,
      eventFixture({
        data: {
          finish_reason: 'tool_calls',
          reasoning_content: 'private chain of thought',
          content: 'untrusted model body',
        },
      }),
    )

    expect(state.timeline[0]?.detail).toBe('tool_calls')
    expect(JSON.stringify(state)).not.toContain('private chain of thought')
    expect(JSON.stringify(state)).not.toContain('untrusted model body')
  })

  it('deduplicates replayed SSE events by sequence number', () => {
    const state = createRunConsoleState()
    const event = eventFixture()
    applyRunEvent(state, event)
    applyRunEvent(state, event)
    expect(state.timeline).toHaveLength(1)
  })

  it('projects live model and tool counters without retaining response bodies', () => {
    const state = createRunConsoleState()
    applyRunSnapshot(state, runFixture({ model_calls: 0, usage: {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      prompt_cache_hit_tokens: 0,
      prompt_cache_miss_tokens: 0,
    } }))
    applyRunEvent(state, eventFixture({
      data: {
        sequence: 1,
        usage: { prompt_tokens: 8, completion_tokens: 3, total_tokens: 11 },
        content: 'must not be retained',
      },
    }))
    applyRunEvent(state, eventFixture({
      seq: 2,
      event: 'tool.completed',
      data: { sequence: 1, ok: true, output: 'must not be retained' },
    }))

    expect(state.run?.model_calls).toBe(1)
    expect(state.run?.tool_calls).toBe(1)
    expect(state.run?.usage.total_tokens).toBe(11)
    expect(JSON.stringify(state)).not.toContain('must not be retained')
  })

  it('opens and resolves the single pending approval', () => {
    const state = createRunConsoleState()
    applyRunSnapshot(state, runFixture())
    applyRunEvent(
      state,
      eventFixture({
        seq: 2,
        event: 'approval.required',
        data: {
          approval: {
            approval_id: 'approval-1',
            argv: ['python', '-m', 'pytest'],
            cwd: '.',
            reason: '需要执行本机测试',
            created_at: '2026-08-27T09:30:02Z',
            expires_at: '2026-08-27T09:35:02Z',
          },
        },
      }),
    )
    expect(state.pendingApproval?.approval_id).toBe('approval-1')
    expect(state.run?.status).toBe('waiting_approval')

    applyRunEvent(
      state,
      eventFixture({ seq: 3, event: 'approval.resolved', data: { decision: 'approve' } }),
    )
    expect(state.pendingApproval).toBeNull()
    expect(state.run?.status).toBe('running')
  })

  it('projects only safe memory metadata from the event stream', () => {
    const state = createRunConsoleState()
    applyRunSnapshot(state, runFixture({ memory: { status: 'pending', loaded_count: 0, loaded_ids: [] } }))

    applyRunEvent(
      state,
      eventFixture({
        event: 'memory.loaded',
        data: {
          status: 'loaded',
          loaded_count: 2,
          loaded_ids: ['memory-1', 'memory-2'],
          content: '不得进入前端状态的记忆正文',
          reasoning_content: '不得进入前端状态的推理',
        },
      }),
    )

    expect(state.run?.memory).toEqual({
      status: 'loaded',
      loaded_count: 2,
      loaded_ids: ['memory-1', 'memory-2'],
    })
    expect(JSON.stringify(state)).not.toContain('不得进入前端状态')
  })
})
