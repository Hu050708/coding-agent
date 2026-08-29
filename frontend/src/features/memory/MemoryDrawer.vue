<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import type { MemoryEntry } from './types'
import AppIcon from '../../shared/components/AppIcon.vue'
import { useMemoryStore } from './store'

const memory = useMemoryStore()
const panel = ref<HTMLElement | null>(null)
const draft = ref('')
const kind = ref<MemoryEntry['kind']>('note')
let previousFocus: HTMLElement | null = null

const kindLabels: Record<MemoryEntry['kind'], string> = {
  preference: '偏好',
  fact: '事实',
  decision: '决定',
  note: '备注',
}

async function add(): Promise<void> {
  if (!draft.value.trim()) return
  const created = await memory.create({
    kind: kind.value,
    content: draft.value.trim(),
    pinned: false,
  })
  if (created) draft.value = ''
}

async function clearAll(): Promise<void> {
  if (!window.confirm('清空当前工作区的全部长期记忆？这项操作不能撤销。')) return
  await memory.clearAll()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    memory.close()
    return
  }
  if (event.key !== 'Tab' || !panel.value) return
  const controls = [...panel.value.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])')]
  const first = controls[0]
  const last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

watch(
  () => memory.open,
  async (isOpen) => {
    if (!isOpen) {
      previousFocus?.focus()
      previousFocus = null
      return
    }
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    panel.value?.focus()
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="memory.open" class="drawer-layer" @mousedown.self="memory.close">
        <aside ref="panel" class="memory-drawer" role="dialog" aria-modal="true" aria-labelledby="memory-title" tabindex="-1" @keydown="onKeydown">
          <header>
            <div>
              <p class="eyebrow">Workspace memory</p>
              <h2 id="memory-title">工作区记忆</h2>
            </div>
            <button class="icon-button" type="button" aria-label="关闭工作区记忆" @click="memory.close">
              <AppIcon name="close" />
            </button>
          </header>

          <p class="memory-boundary">
            只有这里确认保存的内容才会进入后续会话。Agent 不能自行写入长期记忆。
          </p>

          <form class="memory-form" @submit.prevent="add">
            <div class="memory-form-row">
              <label>
                <span class="sr-only">记忆类型</span>
                <select v-model="kind">
                  <option v-for="(label, value) in kindLabels" :key="value" :value="value">{{ label }}</option>
                </select>
              </label>
              <button class="primary-button compact" type="submit" :disabled="!draft.trim() || memory.saving">
                保存记忆
              </button>
            </div>
            <textarea v-model="draft" rows="3" maxlength="2000" placeholder="例如：这个项目统一使用 pytest，改动后先运行目标测试。" />
          </form>

          <div class="memory-list" :aria-busy="memory.loading">
            <p v-if="memory.loading" class="memory-empty">正在读取记忆…</p>
            <div v-else-if="memory.error" class="inline-error">
              <p>{{ memory.error }}</p>
              <button type="button" @click="memory.workspaceId && memory.load(memory.workspaceId)">重试</button>
            </div>
            <p v-else-if="memory.items.length === 0" class="memory-empty">还没有长期记忆。保存一条明确、可复用的信息。</p>
            <article v-for="entry in memory.items" v-else :key="entry.id" class="memory-card" :class="{ disabled: !entry.enabled }">
              <div class="memory-meta">
                <span>{{ kindLabels[entry.kind] }}</span>
                <span v-if="entry.pinned">已置顶</span>
              </div>
              <p>{{ entry.content }}</p>
              <div class="memory-actions">
                <button type="button" :disabled="memory.saving" @click="memory.update(entry, { enabled: !entry.enabled })">
                  {{ entry.enabled ? '停用' : '启用' }}
                </button>
                <button type="button" :disabled="memory.saving" @click="memory.update(entry, { pinned: !entry.pinned })">
                  {{ entry.pinned ? '取消置顶' : '置顶' }}
                </button>
                <button class="danger-link" type="button" :disabled="memory.saving" @click="memory.remove(entry)">删除</button>
              </div>
            </article>
            <button
              v-if="memory.items.length > 0"
              class="clear-memory"
              type="button"
              :disabled="memory.saving"
              @click="clearAll"
            >
              清空当前工作区记忆
            </button>
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.drawer-layer {
  position: fixed;
  inset: 0;
  z-index: 70;
  background: rgb(23 28 38 / 24%);
}

.memory-drawer {
  position: absolute;
  inset: 0 0 0 auto;
  width: min(430px, 100%);
  overflow-y: auto;
  border-left: 1px solid var(--line-strong);
  background: var(--surface);
  box-shadow: -18px 0 46px rgb(28 36 51 / 12%);
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 22px 22px 18px;
  border-bottom: 1px solid var(--line);
}

.eyebrow {
  margin: 0 0 2px;
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 10px;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}

h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 630;
}

.memory-boundary {
  margin: 18px 22px;
  padding: 11px 12px;
  border-left: 2px solid var(--accent);
  color: var(--ink-soft);
  background: var(--accent-soft);
  font-size: 12px;
  line-height: 1.55;
}

.memory-form {
  margin: 0 22px 20px;
}

.memory-form-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

select,
textarea {
  border: 1px solid var(--line-strong);
  border-radius: 7px;
  background: var(--surface);
}

select {
  height: 44px;
  padding: 0 28px 0 9px;
  font-size: 12px;
}

textarea {
  width: 100%;
  padding: 10px 11px;
  resize: vertical;
  font-size: 13px;
  line-height: 1.5;
}

.compact {
  min-height: 44px;
  padding: 0 12px;
  font-size: 12px;
}

.memory-list {
  padding: 0 22px 30px;
}

.memory-card {
  padding: 13px 0;
  border-top: 1px solid var(--line);
}

.memory-card.disabled {
  opacity: 0.55;
}

.memory-meta,
.memory-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 10px;
}

.memory-card > p {
  margin: 7px 0 10px;
  font-size: 13px;
  white-space: pre-wrap;
}

.memory-actions button,
.inline-error button {
  min-height: 44px;
  padding: 0 4px;
  color: var(--accent);
  background: transparent;
  font-size: 11px;
}

.memory-actions .danger-link {
  margin-left: auto;
  color: var(--danger);
}

.memory-empty,
.inline-error {
  padding: 34px 8px;
  color: var(--ink-muted);
  text-align: center;
}

.clear-memory {
  width: 100%;
  min-height: 44px;
  margin-top: 12px;
  padding: 9px;
  border: 1px solid var(--danger-border);
  border-radius: 7px;
  color: var(--danger);
  background: transparent;
  font-size: 11px;
}

.inline-error p {
  color: var(--danger);
}

.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 180ms var(--ease-out);
}

.drawer-enter-active .memory-drawer,
.drawer-leave-active .memory-drawer {
  transition: transform 180ms var(--ease-out);
}

.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}

.drawer-enter-from .memory-drawer,
.drawer-leave-to .memory-drawer {
  transform: translateX(28px);
}
</style>
