<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ApprovalCard from '../../features/chat/components/ApprovalCard.vue'
import ChatComposer from '../../features/chat/components/ChatComposer.vue'
import ConversationHeader from '../../features/chat/components/ConversationHeader.vue'
import MessageThread from '../../features/chat/components/MessageThread.vue'
import RunInspector from '../../features/chat/components/RunInspector.vue'
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
const inspectorOpen = ref(
  typeof window !== 'undefined' && window.matchMedia('(min-width: 1241px)').matches,
)
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
    <div class="conversation-pane">
      <ConversationHeader
        v-if="ready && conversations.current"
        :conversation="conversations.current"
        :run="runs.current"
        :stream="runs.stream"
        :inspector-open="inspectorOpen"
        @open-sidebar="$emit('openSidebar')"
        @toggle-inspector="inspectorOpen = !inspectorOpen"
      />
      <header v-else class="loading-header">
        <button class="icon-button mobile-menu" type="button" aria-label="打开工作区与会话" @click="$emit('openSidebar')">
          <AppIcon name="menu" />
        </button>
        <span>正在打开会话…</span>
      </header>

      <div v-if="healthError || serviceBlocked || conversations.error || runs.error" class="recovery-banner" role="alert">
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
        <MessageThread :messages="conversations.messages" :run="runs.current" />
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
        <span class="missing-icon" aria-hidden="true"><AppIcon name="chat" /></span>
        <h2>无法打开这个会话</h2>
        <p>{{ conversations.error || '会话不属于当前工作区，或者已经被删除。' }}</p>
        <button class="secondary-button" type="button" @click="router.push(`/w/${encodeURIComponent(workspaceId)}`)">返回工作区</button>
      </div>
      <div v-else class="thread-loading" aria-live="polite">
        <span class="loading-dot" aria-hidden="true" />
        正在同步消息与运行状态…
      </div>
    </div>

    <button v-if="inspectorOpen" class="inspector-scrim" type="button" aria-label="关闭运行检查器" @click="inspectorOpen = false" />
    <Transition name="inspector">
      <RunInspector
        v-if="inspectorOpen"
        :run="runs.current"
        :events="runs.events"
        :stream="runs.stream"
        :action-busy="actionBusy"
        @close="inspectorOpen = false"
        @stop="runs.cancel"
      />
    </Transition>

    <ApprovalCard
      v-if="runs.current?.pending_approval?.status === 'pending'"
      :approval="runs.current.pending_approval"
      :busy="actionBusy"
      @approve="runs.decide('approve')"
      @reject="runs.decide('reject')"
    />
  </section>
</template>

<style scoped>
.workbench-view {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  background: var(--canvas);
}

.conversation-pane {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}

.loading-header {
  display: flex;
  min-height: var(--header-height);
  flex: none;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  color: var(--ink-muted);
  background: var(--surface);
  font-size: 12px;
}

.mobile-menu {
  display: none;
}

.recovery-banner {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 10px 18px;
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
  font-weight: 700;
}

.recovery-banner p {
  margin-top: 2px;
}

.recovery-banner button {
  display: inline-flex;
  min-height: 38px;
  flex: none;
  align-items: center;
  gap: 6px;
  padding: 0 11px;
  border: 1px solid var(--danger-border);
  border-radius: 8px;
  color: var(--danger);
  background: var(--surface);
  font-size: 11px;
  font-weight: 650;
}

.recovery-banner button :deep(svg) {
  width: 14px;
  height: 14px;
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

.thread-loading {
  gap: 8px;
}

.loading-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 4px var(--accent-soft);
}

.missing-thread {
  flex-direction: column;
  padding: 24px;
  text-align: center;
}

.missing-icon {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  margin-bottom: 14px;
  border: 1px solid var(--line-strong);
  border-radius: 13px;
  color: var(--ink-muted);
  background: var(--surface);
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

.inspector-scrim {
  position: fixed;
  inset: 0;
  z-index: 55;
  display: none;
  background: rgb(15 23 42 / 32%);
}

.inspector-enter-active,
.inspector-leave-active {
  transition: opacity 180ms var(--ease-out);
}

.inspector-enter-from,
.inspector-leave-to {
  opacity: 0;
}

@media (max-width: 1240px) {
  .inspector-scrim {
    display: block;
  }

  .inspector-enter-active,
  .inspector-leave-active {
    transition: opacity 200ms var(--ease-out), transform 240ms var(--ease-out);
  }

  .inspector-enter-from,
  .inspector-leave-to {
    opacity: 0;
    transform: translateX(100%);
  }
}

@media (max-width: 900px) {
  .mobile-menu {
    display: grid;
  }
}

@media (max-width: 640px) {
  .recovery-banner {
    align-items: flex-start;
    padding: 9px 12px;
  }

  .recovery-banner p {
    line-height: 1.4;
  }
}
</style>
