<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useConversationStore } from '../../features/conversations/conversationStore'
import { useWorkspaceStore } from '../../features/workspaces/workspaceStore'
import AppIcon from '../../shared/components/AppIcon.vue'

defineEmits<{ openSidebar: [] }>()

const route = useRoute()
const router = useRouter()
const workspaces = useWorkspaceStore()
const conversations = useConversationStore()
const workspaceId = computed(() => String(route.params.workspaceId ?? ''))
const workspace = computed(() =>
  workspaces.items.find((item) => item.id === workspaceId.value) ?? null,
)

async function createConversation(): Promise<void> {
  if (!workspaceId.value) return
  const conversation = await conversations.create(workspaceId.value)
  if (conversation) {
    await router.push(`/w/${encodeURIComponent(workspaceId.value)}/c/${encodeURIComponent(conversation.id)}`)
  }
}

onMounted(async () => {
  if (workspaces.items.length === 0) await workspaces.load()
  if (workspaceId.value) await conversations.loadList(workspaceId.value)
})
</script>

<template>
  <section class="workspace-view">
    <header class="workspace-header">
      <button class="icon-button mobile-menu" type="button" aria-label="打开侧栏" @click="$emit('openSidebar')">
        <AppIcon name="menu" />
      </button>
      <div>
        <h1>{{ workspace?.display_name ?? '工作区' }}</h1>
        <p>选择会话或开始一个新任务</p>
      </div>
    </header>
    <div class="workspace-gate">
      <span class="gate-symbol" aria-hidden="true">＋</span>
      <h2>创建这个工作区的第一个会话</h2>
      <p>会话会自动保存消息和运行记录；长期记忆仍由你单独确认。</p>
      <button class="primary-button" type="button" @click="createConversation">新建会话</button>
      <p v-if="conversations.error" class="gate-error">{{ conversations.error }}</p>
    </div>
  </section>
</template>

<style scoped>
.workspace-view {
  height: 100%;
}

.workspace-header {
  display: flex;
  height: var(--header-height);
  align-items: center;
  gap: 12px;
  padding: 0 22px;
  border-bottom: 1px solid var(--line);
}

.workspace-header h1,
.workspace-header p {
  margin: 0;
}

.workspace-header h1 {
  font-size: 14px;
  font-weight: 630;
}

.workspace-header p {
  color: var(--ink-muted);
  font-size: 10px;
}

.mobile-menu {
  display: none;
}

.workspace-gate {
  display: flex;
  height: calc(100% - var(--header-height));
  align-items: center;
  justify-content: center;
  flex-direction: column;
  padding: 24px;
  text-align: center;
}

.gate-symbol {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  margin-bottom: 18px;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  color: var(--accent);
  background: var(--surface-subtle);
  font-size: 21px;
}

.workspace-gate h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 630;
}

.workspace-gate p {
  max-width: 450px;
  margin: 9px 0 18px;
  color: var(--ink-muted);
  font-size: 12.5px;
}

.workspace-gate .gate-error {
  color: var(--danger);
}

@media (max-width: 900px) {
  .mobile-menu {
    display: grid;
  }
}
</style>
