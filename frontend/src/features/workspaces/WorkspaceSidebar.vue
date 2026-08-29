<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '../../shared/components/AppIcon.vue'
import { useConversationStore } from '../conversations/store'
import { useMemoryStore } from '../memory/store'
import DirectoryBrowserDialog from './DirectoryBrowserDialog.vue'
import { useWorkspaceStore } from './store'

defineProps<{ mobileOpen: boolean }>()
const emit = defineEmits<{ closeMobile: [] }>()

const route = useRoute()
const router = useRouter()
const workspaces = useWorkspaceStore()
const conversations = useConversationStore()
const memory = useMemoryStore()
const browserOpen = ref(false)
const creatingConversation = ref(false)

defineExpose({ openBrowser: () => { browserOpen.value = true } })

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
      <div class="brand-mark" aria-hidden="true">&gt;_</div>
      <div class="brand-copy">
        <p class="brand-name">Coding Agent</p>
        <p class="brand-caption"><span />Local workbench</p>
      </div>
      <button class="icon-button mobile-close" type="button" aria-label="关闭侧栏" @click="emit('closeMobile')">
        <AppIcon name="close" />
      </button>
    </div>

    <div class="workspace-control">
      <div class="section-label">
        <label for="workspace-select">当前工作区</label>
        <span>{{ workspaces.loading ? '同步中' : `${workspaces.items.length} 个` }}</span>
      </div>
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
      <span class="new-chat-icon"><AppIcon name="plus" /></span>
      <span>{{ creatingConversation ? '正在创建…' : '新建会话' }}</span>
      <kbd>Ctrl N</kbd>
    </button>

    <nav class="conversation-nav" aria-label="当前工作区的会话">
      <div class="section-label conversation-label">
        <span>最近会话</span>
        <span v-if="conversations.loadingList">读取中</span>
      </div>
      <p v-if="routeWorkspaceId && !conversations.loadingList && conversations.items.length === 0" class="sidebar-empty">
        还没有会话。新建会话后即可向 Agent 提交任务。
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
        <span v-if="conversation.active_run_id" class="busy-dot" title="正在运行"><span class="sr-only">正在运行</span></span>
      </RouterLink>
    </nav>

    <div class="sidebar-footer">
      <RouterLink class="footer-action" to="/evaluations" @click="emit('closeMobile')">
        <AppIcon name="beaker" />
        <span>评测结果</span>
      </RouterLink>
      <button type="button" class="footer-action" :disabled="!routeWorkspaceId" @click="showMemory">
        <AppIcon name="memory" />
        <span>工作区记忆</span>
      </button>
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
  color: var(--sidebar-ink);
  background: var(--sidebar);
}

.brand-row {
  display: flex;
  min-height: 76px;
  align-items: center;
  gap: 11px;
  padding: 0 16px;
  border-bottom: 1px solid var(--sidebar-line);
}

.brand-mark {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border: 1px solid rgb(255 255 255 / 16%);
  border-radius: 10px;
  color: #dbe7ff;
  background: #27498f;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
}

.brand-copy {
  min-width: 0;
}

.brand-name,
.brand-caption {
  margin: 0;
}

.brand-name {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.brand-caption {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 1px;
  color: var(--sidebar-muted);
  font-family: var(--font-utility);
  font-size: 9px;
  font-weight: 650;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.brand-caption span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #43ba8e;
  box-shadow: 0 0 0 3px rgb(67 186 142 / 12%);
}

.mobile-close {
  display: none;
  margin-left: auto;
  color: var(--sidebar-ink);
}

.mobile-close:hover {
  background: var(--sidebar-hover);
}

.workspace-control {
  padding: 18px 14px 10px;
}

.section-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 2px 8px;
  color: var(--sidebar-muted);
  font-family: var(--font-utility);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

.workspace-select-row {
  display: flex;
  gap: 8px;
}

.workspace-select-row select {
  min-width: 0;
  height: 44px;
  flex: 1;
  padding: 0 32px 0 12px;
  border: 1px solid var(--sidebar-line);
  border-radius: 9px;
  color: var(--sidebar-ink);
  background: var(--sidebar-raised);
  font-size: 13px;
}

.workspace-select-row option {
  color: var(--ink);
  background: var(--surface);
}

.add-workspace {
  border: 1px solid var(--sidebar-line);
  color: #c7d2e2;
  background: var(--sidebar-raised);
}

.add-workspace:hover:not(:disabled) {
  color: white;
  background: var(--sidebar-active);
}

.sidebar-error {
  margin: 8px 2px 0;
  color: #ff9ca6;
  font-size: 11px;
}

.new-chat-button {
  display: flex;
  min-height: 46px;
  align-items: center;
  gap: 9px;
  margin: 6px 14px 22px;
  padding: 0 10px;
  border: 1px solid rgb(123 157 231 / 35%);
  border-radius: 10px;
  color: white;
  background: #27498f;
  text-align: left;
}

.new-chat-button:hover:not(:disabled) {
  background: #3159aa;
}

.new-chat-button:disabled {
  opacity: 0.45;
}

.new-chat-icon {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: 6px;
  background: rgb(255 255 255 / 10%);
}

.new-chat-icon :deep(svg) {
  width: 14px;
  height: 14px;
}

.new-chat-button > span:nth-child(2) {
  flex: 1;
  font-size: 13px;
  font-weight: 650;
}

kbd {
  color: #b7c5da;
  font-family: var(--font-utility);
  font-size: 9px;
}

.conversation-nav {
  min-height: 0;
  flex: 1;
  padding: 0 9px;
  overflow-y: auto;
}

.conversation-label {
  margin-inline: 7px;
}

.conversation-link {
  display: flex;
  min-height: 52px;
  align-items: center;
  gap: 10px;
  margin-bottom: 3px;
  padding: 7px 10px;
  border: 1px solid transparent;
  border-radius: 9px;
  color: #b9c4d3;
  text-decoration: none;
}

.conversation-link:hover {
  color: white;
  background: var(--sidebar-raised);
}

.conversation-link.router-link-active {
  border-color: rgb(255 255 255 / 7%);
  color: white;
  background: var(--sidebar-active);
}

.conversation-link :deep(svg) {
  width: 16px;
  height: 16px;
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
  font-size: 13px;
  font-weight: 550;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-time {
  color: var(--sidebar-muted);
  font-family: var(--font-utility);
  font-size: 10px;
}

.busy-dot {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: #7aa2ff;
  box-shadow: 0 0 0 3px rgb(122 162 255 / 14%);
}

.sidebar-empty {
  margin: 18px 10px;
  color: var(--sidebar-muted);
  font-size: 12px;
  line-height: 1.6;
}

.sidebar-footer {
  padding: 12px 12px 16px;
  border-top: 1px solid var(--sidebar-line);
}

.footer-action {
  display: flex;
  width: 100%;
  min-height: 44px;
  align-items: center;
  gap: 10px;
  padding: 0 9px;
  border-radius: 9px;
  color: #c9d3e1;
  background: transparent;
  font-size: 13px;
  text-align: left;
  text-decoration: none;
}

.footer-action:hover:not(:disabled) {
  color: white;
  background: var(--sidebar-raised);
}

.footer-action.router-link-active {
  color: white;
  background: var(--sidebar-active);
}

@media (max-width: 900px) {
  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    width: min(var(--sidebar-width), calc(100vw - 48px));
    transform: translateX(-102%);
    box-shadow: var(--shadow-dialog);
    transition: transform 240ms var(--ease-out);
  }

  .sidebar.is-mobile-open {
    transform: translateX(0);
  }

  .mobile-close {
    display: grid;
  }
}
</style>
