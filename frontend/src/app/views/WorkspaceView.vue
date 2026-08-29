<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useConversationStore } from '../../features/conversations/store'
import { useWorkspaceStore } from '../../features/workspaces/store'
import AppIcon from '../../shared/components/AppIcon.vue'

defineEmits<{ openSidebar: [] }>()

const route = useRoute()
const router = useRouter()
const workspaces = useWorkspaceStore()
const conversations = useConversationStore()
const creating = ref(false)
const workspaceId = computed(() => String(route.params.workspaceId ?? ''))
const workspace = computed(() =>
  workspaces.items.find((item) => item.id === workspaceId.value) ?? null,
)

async function createConversation(): Promise<void> {
  if (!workspaceId.value || creating.value) return
  creating.value = true
  try {
    const conversation = await conversations.create(workspaceId.value)
    if (conversation) {
      await router.push(`/w/${encodeURIComponent(workspaceId.value)}/c/${encodeURIComponent(conversation.id)}`)
    }
  } finally {
    creating.value = false
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
      <button class="icon-button mobile-menu" type="button" aria-label="打开工作区与会话" @click="$emit('openSidebar')">
        <AppIcon name="menu" />
      </button>
      <div class="header-title">
        <h1>{{ workspace?.display_name ?? '工作区' }}</h1>
        <p>本地工作区 · {{ conversations.items.length }} 个会话</p>
      </div>
      <span class="workspace-scope"><AppIcon name="shield" />边界已启用</span>
    </header>

    <main class="workspace-content">
      <section class="workspace-hero">
        <span class="hero-icon" aria-hidden="true"><AppIcon name="chat" /></span>
        <p class="eyebrow">NEW CONVERSATION</p>
        <h2>开始一个新的编码任务</h2>
        <p class="hero-description">会话会保存用户消息、Agent 回答和可安全重放的运行轨迹。长期记忆仍然只能由你明确确认后写入。</p>
        <button class="primary-button create-button" type="button" :disabled="creating" @click="createConversation">
          <AppIcon name="plus" />
          {{ creating ? '正在创建…' : '新建会话' }}
        </button>
        <p v-if="conversations.error" class="gate-error" role="alert">{{ conversations.error }}</p>
      </section>

      <aside class="task-guide" aria-label="任务描述建议">
        <div class="guide-heading"><AppIcon name="terminal" /><strong>一条清晰的任务通常包括</strong></div>
        <ol>
          <li><span>1</span><div><strong>当前问题</strong><p>说明错误现象或需要改进的行为。</p></div></li>
          <li><span>2</span><div><strong>预期结果</strong><p>给出可以检查的输出或验收条件。</p></div></li>
          <li><span>3</span><div><strong>修改边界</strong><p>标明不能修改的文件、接口或依赖。</p></div></li>
        </ol>
        <p class="memory-note"><AppIcon name="memory" />工作区记忆可以保存明确、可复用的项目约束。</p>
      </aside>
    </main>
  </section>
</template>

<style scoped>
.workspace-view {
  height: 100%;
  background:
    radial-gradient(circle at 70% 20%, rgb(49 95 204 / 5%), transparent 30%),
    var(--canvas);
}

.workspace-header {
  display: flex;
  min-height: var(--header-height);
  align-items: center;
  gap: 12px;
  padding: 0 22px;
  border-bottom: 1px solid var(--line);
  background: rgb(255 255 255 / 88%);
  backdrop-filter: blur(12px);
}

.header-title {
  min-width: 0;
  flex: 1;
}

.workspace-header h1,
.workspace-header p {
  margin: 0;
}

.workspace-header h1 {
  overflow: hidden;
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-header p {
  color: var(--ink-muted);
  font-size: 10px;
}

.workspace-scope {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 8px;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--success);
  background: var(--success-soft);
  font-size: 10px;
  font-weight: 650;
}

.workspace-scope :deep(svg) {
  width: 13px;
  height: 13px;
}

.mobile-menu {
  display: none;
}

.workspace-content {
  display: grid;
  width: min(960px, calc(100% - 48px));
  height: calc(100% - var(--header-height));
  grid-template-columns: minmax(0, 1.15fr) minmax(300px, 0.85fr);
  place-content: center;
  gap: 18px;
  margin: 0 auto;
  padding: 34px 0;
}

.workspace-hero,
.task-guide {
  border: 1px solid var(--line);
  border-radius: 18px;
  background: var(--surface);
  box-shadow: 0 18px 55px rgb(24 32 43 / 7%);
}

.workspace-hero {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  flex-direction: column;
  padding: 46px;
}

.hero-icon {
  display: grid;
  width: 50px;
  height: 50px;
  place-items: center;
  margin-bottom: 20px;
  border-radius: 14px;
  color: var(--accent);
  background: var(--accent-soft);
}

.eyebrow,
h2,
.hero-description,
.gate-error {
  margin: 0;
}

.eyebrow {
  color: var(--accent);
  font-family: var(--font-utility);
  font-size: 9px;
  font-weight: 750;
  letter-spacing: 0.11em;
}

h2 {
  margin-top: 5px;
  font-family: var(--font-display);
  font-size: 25px;
  font-weight: 740;
  letter-spacing: -0.025em;
}

.hero-description {
  max-width: 520px;
  margin-top: 12px;
  color: var(--ink-muted);
  font-size: 13.5px;
  line-height: 1.7;
}

.create-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 24px;
  box-shadow: 0 8px 20px rgb(49 95 204 / 18%);
}

.create-button :deep(svg) {
  width: 16px;
  height: 16px;
}

.gate-error {
  margin-top: 12px;
  color: var(--danger);
  font-size: 11px;
}

.task-guide {
  padding: 32px 28px;
  color: #d7e1ef;
  background: #111827;
}

.guide-heading {
  display: flex;
  align-items: center;
  gap: 9px;
  padding-bottom: 17px;
  border-bottom: 1px solid #2a3649;
}

.guide-heading :deep(svg) {
  color: #7da4ff;
}

.guide-heading strong {
  color: white;
  font-size: 12px;
}

ol {
  display: grid;
  gap: 20px;
  margin: 24px 0 0;
  padding: 0;
  list-style: none;
}

li {
  display: grid;
  grid-template-columns: 26px 1fr;
  gap: 10px;
}

li > span {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border: 1px solid #34435a;
  border-radius: 7px;
  color: #8fb0ff;
  font-family: var(--font-mono);
  font-size: 9px;
}

li strong,
li p {
  margin: 0;
}

li strong {
  color: #f6f8fb;
  font-size: 12px;
}

li p {
  margin-top: 2px;
  color: #9eacc0;
  font-size: 10.5px;
  line-height: 1.5;
}

.memory-note {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin: 26px 0 0;
  padding-top: 17px;
  border-top: 1px solid #2a3649;
  color: #8f9eb2;
  font-size: 9.5px;
  line-height: 1.45;
}

.memory-note :deep(svg) {
  width: 13px;
  height: 13px;
  flex: none;
}

@media (max-width: 900px) {
  .mobile-menu {
    display: grid;
  }
}

@media (max-width: 760px) {
  .workspace-header {
    padding: 0 10px;
  }

  .workspace-scope {
    display: none;
  }

  .workspace-content {
    display: block;
    width: 100%;
    height: calc(100% - var(--header-height));
    padding: 16px 14px 28px;
    overflow-y: auto;
  }

  .workspace-hero {
    padding: 30px 24px;
  }

  h2 {
    font-size: 22px;
  }

  .create-button {
    width: 100%;
    justify-content: center;
  }

  .task-guide {
    margin-top: 14px;
    padding: 26px 22px;
  }
}
</style>
