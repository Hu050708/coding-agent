import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import MemoryPanel from './MemoryPanel.vue'
import type { MemoryEntry } from './types'

function entry(): MemoryEntry {
  return {
    id: 'memory-1',
    workspace: 'E:\\code\\demo',
    kind: 'decision',
    content: '后端使用 FastAPI，前端使用 Vue。',
    source: 'manual',
    source_run_id: null,
    pinned: false,
    enabled: true,
    created_at: '2026-08-27T09:00:00Z',
    updated_at: '2026-08-27T09:00:00Z',
  }
}

describe('MemoryPanel', () => {
  it('explains the empty state and requires a second delete action', async () => {
    const wrapper = mount(MemoryPanel, {
      props: {
        workspace: 'E:\\code\\demo',
        phase: 'ready',
        items: [],
        message: null,
        busy: null,
        editor: null,
        readOnly: false,
      },
    })
    expect(wrapper.text()).toContain('还没有项目记忆')

    await wrapper.setProps({ items: [entry()] })
    const deleteButton = wrapper.findAll('button').find((button) => button.text() === '删除')
    expect(deleteButton).toBeDefined()
    await deleteButton?.trigger('click')
    expect(wrapper.emitted('remove')).toBeUndefined()

    const confirmButton = wrapper.findAll('button').find((button) => button.text() === '确认删除')
    await confirmButton?.trigger('click')
    expect(wrapper.emitted('remove')?.[0]?.[0]).toMatchObject({ id: 'memory-1' })
  })

  it('disables card mutations while a data-layer operation is busy', () => {
    const wrapper = mount(MemoryPanel, {
      props: {
        workspace: 'E:\\code\\demo',
        phase: 'ready',
        items: [entry()],
        message: null,
        busy: 'updating',
        editor: null,
        readOnly: false,
      },
    })

    const editButton = wrapper.findAll('button').find((button) => button.text() === '编辑')
    expect(editButton?.attributes('disabled')).toBeDefined()
  })

  it('moves focus into and back out of purge confirmation', async () => {
    const wrapper = mount(MemoryPanel, {
      attachTo: document.body,
      props: {
        workspace: 'E:\\code\\demo',
        phase: 'ready',
        items: [entry()],
        message: null,
        busy: null,
        editor: null,
        readOnly: false,
      },
    })

    const purge = wrapper.findAll('button').find((button) => button.text() === '清空项目记忆')
    await purge?.trigger('click')
    const confirm = wrapper.findAll('button').find((button) => button.text() === '确认清空')
    expect(document.activeElement).toBe(confirm?.element)

    const cancel = wrapper.findAll('button').find((button) => button.text() === '取消')
    await cancel?.trigger('click')
    const restored = wrapper.findAll('button').find((button) => button.text() === '清空项目记忆')
    expect(document.activeElement).toBe(restored?.element)
    wrapper.unmount()
  })

  it('returns focus to the card action after the editor closes', async () => {
    const wrapper = mount(MemoryPanel, {
      attachTo: document.body,
      props: {
        workspace: 'E:\\code\\demo',
        phase: 'ready',
        items: [entry()],
        message: null,
        busy: null,
        editor: null,
        readOnly: false,
      },
    })
    const edit = wrapper.findAll('button').find((button) => button.text() === '编辑')
    await edit?.trigger('click')
    await wrapper.setProps({
      editor: {
        mode: 'edit',
        memoryId: 'memory-1',
        initial: { kind: 'decision', content: '后端使用 FastAPI。', pinned: false },
        sourceRunId: null,
      },
    })
    await wrapper.setProps({ editor: null })
    await nextTick()

    expect(document.activeElement).toBe(edit?.element)
    wrapper.unmount()
  })

  it('keeps refresh available but disables every mutation while a run is active', () => {
    const wrapper = mount(MemoryPanel, {
      props: {
        workspace: 'E:\\code\\demo',
        phase: 'ready',
        items: [entry()],
        message: null,
        busy: null,
        editor: null,
        readOnly: true,
      },
    })

    expect(wrapper.text()).toContain('运行期间记忆只读')
    const button = (label: string) =>
      wrapper.findAll('button').find((candidate) => candidate.text() === label)
    expect(button('刷新')?.attributes('disabled')).toBeUndefined()
    for (const label of ['新增记忆', '编辑', '置顶', '停用', '删除', '清空项目记忆']) {
      expect(button(label)?.attributes('disabled'), label).toBeDefined()
    }
  })
})
