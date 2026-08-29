import { describe, expect, it } from 'vitest'

import type { RunEventEnvelope } from './types'
import { latestChangeCheck, presentChangeCheck, presentRunEvent, presentRunOutcome } from './display'

describe('run event presentation', () => {
  it('only renders bounded safe summaries', () => {
    const item = presentRunEvent({
      seq: 1,
      event: 'tool.completed',
      timestamp: '2026-08-27T10:00:00Z',
      data: {
        tool_name: 'run_command',
        result_summary: `line one\n${'x'.repeat(500)}`,
        duration_ms: 15.6,
        raw_output: 'must never be presented',
      },
    })
    expect(item.detail).not.toContain('\n')
    expect(item.detail?.length).toBeLessThanOrEqual(240)
    expect(item.meta).toBe('16 ms')
  })

  it('shows safe command and created-file summaries', () => {
    const started = presentRunEvent({
      seq: 2,
      event: 'tool.started',
      timestamp: '2026-08-27T10:00:00Z',
      data: { tool_name: 'run_command', argv_summary: 'python hello.py' },
    })
    const completed = presentRunEvent({
      seq: 3,
      event: 'tool.completed',
      timestamp: '2026-08-27T10:00:01Z',
      data: { tool_name: 'write_file', ok: true, result_summary: '创建 hello.py · 428 B' },
    })

    expect(started).toMatchObject({ detail: '命令：python hello.py', detailCode: true })
    expect(completed).toMatchObject({ detail: '创建 hello.py · 428 B', detailCode: true })
  })

  it('shows the latest modification check without changing the tool result summary', () => {
    const events: RunEventEnvelope[] = [
      {
        seq: 1,
        event: 'tool.completed' as const,
        timestamp: '2026-08-27T10:00:00Z',
        data: {
          tool_name: 'write_file',
          ok: true,
          result_summary: '创建 hello.py · 428 B',
          change_check: {
            status: 'needs_check',
            change_version: 1,
            checked_version: null,
            check_kind: null,
            tool_sequence: null,
            exit_code: null,
          },
        },
      },
      {
        seq: 2,
        event: 'tool.completed' as const,
        timestamp: '2026-08-27T10:00:01Z',
        data: {
          tool_name: 'run_command',
          ok: true,
          result_summary: '命令成功结束 · exit 0',
          change_check: {
            status: 'passed',
            change_version: 1,
            checked_version: 1,
            check_kind: 'test',
            tool_sequence: 2,
            exit_code: 0,
          },
        },
      },
    ]

    const check = latestChangeCheck(events)
    expect(check).toMatchObject({ status: 'passed', check_kind: 'test', tool_sequence: 2 })
    expect(presentChangeCheck(check)).toEqual({
      label: '当前修改已通过测试',
      detail: '第 2 次工具调用，退出码 0',
      tone: 'success',
    })
    expect(presentRunEvent(events[1]!).detail).toBe(
      '命令成功结束 · exit 0；当前修改已通过测试',
    )
  })

  it('labels directory creation and file deletion events', () => {
    const directory = presentRunEvent({
      seq: 4,
      event: 'tool.started',
      timestamp: '2026-08-27T10:00:00Z',
      data: { tool_name: 'make_directory', target: 'src/main/java' },
    })
    const deletion = presentRunEvent({
      seq: 5,
      event: 'tool.completed',
      timestamp: '2026-08-27T10:00:01Z',
      data: { tool_name: 'delete_file', ok: true, result_summary: '删除 obsolete.txt · 12 B' },
    })

    expect(directory.title).toBe('创建目录 · make_directory')
    expect(deletion.title).toBe('删除文件 · delete_file已返回')
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
      title: '读取文件 · read_file已返回',
      detail: '检测到完全重复的工具结果，已提示模型调整策略',
      tone: 'warning',
      stage: 'feedback',
    })
  })

  it('labels a model final as awaiting independent verification', () => {
    expect(
      presentRunOutcome({ status: 'completed', reason: 'model_final', error: null }),
    ).toMatchObject({
      title: '模型已结束本次运行',
      statusLabel: '待外部验证',
      reasonLabel: '模型返回最终回答',
      tone: 'neutral',
    })
  })

  it('keeps budget exhaustion separate from successful completion', () => {
    expect(
      presentRunOutcome({
        status: 'budget_exhausted',
        reason: 'token_budget_exceeded',
        error: null,
      }),
    ).toMatchObject({
      statusLabel: '未验证',
      reasonLabel: '达到 Token 上限',
      tone: 'warning',
    })
  })
})
