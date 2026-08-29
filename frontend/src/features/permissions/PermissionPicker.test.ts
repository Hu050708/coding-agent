import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import PermissionPicker from './PermissionPicker.vue'


describe('PermissionPicker', () => {
  it('shows the three workspace modes and emits the selected mode', async () => {
    const wrapper = mount(PermissionPicker, {
      props: { modelValue: 'agent', disabled: false },
    })

    expect(wrapper.text()).toContain('严格确认')
    expect(wrapper.text()).toContain('风险确认')
    expect(wrapper.text()).toContain('删除文件与风险命令询问')
    expect(wrapper.text()).toContain('工作区自动执行')

    await wrapper.get('button.workspace_full').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['workspace_full'])
  })

  it('does not open while a run has frozen its permission', async () => {
    const wrapper = mount(PermissionPicker, {
      props: { modelValue: 'ask', disabled: true },
    })

    await wrapper.get('summary').trigger('click')
    expect((wrapper.get('details').element as HTMLDetailsElement).open).toBe(false)
  })
})
