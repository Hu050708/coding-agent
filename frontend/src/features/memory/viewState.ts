import type { MemoryPhase } from './types'

export const MEMORY_CONTENT_LIMIT = 2000

export type MemoryPanelPhase = 'idle' | 'loading' | 'ready' | 'error'
export type MemoryBusyAction = 'loading' | 'saving' | 'updating' | 'deleting' | 'purging'

export function toMemoryPanelPhase(phase: MemoryPhase): MemoryPanelPhase {
  return phase === 'success' ? 'ready' : phase
}

export function toMemoryDraftContent(value: string): string {
  return value.slice(0, MEMORY_CONTENT_LIMIT)
}

export function toMemoryPanelBusy(
  busy: boolean,
  action: MemoryBusyAction | null,
): MemoryBusyAction | 'working' | null {
  if (!busy) return null
  return action ?? 'working'
}
