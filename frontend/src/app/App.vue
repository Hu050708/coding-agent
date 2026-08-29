<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useConversationStore } from '../features/conversations/conversationStore'
import MemoryDrawer from '../features/memory/MemoryDrawer.vue'
import WorkspaceSidebar from '../features/workspaces/WorkspaceSidebar.vue'

const route = useRoute()
const router = useRouter()
const conversations = useConversationStore()
const sidebarOpen = ref(false)
const workspaceSidebar = ref<{ openBrowser(): void } | null>(null)

function addWorkspace(): void {
  workspaceSidebar.value?.openBrowser()
}

async function onGlobalKeydown(event: KeyboardEvent): Promise<void> {
  if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'n') return
  const workspaceId = typeof route.params.workspaceId === 'string' ? route.params.workspaceId : null
  if (!workspaceId) return
  event.preventDefault()
  const conversation = await conversations.create(workspaceId)
  if (conversation) {
    await router.push(`/w/${encodeURIComponent(workspaceId)}/c/${encodeURIComponent(conversation.id)}`)
  }
}

window.addEventListener('keydown', onGlobalKeydown)
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKeydown))
</script>

<template>
  <div class="app-shell">
    <WorkspaceSidebar ref="workspaceSidebar" :mobile-open="sidebarOpen" @close-mobile="sidebarOpen = false" />
    <button v-if="sidebarOpen" class="sidebar-scrim" type="button" aria-label="关闭侧栏" @click="sidebarOpen = false" />
    <main class="app-main">
      <RouterView v-slot="{ Component }">
        <component :is="Component" @open-sidebar="sidebarOpen = true" @add-workspace="addWorkspace" />
      </RouterView>
    </main>
    <MemoryDrawer />
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  width: 100%;
  height: 100dvh;
  overflow: hidden;
}

.app-main {
  min-width: 0;
  flex: 1;
  background: var(--canvas);
}

.sidebar-scrim {
  position: fixed;
  inset: 0;
  z-index: 20;
  display: none;
  background: rgb(23 28 38 / 26%);
}

@media (max-width: 900px) {
  .sidebar-scrim {
    display: block;
  }
}
</style>
