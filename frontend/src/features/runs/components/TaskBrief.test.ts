import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TaskBrief from './TaskBrief.vue'

function props() {
  return {
    workspace: 'E:\\code\\demo',
    task: '检查边界',
    useMemory: true,
    validation: {
      phase: 'success' as const,
      checkedValue: 'E:\\code\\demo',
      data: { valid: true as const, workspace: 'E:\\code\\demo', allowed_root: 'E:\\code' },
      message: null,
    },
    memoryAvailable: true,
    memoryPhase: 'ready' as const,
    memoryCount: 2,
    memoryOpen: false,
    memoryBusy: false,
    active: false,
    canStart: true,
    action: 'idle',
    message: null,
    limits: null,
  }
}

describe('TaskBrief memory controls', () => {
  it('exposes disclosure semantics and locks task inputs while a run starts', async () => {
    const wrapper = mount(TaskBrief, { props: props() })
    const manage = wrapper.findAll('button').find((button) => button.text() === '管理')

    expect(manage?.attributes('aria-expanded')).toBe('false')
    expect(manage?.attributes('aria-controls')).toBe('project-memory-panel')
    await manage?.trigger('click')
    expect(wrapper.emitted('manage-memory')?.[0]?.[0]).toBeInstanceOf(HTMLButtonElement)

    await wrapper.setProps({ memoryBusy: true })
    const start = wrapper.findAll('button').find((button) => button.text() === '等待记忆操作')
    expect(start?.attributes('disabled')).toBeDefined()

    await wrapper.setProps({ memoryOpen: true, memoryBusy: false, action: 'starting' })
    expect(manage?.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('#workspace').attributes('disabled')).toBeDefined()
    expect(wrapper.get('#task').attributes('disabled')).toBeDefined()
    expect(wrapper.get('input[type="checkbox"]').attributes('disabled')).toBeDefined()
  })
})
