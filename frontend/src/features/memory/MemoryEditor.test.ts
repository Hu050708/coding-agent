import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MemoryEditor from './MemoryEditor.vue'

describe('MemoryEditor', () => {
  it('caps programmatic run-result content and emits an editable confirmation', async () => {
    const wrapper = mount(MemoryEditor, {
      props: {
        mode: 'create',
        initial: { kind: 'note', content: '结'.repeat(2400), pinned: false },
        sourceRunId: 'run-1',
        busy: false,
      },
    })

    const textarea = wrapper.get('textarea')
    expect((textarea.element as HTMLTextAreaElement).value).toHaveLength(2000)
    await textarea.setValue('测试命令固定为 pytest。')
    await wrapper.get('select').setValue('decision')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('save')?.[0]).toEqual([
      { kind: 'decision', content: '测试命令固定为 pytest。', pinned: true },
    ])
  })
})
