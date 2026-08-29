import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { RunSummary } from '../../runs/types'
import RunResult from './RunResult.vue'

function completedRun(): RunSummary {
  return {
    id: 'run-1',
    conversation_id: 'conversation-1',
    workspace_id: 'workspace-1',
    status: 'completed',
    permission_mode: 'agent',
    use_memory: true,
    model: 'deepseek-chat',
    final_content: 'done',
    reason: 'model_final',
    error: null,
    pending_approval: null,
    usage: { prompt_tokens: 800, completion_tokens: 200, total_tokens: 1000 },
    model_calls: 3,
    tool_calls: 5,
    duration_ms: 2450,
    created_at: '2026-08-27T10:00:00Z',
    started_at: '2026-08-27T10:00:00Z',
    finished_at: '2026-08-27T10:00:02Z',
  }
}

describe('RunResult', () => {
  it('separates model termination from external verification evidence', () => {
    const wrapper = mount(RunResult, { props: { run: completedRun() } })

    expect(wrapper.text()).toContain('待外部验证')
    expect(wrapper.text()).toContain('独立验收')
    expect(wrapper.text()).toContain('尚未执行')
    expect(wrapper.text()).toContain('模型调用3 次')
    expect(wrapper.text()).toContain('工具调用5 次')
    expect(wrapper.text()).toContain('总耗时2.5 s')
    expect(wrapper.text()).not.toContain('验证成功')
  })
})
