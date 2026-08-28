import { ref } from 'vue'
import { defineStore } from 'pinia'

import { localizedError } from '../../shared/api/http'
import type { ChatMessage, Conversation, PermissionMode } from '../../shared/api/types'
import { conversationApi } from './conversationApi'

export const useConversationStore = defineStore('conversations', () => {
  const items = ref<Conversation[]>([])
  const current = ref<Conversation | null>(null)
  const messages = ref<ChatMessage[]>([])
  const loadingList = ref(false)
  const loadingThread = ref(false)
  const error = ref<string | null>(null)
  let listGeneration = 0
  let threadGeneration = 0

  async function loadList(workspaceId: string): Promise<void> {
    const currentGeneration = ++listGeneration
    loadingList.value = true
    error.value = null
    try {
      const result = await conversationApi.list(workspaceId)
      if (currentGeneration !== listGeneration) return
      items.value = result
    } catch (reason) {
      if (currentGeneration === listGeneration) error.value = localizedError(reason)
    } finally {
      if (currentGeneration === listGeneration) loadingList.value = false
    }
  }

  async function open(conversationId: string): Promise<boolean> {
    const currentGeneration = ++threadGeneration
    loadingThread.value = true
    error.value = null
    try {
      const [conversation, threadMessages] = await Promise.all([
        conversationApi.get(conversationId),
        conversationApi.messages(conversationId),
      ])
      if (currentGeneration !== threadGeneration) return false
      current.value = conversation
      messages.value = [...threadMessages].sort((left, right) => left.seq - right.seq)
      return true
    } catch (reason) {
      if (currentGeneration === threadGeneration) error.value = localizedError(reason)
      return false
    } finally {
      if (currentGeneration === threadGeneration) loadingThread.value = false
    }
  }

  async function create(
    workspaceId: string,
    permissionMode: PermissionMode = 'agent',
  ): Promise<Conversation | null> {
    error.value = null
    try {
      const conversation = await conversationApi.create({
        workspace_id: workspaceId,
        default_permission_mode: permissionMode,
        use_memory: true,
      })
      items.value = [conversation, ...items.value]
      current.value = conversation
      messages.value = []
      return conversation
    } catch (reason) {
      error.value = localizedError(reason)
      return null
    }
  }

  function appendMessages(next: ChatMessage[]): void {
    const merged = new Map(messages.value.map((message) => [message.id, message]))
    for (const message of next) merged.set(message.id, message)
    messages.value = [...merged.values()].sort((left, right) => left.seq - right.seq)
  }

  function clearThread(): void {
    threadGeneration += 1
    current.value = null
    messages.value = []
  }

  return {
    items,
    current,
    messages,
    loadingList,
    loadingThread,
    error,
    loadList,
    open,
    create,
    appendMessages,
    clearThread,
  }
})
