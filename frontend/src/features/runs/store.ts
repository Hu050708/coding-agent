import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { localizedError } from '../../shared/api/http'
import type { PermissionMode } from '../../shared/api/types'
import type { ChatMessage } from '../conversations/types'
import type { RunEventEnvelope, RunSummary } from './types'
import { useConversationStore } from '../conversations/store'
import { openRunEventStream } from './events'
import { runApi } from './api'

const terminalStatuses = new Set([
  'completed',
  'failed',
  'cancelled',
  'budget_exhausted',
  'interrupted',
])

function requestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  const bytes = new Uint8Array(16)
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes)
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256)
    }
  }
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80
  const value = [...bytes].map((item) => item.toString(16).padStart(2, '0')).join('')
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`
}

export const useRunStore = defineStore('runs', () => {
  const current = ref<RunSummary | null>(null)
  const events = ref<RunEventEnvelope[]>([])
  const stream = ref<'idle' | 'connecting' | 'live' | 'reconnecting' | 'closed'>('idle')
  const action = ref<'idle' | 'starting' | 'cancelling' | 'approving' | 'rejecting'>('idle')
  const error = ref<string | null>(null)
  let generation = 0
  let streamHandle: { close(): void } | null = null

  const active = computed(
    () => current.value !== null && !terminalStatuses.has(current.value.status),
  )

  function closeStream(): void {
    streamHandle?.close()
    streamHandle = null
    if (stream.value !== 'idle') stream.value = 'closed'
  }

  async function refresh(runId = current.value?.id): Promise<void> {
    if (!runId) return
    const currentGeneration = generation
    try {
      const snapshot = await runApi.get(runId)
      if (generation !== currentGeneration || current.value?.id !== runId) return
      current.value = snapshot
      if (terminalStatuses.has(snapshot.status)) {
        closeStream()
        const conversations = useConversationStore()
        if (conversations.current?.id === snapshot.conversation_id) {
          await conversations.open(snapshot.conversation_id)
        }
      }
    } catch (reason) {
      if (generation === currentGeneration) error.value = localizedError(reason)
    }
  }

  function connect(runId: string): void {
    closeStream()
    const connectionGeneration = generation
    stream.value = 'connecting'
    const lastSeq = events.value.at(-1)?.seq ?? 0
    streamHandle = openRunEventStream(
      runId,
      {
        onOpen: () => {
          if (connectionGeneration === generation && current.value?.id === runId) stream.value = 'live'
        },
        onEvent: (event) => {
          if (connectionGeneration !== generation || current.value?.id !== runId) return
          if (!events.value.some((item) => item.seq === event.seq)) {
            events.value = [...events.value, event].sort((left, right) => left.seq - right.seq)
          }
          if (event.event === 'approval.required' || event.event === 'approval.resolved') {
            void refresh(runId)
          }
          if (event.event === 'run.finished' || event.event === 'run.interrupted') {
            void refresh(runId)
          }
        },
        onError: () => {
          if (connectionGeneration !== generation || current.value?.id !== runId) return
          stream.value = active.value ? 'reconnecting' : 'closed'
        },
      },
      undefined,
      lastSeq,
    )
  }

  async function restore(runId: string | null): Promise<void> {
    generation += 1
    closeStream()
    current.value = null
    events.value = []
    error.value = null
    if (!runId) {
      stream.value = 'idle'
      return
    }
    const currentGeneration = generation
    try {
      const run = await runApi.get(runId)
      if (generation !== currentGeneration) return
      current.value = run
      connect(run.id)
    } catch (reason) {
      if (generation === currentGeneration) error.value = localizedError(reason)
    }
  }

  async function start(
    conversationId: string,
    content: string,
    permissionMode: PermissionMode,
    useMemory: boolean,
  ): Promise<boolean> {
    if (!content.trim() || action.value !== 'idle' || active.value) return false
    const conversations = useConversationStore()
    const clientRequestId = requestId()
    action.value = 'starting'
    error.value = null
    generation += 1
    closeStream()
    events.value = []
    const optimistic: ChatMessage = {
      id: `local:${clientRequestId}`,
      conversation_id: conversationId,
      run_id: null,
      role: 'user',
      content: content.trim(),
      seq: Math.max(0, ...conversations.messages.map((message) => message.seq)) + 1,
      created_at: new Date().toISOString(),
    }
    conversations.appendMessages([optimistic])
    const currentGeneration = generation
    try {
      const run = await runApi.create(conversationId, {
        content: content.trim(),
        permission_mode: permissionMode,
        use_memory: useMemory,
        client_request_id: clientRequestId,
      })
      if (generation !== currentGeneration) return false
      current.value = run
      connect(run.id)
      await conversations.open(conversationId)
      return true
    } catch (reason) {
      if (generation === currentGeneration) error.value = localizedError(reason)
      conversations.messages = conversations.messages.filter((message) => message.id !== optimistic.id)
      return false
    } finally {
      if (generation === currentGeneration) action.value = 'idle'
    }
  }

  async function cancel(): Promise<void> {
    const runId = current.value?.id
    if (!runId || !active.value || action.value !== 'idle') return
    action.value = 'cancelling'
    error.value = null
    try {
      current.value = await runApi.cancel(runId)
    } catch (reason) {
      error.value = localizedError(reason)
    } finally {
      action.value = 'idle'
    }
  }

  async function decide(decision: 'approve' | 'reject'): Promise<void> {
    const run = current.value
    const approval = run?.pending_approval
    if (!run || !approval || action.value !== 'idle') return
    action.value = decision === 'approve' ? 'approving' : 'rejecting'
    error.value = null
    try {
      await runApi.decideApproval(run.id, approval.id, decision)
      await refresh(run.id)
    } catch (reason) {
      error.value = localizedError(reason)
    } finally {
      action.value = 'idle'
    }
  }

  function dispose(): void {
    generation += 1
    closeStream()
  }

  return { current, events, stream, action, error, active, restore, start, cancel, decide, refresh, dispose }
})
