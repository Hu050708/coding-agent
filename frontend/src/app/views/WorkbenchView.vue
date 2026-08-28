<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ChatComposer from '../../features/chat/components/ChatComposer.vue'
import ConversationHeader from '../../features/chat/components/ConversationHeader.vue'
import MessageThread from '../../features/chat/components/MessageThread.vue'
import { conversationApi } from '../../features/conversations/conversationApi'
import { useConversationStore } from '../../features/conversations/conversationStore'
import { useRunStore } from '../../features/runs/runStore'
import { useWorkspaceStore } from '../../features/workspaces/workspaceStore'
import { localizedError } from '../../shared/api/http'
import { healthApi } from '../../shared/api/healthApi'
import type { HealthResponse, PermissionMode } from '../../shared/api/types'
import AppIcon from '../../shared/components/AppIcon.vue'

defineEmits<{ openSidebar: [] }>()

const route = useRoute()
const router = useRouter()
const workspaces = useWorkspaceStore()
const conversations = useConversationStore()
const runs = useRunStore()
const permissionMode = ref<PermissionMode>('agent')
const useMemory = ref(true)
const health = ref<HealthResponse | null>(null)
const healthError = ref<string | null>(null)
const loadingHealth = ref(false)
let routeGeneration = 0

const workspaceId = computed(() => String(route.params.workspaceId ?? ''))
const conversationId = computed(() => String(route.params.conversationId ?? ''))
const ready = computed(
  () =>
    conversations.current?.id === conversationId.value &&
    conversations.current.workspace_id === workspaceId.value,
)
const serviceBlocked = computed(
  () => health.value?.database === 'unavailable' || health.value?.provider_configured === false,
)
const actionBusy = computed(() => runs.action !== 'idle')

async function checkHealth(): Promise<void> {
  loadingHealth.value = true
  healthError.value = null
  try {
    health.value = await healthApi.get()
  } catch (reason) {
    health.value = null
    healthError.value = localizedError(reason)
  } finally {
    loadingHealth.value = false
  }
}

async function openRoute(): Promise<void> {
  const generation = ++routeGeneration
  const nextWorkspaceId = workspaceId.value
  const nextConversationId = conversationId.value
  if (!nextWorkspaceId || !nextConversationId) return

  workspaces.select(nextWorkspaceId)
  if (workspaces.items.length === 0) await workspaces.load()
  await conversations.loadList(nextWorkspaceId)
  const opened = await conversations.open(nextConversationId)
  if (generation !== routeGeneration) return
  if (!opened || conversations.current?.workspace_id !== nextWorkspaceId) {
    await runs.restore(null)
    return
  }
  permissionMode.value = conversations.current.default_permission_mode
  useMemory.value = conversations.current.use_memory
  await runs.restore(conversations.current.active_run_id)
}

async function send(content: string): Promise<void> {
  if (!ready.value || serviceBlocked.value) return
  const conversation = conversations.current
  if (!conversation) return
  if (
    conversation.default_permission_mode !== permissionMode.value ||
    conversation.use_memory !== useMemory.value
  ) {
    try {
      const updated = await conversationApi.update(conversation.id, {
        default_permission_mode: permissionMode.value,
        use_memory: useMemory.value,
      })
      conversations.current = updated
    } catch {
      // Run creation is authoritative for these frozen per-run values; failure to
      // update the convenience defaults must not submit different permissions.
    }
  }
  const started = await runs.start(
    conversation.id,
    content,
    permissionMode.value,
    useMemory.value,
  )
  if (started) void conversations.loadList(workspaceId.value)
}

function recover(): void {
  void Promise.all([checkHealth(), openRoute()])
}

watch([workspaceId, conversationId], () => void openRoute(), { immediate: true })
void checkHealth()

onBeforeUnmount(() => {
  routeGeneration += 1
  runs.dispose()
})
</script>

<template>
  <section class="workbench-view">
    <ConversationHeader
      v-if="ready && conversations.current"
      :conversation="conversations.current"
      :run="runs.current"
      :stream="runs.stream"
      @open-sidebar="$emit('openSidebar')"
    />
    <header v-else class="loading-header">
      <button class="icon-button mobile-menu" type="button" aria-label="打开侧栏" @click="$emit('openSidebar')">
        <AppIcon name="menu" />
      </button>
      <span>正在打开会话…</span>
    </header>

    <div v-if="healthError || serviceBlocked || conversations.error || runs.error" class="recovery-banner" role="status">
      <div>
        <strong v-if="health?.database === 'unavailable'">数据库未连接</strong>
        <strong v-else-if="health?.provider_configured === false">模型接口未配置</strong>
        <strong v-else>当前操作没有完成</strong>
        <p>
          {{ healthError || conversations.error || runs.error || (health?.database === 'unavailable'
            ? '启动 coding-agent-postgres 并检查后端数据库配置。'
            : '在后端环境中配置 DeepSeek API Key 后重试。') }}
        </p>
      </div>
      <button type="button" :disabled="loadingHealth" @click="recover">
        <AppIcon name="refresh" />
        重试
      </button>
    </div>

    <template v-if="ready">
      <MessageThread
        :messages="conversations.messages"
        :run="runs.current"
        :events="runs.events"
        :action-busy="actionBusy"
        @approve="runs.decide('approve')"
        @reject="runs.decide('reject')"
      />
      <ChatComposer
        :disabled="!ready || serviceBlocked"
        :active="runs.active"
        :busy="actionBusy"
        :permission-mode="permissionMode"
        :use-memory="useMemory"
        @send="send"
        @stop="runs.cancel"
        @update:permission-mode="permissionMode = $event"
        @update:use-memory="useMemory = $event"
      />
    </template>
    <div v-else-if="!conversations.loadingThread" class="missing-thread">
      <h2>无法打开这个会话</h2>
      <p>{{ conversations.error || '会话不属于当前工作区，或者已经被删除。' }}</p>
      <button class="secondary-button" type="button" @click="router.push(`/w/${encodeURIComponent(workspaceId)}`)">返回工作区</button>
    </div>
    <div v-else class="thread-loading" aria-live="polite">正在同步消息与运行状态…</div>
  </section>
</template>

<style scoped>
.workbench-view {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
}

.loading-header {
  display: flex;
  height: var(--header-height);
  flex: none;
  align-items: center;
  gap: 12px;
  padding: 0 22px;
  border-bottom: 1px solid var(--line);
  color: var(--ink-muted);
  font-size: 12px;
}

.mobile-menu {
  display: none;
}

.recovery-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 9px 20px;
  border-bottom: 1px solid var(--danger-border);
  color: var(--ink-soft);
  background: var(--danger-soft);
}

.recovery-banner strong,
.recovery-banner p {
  margin: 0;
  font-size: 11px;
}

.recovery-banner strong {
  color: var(--danger);
  font-weight: 650;
}

.recovery-banner p {
  margin-top: 1px;
}

.recovery-banner button {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 5px;
  padding: 5px 8px;
  border: 1px solid var(--danger-border);
  border-radius: 6px;
  color: var(--danger);
  background: var(--surface);
  font-size: 10px;
}

.thread-loading,
.missing-thread {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  color: var(--ink-muted);
  font-size: 12px;
}

.missing-thread {
  flex-direction: column;
  text-align: center;
}

.missing-thread h2,
.missing-thread p {
  margin: 0;
}

.missing-thread h2 {
  color: var(--ink);
  font-size: 18px;
}

.missing-thread p {
  margin: 8px 0 18px;
}

@media (max-width: 900px) {
  .mobile-menu {
    display: grid;
  }
}
</style>
