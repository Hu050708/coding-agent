import { describe, expect, it } from 'vitest'

import {
  MEMORY_CONTENT_LIMIT,
  toMemoryDraftContent,
  toMemoryPanelBusy,
  toMemoryPanelPhase,
} from './viewState'

describe('memory view-state adapter', () => {
  it('maps the data-layer success phase to the panel ready phase', () => {
    expect(toMemoryPanelPhase('success')).toBe('ready')
    expect(toMemoryPanelPhase('loading')).toBe('loading')
    expect(toMemoryPanelPhase('error')).toBe('error')
  })

  it('only exposes an operation name while the data layer is busy', () => {
    expect(toMemoryPanelBusy(true, 'saving')).toBe('saving')
    expect(toMemoryPanelBusy(true, null)).toBe('working')
    expect(toMemoryPanelBusy(false, 'purging')).toBeNull()
  })

  it('never prefills more than the backend limit from a long run result', () => {
    const result = `运行结果:${'界'.repeat(2500)}`

    const draft = toMemoryDraftContent(result)

    expect(draft).toHaveLength(MEMORY_CONTENT_LIMIT)
    expect(draft).toBe(result.slice(0, MEMORY_CONTENT_LIMIT))
  })
})
