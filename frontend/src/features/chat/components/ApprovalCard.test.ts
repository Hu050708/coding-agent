import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { ApprovalRequest } from '../../../shared/api/types'
import ApprovalCard from './ApprovalCard.vue'

const approval: ApprovalRequest = {
  id: 'approval-1',
  run_id: 'run-1',
  tool_name: 'run_command',
  action_summary: 'python (2 arguments)',
  argv: ['python', 'safe.py\nforged command', '--label=a b'],
  cwd_label: '.',
  reason: '运行目标测试',
  status: 'pending',
  created_at: '2026-08-27T10:00:00Z',
  expires_at: null,
}

describe('ApprovalCard', () => {
  it('shows escaped arguments without injecting a forged command line', () => {
    const wrapper = mount(ApprovalCard, { props: { approval, busy: false } })
    const command = wrapper.get('pre').text()
    expect(command).toContain('"safe.py\\nforged command"')
    expect(command).toContain('"--label=a b"')
    expect(command).not.toContain('safe.py\nforged command')
  })

  it('emits an explicit one-time decision', async () => {
    const wrapper = mount(ApprovalCard, { props: { approval, busy: false } })
    await wrapper.get('button.primary-button').trigger('click')
    expect(wrapper.emitted('approve')).toHaveLength(1)
  })
})
