<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '../../shared/components/AppIcon.vue'
import { useConversationStore } from '../conversations/conversationStore'
import { useMemoryStore } from '../memory/memoryStore'
import DirectoryBrowserDialog from './DirectoryBrowserDialog.vue'
import { useWorkspaceStore } from './workspaceStore'

defineProps<{ mobileOpen: boolean }>()
const emit = defineEmits<{ closeMobile: [] }>()

const route = useRoute()
const router = useRouter()
const workspaces = useWorkspaceStore()
const conversations = useConversationStore()
const memory = useMemoryStore()
const browserOpen = ref(false)
const creatingConversation = ref(false)

const routeWorkspaceId = computed(() =>
  typeof route.params.workspaceId === 'string' ? route.params.workspaceId : null,
)

function formatRelative(iso: string): string {
  const value = Date.parse(iso)
  if (!Number.isFinite(value)) return ''
  const minutes = Math.floor((Date.now() - value) / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时前`
  return `${Math.floor(minutes / 1440)} 天前`
}

async function selectWorkspace(event: Event): Promise<void> {
  const workspaceId = (event.target as HTMLSelectElement).value
  workspaces.select(workspaceId || null)
  conversations.clearThread()
  if (!workspaceId) {
    await router.push('/')
    return
  }
  await conversations.loadList(workspaceId)
  await router.push(`/w/${encodeURIComponent(workspaceId)}`)
  emit('closeMobile')
}

async function addWorkspace(path: string): Promise<void> {
  const workspace = await workspaces.create(path)
  if (!workspace) return
  browserOpen.value = false
  await conversations.loadList(workspace.id)
  await router.push(`/w/${encodeURIComponent(workspace.id)}`)
  emit('closeMobile')
}

async function newConversation(): Promise<void> {
  const workspaceId = routeWorkspaceId.value ?? workspaces.selectedId
  if (!workspaceId || creatingConversation.value) return
  creatingConversation.value = true
  try {
    const conversation = await conversations.create(workspaceId)
    if (!conversation) return
    await router.push(
      `/w/${encodeURIComponent(workspaceId)}/c/${encodeURIComponent(conversation.id)}`,
    )
    emit('closeMobile')
  } finally {
    creatingConversation.value = false
  }
}

async function showMemory(): Promise<void> {
  const workspaceId = routeWorkspaceId.value ?? workspaces.selectedId
  if (!workspaceId) return
  await memory.show(workspaceId)
  emit('closeMobile')
}

watch(
  routeWorkspaceId,
  async (workspaceId) => {
    workspaces.select(workspaceId)
    if (workspaceId) await conversations.loadList(workspaceId)
    else conversations.clearThread()
  },
  { immediate: true },
)

onMounted(() => void workspaces.load())
</script>

<template>
  <aside class="sidebar" :class="{ 'is-mobile-open': mobileOpen }" aria-label="工作区与会话">
    <div class="brand-row">
      <div class="brand-mark" aria-hidden="true">CA</div>
      <div>
        <p class="brand-name">Coding Agent</p>
        <p class="brand-caption">local workbench</p>
      </div>
      <button class="icon-button mobile-close" type="button" aria-label="关闭侧栏" @click="emit('closeMobile')">
        <AppIcon name="close" />
      </button>
    </div>

    <div class="workspace-control">
      <label for="workspace-select">工作区</label>
      <div class="workspace-select-row">
        <select id="workspace-select" :value="routeWorkspaceId ?? ''" :disabled="workspaces.loading" @change="selectWorkspace">
          <option value="">选择工作区</option>
          <option v-for="workspace in workspaces.items" :key="workspace.id" :value="workspace.id">
            {{ workspace.display_name }}
          </option>
        </select>
        <button class="icon-button add-workspace" type="button" aria-label="添加工作区" title="添加工作区" @click="browserOpen = true">
          <AppIcon name="folder" />
        </button>
      </div>
      <p v-if="workspaces.error" class="sidebar-error">{{ workspaces.error }}</p>
    </div>

    <button class="new-chat-button" type="button" :disabled="!routeWorkspaceId || creatingConversation" @click="newConversation">
      <AppIcon name="plus" />
      <span>{{ creatingConversation ? '正在创建…' : '新建会话' }}</span>
      <kbd>Ctrl N</kbd>
    </button>

    <nav class="conversation-nav" aria-label="当前工作区的会话">
      <div class="section-label">
        <span>最近会话</span>
        <span v-if="conversations.loadingList">同步中</span>
      </div>
      <p v-if="routeWorkspaceId && !conversations.loadingList && conversations.items.length === 0" class="sidebar-empty">
        还没有会话。创建一个开始工作。
      </p>
      <RouterLink
        v-for="conversation in conversations.items"
        :key="conversation.id"
        class="conversation-link"
        :to="`/w/${encodeURIComponent(conversation.workspace_id)}/c/${encodeURIComponent(conversation.id)}`"
        @click="emit('closeMobile')"
      >
        <AppIcon name="chat" />
        <span class="conversation-copy">
          <span class="conversation-title">{{ conversation.title || '新会话' }}</span>
          <span class="conversation-time">{{ formatRelative(conversation.updated_at) }}</span>
        </span>
        <span v-if="conversation.active_run_id" class="busy-dot" title="正在运行" />
      </RouterLink>
    </nav>

    <div class="sidebar-footer">
      <button type="button" class="footer-action" :disabled="!routeWorkspaceId" @click="showMemory">
        <AppIcon name="memory" />
        <span>工作区记忆</span>
      </button>
      <p>记忆只在你确认后保存</p>
    </div>

    <DirectoryBrowserDialog :open="browserOpen" @close="browserOpen = false" @select="addWorkspace" />
  </aside>
</template>

<style scoped>
.sidebar {
  position: relative;
  z-index: 30;
  display: flex;
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
  height: 100dvh;
  flex-direction: column;
  border-right: 1px solid var(--line);
  background: var(--sidebar);
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 68px;
  padding: 0 16px;
}

.brand-mark {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 7px;
  color: white;
  background: var(--accent);
  font-family: var(--font-utility);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.brand-name,
.brand-caption {
  margin: 0;
}

.brand-name {
  font-size: 14px;
  font-weight: 650;
}

.brand-caption {
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.mobile-close {
  display: none;
  margin-left: auto;
}

.workspace-control {
  padding: 8px 12px 12px;
}

.workspace-control label,
.section-label {
  display: flex;
  justify-content: space-between;
  margin: 0 4px 7px;
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.workspace-select-row {
  display: flex;
  gap: 6px;
}

.workspace-select-row select {
  min-width: 0;
  height: 36px;
  flex: 1;
  padding: 0 28px 0 10px;
  border: 1px solid var(--line-strong);
  border-radius: 7px;
  background: var(--surface);
  font-size: 13px;
}

.add-workspace {
  width: 36px;
  height: 36px;
  border: 1px solid var(--line-strong);
  background: var(--surface);
}

.sidebar-error {
  margin: 8px 4px 0;
  color: var(--danger);
  font-size: 11px;
}

.new-chat-button {
  display: flex;
  min-height: 38px;
  align-items: center;
  gap: 9px;
  margin: 4px 12px 18px;
  padding: 0 10px;
  border: 1px solid var(--line-strong);
  border-radius: 7px;
  background: var(--surface);
  text-align: left;
  box-shadow: 0 1px 1px rgb(25 35 50 / 3%);
}

.new-chat-button:hover:not(:disabled) {
  border-color: var(--accent-border);
  background: var(--surface-hover);
}

.new-chat-button span {
  flex: 1;
  font-size: 13px;
  font-weight: 570;
}

kbd {
  color: var(--ink-faint);
  font-family: var(--font-utility);
  font-size: 9px;
}

.conversation-nav {
  min-height: 0;
  flex: 1;
  padding: 0 8px;
  overflow-y: auto;
}

.conversation-link {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 2px;
  padding: 8px 8px;
  border-radius: 7px;
  color: var(--ink-soft);
  text-decoration: none;
}

.conversation-link:hover,
.conversation-link.router-link-active {
  color: var(--ink);
  background: var(--sidebar-active);
}

.conversation-link :deep(svg) {
  width: 15px;
  height: 15px;
  flex: none;
}

.conversation-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}

.conversation-title {
  overflow: hidden;
  font-size: 12.5px;
  font-weight: 520;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-time {
  color: var(--ink-faint);
  font-family: var(--font-utility);
  font-size: 9px;
}

.busy-dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.sidebar-empty {
  margin: 22px 10px;
  color: var(--ink-muted);
  font-size: 12px;
  line-height: 1.55;
}

.sidebar-footer {
  padding: 10px 12px 14px;
  border-top: 1px solid var(--line);
}

.footer-action {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 9px;
  padding: 8px;
  border-radius: 7px;
  background: transparent;
  font-size: 12.5px;
  text-align: left;
}

.footer-action:hover:not(:disabled) {
  background: var(--sidebar-active);
}

.sidebar-footer p {
  margin: 5px 8px 0;
  color: var(--ink-faint);
  font-size: 10px;
}

@media (max-width: 900px) {
  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    width: min(var(--sidebar-width), calc(100vw - 56px));
    transform: translateX(-102%);
    box-shadow: var(--shadow-dialog);
    transition: transform 180ms var(--ease-out);
  }

  .sidebar.is-mobile-open {
    transform: translateX(0);
  }

  .mobile-close {
    display: grid;
  }
}
</style>
