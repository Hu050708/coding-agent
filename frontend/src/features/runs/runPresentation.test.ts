import { describe, expect, it } from 'vitest'

import { presentRunEvent } from './runPresentation'

describe('run event presentation', () => {
  it('only renders bounded safe summaries', () => {
    const item = presentRunEvent({
      seq: 1,
      event: 'tool.completed',
      timestamp: '2026-08-27T10:00:00Z',
      data: {
        tool_name: 'run_command',
        summary: `line one\n${'x'.repeat(500)}`,
        duration_ms: 15.6,
        raw_output: 'must never be presented',
      },
    })
    expect(item.detail).not.toContain('\n')
    expect(item.detail?.length).toBeLessThanOrEqual(240)
    expect(item.meta).toBe('16 ms')
  })

  it('marks interrupted runs as recoverable warnings', () => {
    expect(
      presentRunEvent({
        seq: 2,
        event: 'run.interrupted',
        timestamp: '2026-08-27T10:00:00Z',
        data: {},
      }),
    ).toMatchObject({ tone: 'warning', title: '运行被服务重启中断' })
  })

  it('surfaces a repeated exchange warning without exposing tool content', () => {
    expect(
      presentRunEvent({
        seq: 3,
        event: 'tool.completed',
        timestamp: '2026-08-27T10:00:00Z',
        data: {
          tool_name: 'read_file',
          ok: true,
          repeat_count: 3,
          progress_warning: true,
          raw_result: 'must not be rendered',
        },
      }),
    ).toMatchObject({
      title: 'read_file完成',
      detail: '检测到完全重复的工具结果，已提示模型调整策略',
      tone: 'warning',
    })
  })
})
