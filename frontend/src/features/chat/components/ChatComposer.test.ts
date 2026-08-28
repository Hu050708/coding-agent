import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatComposer from './ChatComposer.vue'

describe('ChatComposer', () => {
  it('submits with Enter and keeps Shift+Enter for a newline', async () => {
    const wrapper = mount(ChatComposer, {
      props: {
        disabled: false,
        active: false,
        busy: false,
        permissionMode: 'agent',
        useMemory: true,
      },
    })
    const textarea = wrapper.get('textarea')
    await textarea.setValue('运行目标测试')
    await textarea.trigger('keydown', { key: 'Enter', shiftKey: false })
    expect(wrapper.emitted('send')?.[0]).toEqual(['运行目标测试'])
    expect((textarea.element as HTMLTextAreaElement).value).toBe('运行目标测试')
    await wrapper.setProps({ active: true })
    expect((textarea.element as HTMLTextAreaElement).value).toBe('')
  })

  it('shows stop instead of send while a run is active', () => {
    const wrapper = mount(ChatComposer, {
      props: {
        disabled: false,
        active: true,
        busy: false,
        permissionMode: 'workspace_full',
        useMemory: false,
      },
    })
    expect(wrapper.find('button[aria-label="停止任务"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-label="发送任务"]').exists()).toBe(false)
  })
})
