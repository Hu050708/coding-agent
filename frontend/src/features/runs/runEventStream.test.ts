import { describe, expect, it } from 'vitest'

import { openRunEventStream, parseRunEvent, type EventSourceLike } from './runEventStream'

class FakeEventSource implements EventSourceLike {
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  readonly listeners = new Map<string, EventListener[]>()
  closed = false

  addEventListener(type: string, listener: EventListener): void {
    const listeners = this.listeners.get(type) ?? []
    listeners.push(listener)
    this.listeners.set(type, listeners)
  }

  emit(type: string, data: string): void {
    const event = new MessageEvent(type, { data })
    for (const listener of this.listeners.get(type) ?? []) listener(event)
  }

  close(): void {
    this.closed = true
  }
}

describe('run event stream', () => {
  it('parses the named SSE envelope and rejects unknown events', () => {
    expect(
      parseRunEvent(
        JSON.stringify({
          seq: 4,
          event: 'tool.completed',
          timestamp: '2026-08-27T09:30:00Z',
          data: { tool_name: 'read_file', success: true },
        }),
      ),
    ).toMatchObject({ seq: 4, event: 'tool.completed' })

    expect(
      parseRunEvent(
        JSON.stringify({
          seq: 5,
          event: 'memory.loaded',
          timestamp: '2026-08-27T09:30:00Z',
          data: { status: 'loaded', loaded_count: 2, loaded_ids: ['m1', 'm2'] },
        }),
      ),
    ).toMatchObject({ seq: 5, event: 'memory.loaded' })

    expect(
      parseRunEvent(
        JSON.stringify({ seq: 6, event: 'reasoning.delta', timestamp: 'now', data: {} }),
      ),
    ).toBeNull()
  })

  it('registers custom event names and closes the source', () => {
    const source = new FakeEventSource()
    const received: string[] = []
    const handle = openRunEventStream(
      'run/1',
      {
        onOpen: () => undefined,
        onEvent: (event) => received.push(event.event),
        onError: () => undefined,
      },
      (url) => {
        expect(url).toBe('/api/v1/runs/run%2F1/events')
        return source
      },
    )

    source.emit(
      'run.started',
      JSON.stringify({
        seq: 2,
        event: 'run.started',
        timestamp: '2026-08-27T09:30:00Z',
        data: {},
      }),
    )
    expect(received).toEqual(['run.started'])

    handle.close()
    expect(source.closed).toBe(true)
  })
})
