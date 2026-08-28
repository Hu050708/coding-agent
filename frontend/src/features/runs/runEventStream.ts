import {
  RUN_EVENT_NAMES,
  type RunEventEnvelope,
  type RunEventName,
} from '../../shared/api/types'

export interface EventSourceLike {
  onopen: ((event: Event) => void) | null
  onerror: ((event: Event) => void) | null
  addEventListener(type: string, listener: EventListener): void
  close(): void
}

export type EventSourceFactory = (url: string) => EventSourceLike

export interface RunEventStreamCallbacks {
  onOpen(): void
  onEvent(envelope: RunEventEnvelope): void
  onError(): void
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isRunEventName(value: unknown): value is RunEventName {
  return typeof value === 'string' && (RUN_EVENT_NAMES as readonly string[]).includes(value)
}

export function parseRunEvent(raw: string, announcedName?: string): RunEventEnvelope | null {
  try {
    const payload: unknown = JSON.parse(raw)
    if (!isRecord(payload)) return null
    const event = isRunEventName(payload.event)
      ? payload.event
      : isRunEventName(announcedName)
        ? announcedName
        : null
    if (event === null || typeof payload.seq !== 'number' || typeof payload.timestamp !== 'string') {
      return null
    }
    return {
      seq: payload.seq,
      event,
      timestamp: payload.timestamp,
      data: isRecord(payload.data) ? payload.data : {},
    }
  } catch {
    return null
  }
}

const defaultFactory: EventSourceFactory = (url) => new EventSource(url)

export function openRunEventStream(
  runId: string,
  callbacks: RunEventStreamCallbacks,
  factory: EventSourceFactory = defaultFactory,
  afterSeq = 0,
): { close(): void } {
  const query = afterSeq > 0 ? `?${new URLSearchParams({ after_seq: String(afterSeq) })}` : ''
  // The endpoint first replays persisted events after this sequence and then
  // stays live. On network reconnect, native EventSource also forwards the
  // latest server `id:` value as Last-Event-ID.
  const source = factory(`/api/v1/runs/${encodeURIComponent(runId)}/events${query}`)
  source.onopen = () => callbacks.onOpen()
  source.onerror = () => callbacks.onError()

  for (const eventName of RUN_EVENT_NAMES) {
    source.addEventListener(eventName, ((event: MessageEvent<string>) => {
      const envelope = parseRunEvent(event.data, eventName)
      if (envelope) callbacks.onEvent(envelope)
    }) as EventListener)
  }

  source.addEventListener('message', ((event: MessageEvent<string>) => {
    const envelope = parseRunEvent(event.data)
    if (envelope) callbacks.onEvent(envelope)
  }) as EventListener)

  return { close: () => source.close() }
}
