<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import type { MemoryEntry, MemoryKind } from './types'
import MemoryEditor from './MemoryEditor.vue'

interface EditorState {
  mode: 'create' | 'edit'
  memoryId: string | null
  initial: { kind: MemoryKind; content: string; pinned: boolean }
  sourceRunId: string | null
}

const props = defineProps<{
  workspace: string
  phase: 'idle' | 'loading' | 'ready' | 'error'
  items: MemoryEntry[]
  message: string | null
  busy: string | null
  editor: EditorState | null
  readOnly: boolean
}>()

const emit = defineEmits<{
  close: []
  retry: []
  create: []
  edit: [entry: MemoryEntry]
  'toggle-pinned': [entry: MemoryEntry]
  'toggle-enabled': [entry: MemoryEntry]
  remove: [entry: MemoryEntry]
  purge: []
  save: [value: { kind: MemoryKind; content: string; pinned: boolean }]
  'cancel-editor': []
}>()

const pendingDeleteId = ref<string | null>(null)
const confirmingPurge = ref(false)
const panelElement = ref<HTMLElement | null>(null)
const editorTrigger = ref<HTMLButtonElement | null>(null)
const purgeButton = ref<HTMLButtonElement | null>(null)
const purgeConfirmButton = ref<HTMLButtonElement | null>(null)

function focusPanel(): void {
  panelElement.value?.focus()
}

defineExpose({ focusPanel })

watch(
  () => props.items.map((item) => item.id),
  (ids) => {
    if (pendingDeleteId.value && !ids.includes(pendingDeleteId.value)) {
      pendingDeleteId.value = null
      void nextTick(() => panelElement.value?.focus())
    }
    if (ids.length === 0 && confirmingPurge.value) {
      confirmingPurge.value = false
      void nextTick(() => panelElement.value?.focus())
    }
  },
)

watch(
  () => props.editor,
  (nextEditor, previousEditor) => {
    if (previousEditor && !nextEditor) {
      void nextTick(() => editorTrigger.value?.focus())
    }
  },
)

watch(
  () => props.readOnly,
  (readOnly) => {
    if (!readOnly) return
    if (props.editor) emit('cancel-editor')
    pendingDeleteId.value = null
    confirmingPurge.value = false
    void nextTick(() => panelElement.value?.focus())
  },
)

const enabledCount = computed(() => props.items.filter((item) => item.enabled).length)
const globallyBusy = computed(() => props.busy !== null)
const refreshLocked = computed(() => globallyBusy.value || props.editor !== null)
const mutationsLocked = computed(
  () => globallyBusy.value || props.editor !== null || props.readOnly,
)

const kindLabels: Record<MemoryKind, string> = {
  preference: '偏好',
  fact: '事实',
  decision: '决策',
  note: '备注',
}

function formattedDate(value: string): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '日期未知'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

function requestDelete(entry: MemoryEntry): void {
  if (pendingDeleteId.value === entry.id) {
    emit('remove', entry)
    return
  }
  pendingDeleteId.value = entry.id
}

function requestCreate(event: MouseEvent): void {
  if (event.currentTarget instanceof HTMLButtonElement) editorTrigger.value = event.currentTarget
  emit('create')
}

function requestEdit(entry: MemoryEntry, event: MouseEvent): void {
  if (event.currentTarget instanceof HTMLButtonElement) editorTrigger.value = event.currentTarget
  emit('edit', entry)
}

async function beginPurgeConfirmation(): Promise<void> {
  confirmingPurge.value = true
  await nextTick()
  purgeConfirmButton.value?.focus()
}

async function cancelPurgeConfirmation(): Promise<void> {
  confirmingPurge.value = false
  await nextTick()
  purgeButton.value?.focus()
}
</script>

<template>
  <section
    id="project-memory-panel"
    ref="panelElement"
    class="memory-panel"
    tabindex="-1"
    aria-labelledby="memory-panel-title"
  >
    <header class="memory-panel__header">
      <div>
        <p class="memory-panel__eyebrow mono">PROJECT INDEX · {{ items.length }}</p>
        <h2 id="memory-panel-title">项目记忆</h2>
      </div>
      <button
        class="memory-panel__close"
        type="button"
        aria-label="关闭项目记忆"
        :disabled="globallyBusy"
        @click="emit('close')"
      >
        ×
      </button>
    </header>

    <p class="memory-panel__intro">
      只保存当前工作区的确认信息。启用的记忆会在新任务开始时作为可核实的历史参考。
    </p>
    <p class="memory-panel__workspace mono" :title="workspace">{{ workspace }}</p>

    <p v-if="readOnly" class="memory-panel__readonly" role="status">
      运行期间记忆只读；你仍然可以查看或刷新当前列表。
    </p>

    <div class="memory-panel__toolbar">
      <span>{{ enabledCount }} 条启用</span>
      <div>
        <button type="button" :disabled="refreshLocked" @click="emit('retry')">刷新</button>
        <button type="button" :disabled="mutationsLocked" @click="requestCreate">新增记忆</button>
      </div>
    </div>

    <MemoryEditor
      v-if="editor && !readOnly"
      :mode="editor.mode"
      :initial="editor.initial"
      :source-run-id="editor.sourceRunId"
      :busy="busy === 'saving'"
      @save="emit('save', $event)"
      @cancel="emit('cancel-editor')"
    />

    <div v-if="phase === 'loading'" class="memory-panel__state" role="status" aria-live="polite">
      <span class="memory-panel__loader" aria-hidden="true"></span>
      <p>正在读取项目记忆…</p>
    </div>

    <div v-else-if="phase === 'error'" class="memory-panel__state memory-panel__state--error" role="alert">
      <strong>项目记忆暂不可用</strong>
      <p>{{ message || '请确认本机后端正在运行，然后重试。' }}</p>
      <button type="button" :disabled="refreshLocked" @click="emit('retry')">重新读取</button>
    </div>

    <div v-else-if="phase === 'ready' && items.length === 0" class="memory-panel__state">
      <strong>还没有项目记忆</strong>
      <p>先记录一条稳定约定，例如测试命令、代码风格或已确认的架构决策。</p>
    </div>

    <ol v-else-if="items.length" class="memory-list" aria-label="项目记忆列表">
      <li
        v-for="entry in items"
        :key="entry.id"
        class="memory-card"
        :class="{ 'memory-card--disabled': !entry.enabled, 'memory-card--pinned': entry.pinned }"
      >
        <div class="memory-card__topline">
          <div class="memory-card__meta mono">
            <span>{{ entry.pinned ? 'PINNED' : entry.source === 'run_result' ? 'RUN' : 'MANUAL' }}</span>
            <time :datetime="entry.updated_at">{{ formattedDate(entry.updated_at) }}</time>
          </div>
          <span class="memory-card__tab">{{ kindLabels[entry.kind] }}</span>
        </div>

        <p class="memory-card__content">{{ entry.content }}</p>
        <p v-if="!entry.enabled" class="memory-card__paused">已停用，不会提供给后续任务</p>

        <div class="memory-card__actions">
          <button type="button" :disabled="mutationsLocked" @click="requestEdit(entry, $event)">编辑</button>
          <button type="button" :disabled="mutationsLocked" @click="emit('toggle-pinned', entry)">
            {{ entry.pinned ? '取消置顶' : '置顶' }}
          </button>
          <button type="button" :disabled="mutationsLocked" @click="emit('toggle-enabled', entry)">
            {{ entry.enabled ? '停用' : '启用' }}
          </button>
          <button
            class="memory-card__delete"
            type="button"
            :disabled="mutationsLocked"
            @click="requestDelete(entry)"
          >
            {{ pendingDeleteId === entry.id ? '确认删除' : '删除' }}
          </button>
          <button
            v-if="pendingDeleteId === entry.id"
            type="button"
            :disabled="globallyBusy"
            @click="pendingDeleteId = null"
          >
            取消
          </button>
        </div>
      </li>
    </ol>

    <footer v-if="items.length" class="memory-panel__footer">
      <template v-if="confirmingPurge">
        <p>清空这个工作区的全部记忆？此操作无法撤销。</p>
        <div>
          <button type="button" :disabled="globallyBusy" @click="cancelPurgeConfirmation">取消</button>
          <button
            ref="purgeConfirmButton"
            class="memory-panel__purge-confirm"
            type="button"
            :disabled="mutationsLocked"
            @click="emit('purge')"
          >
            {{ busy === 'purging' ? '正在清空' : '确认清空' }}
          </button>
        </div>
      </template>
      <button
        v-else
        ref="purgeButton"
        type="button"
        :disabled="mutationsLocked"
        @click="beginPurgeConfirmation"
      >
        清空项目记忆
      </button>
    </footer>
  </section>
</template>

<style scoped>
.memory-panel {
  display: grid;
  gap: 15px;
  margin-top: 12px;
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius-panel);
  background: rgba(243, 247, 248, 0.97);
}

.memory-panel__header,
.memory-panel__toolbar,
.memory-card__topline,
.memory-panel__footer,
.memory-panel__footer > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.memory-panel__eyebrow {
  margin: 0 0 4px;
  color: var(--ink-muted);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.11em;
}

h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 640;
  letter-spacing: -0.035em;
}

.memory-panel__close {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  color: var(--ink-soft);
  background: transparent;
  font-size: 22px;
  line-height: 1;
}

.memory-panel__close:hover {
  color: var(--ink);
  background: var(--surface-strong);
}

.memory-panel__intro {
  margin: 0;
  color: var(--ink-soft);
  font-size: 11px;
  line-height: 1.55;
}

.memory-panel__workspace {
  margin: -5px 0 0;
  overflow: hidden;
  color: var(--ink-muted);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.memory-panel__readonly {
  margin: -3px 0 0;
  padding: 9px 11px;
  border-left: 2px solid var(--amber);
  color: #78501e;
  background: var(--amber-soft);
  font-size: 10px;
  line-height: 1.5;
}

.memory-panel__toolbar {
  padding-top: 12px;
  border-top: 1px solid var(--line);
  color: var(--ink-muted);
  font-size: 10px;
}

.memory-panel__toolbar > div,
.memory-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.memory-panel button:not(.memory-panel__close):not(.memory-editor__save) {
  padding: 2px 0;
  color: var(--cobalt);
  background: transparent;
  font-size: 10px;
  font-weight: 650;
}

.memory-panel button:hover:not(:disabled):not(.memory-panel__close):not(.memory-editor__save) {
  color: var(--cobalt-deep);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.memory-panel button:disabled {
  opacity: 0.46;
}

.memory-panel__state {
  display: grid;
  justify-items: start;
  gap: 5px;
  min-height: 104px;
  padding: 18px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius-control);
  color: var(--ink-soft);
  background: rgba(249, 251, 251, 0.65);
  font-size: 11px;
}

.memory-panel__state strong,
.memory-panel__state p {
  margin: 0;
}

.memory-panel__state--error {
  border-color: rgba(199, 75, 80, 0.42);
  color: var(--danger-deep);
  background: var(--danger-soft);
}

.memory-panel__loader {
  width: 18px;
  height: 2px;
  margin: 7px 0 4px;
  background: var(--cobalt);
  animation: memory-loading 950ms var(--ease-out) infinite alternate;
  transform-origin: left;
}

@keyframes memory-loading {
  from { transform: scaleX(0.25); opacity: 0.45; }
  to { transform: scaleX(1); opacity: 1; }
}

.memory-list {
  display: grid;
  gap: 10px;
  padding: 0;
  margin: 0;
  list-style: none;
}

.memory-card {
  position: relative;
  padding: 14px 13px 12px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-left: 3px solid var(--line-strong);
  border-radius: 7px;
  background: var(--surface);
}

.memory-card--pinned {
  border-left-color: var(--cobalt);
}

.memory-card--disabled {
  background: var(--surface-strong);
}

.memory-card__meta {
  display: flex;
  gap: 8px;
  color: var(--ink-muted);
  font-size: 8px;
  letter-spacing: 0.06em;
}

.memory-card__tab {
  padding: 3px 7px;
  border-radius: 0 0 0 5px;
  color: var(--ink-soft);
  background: var(--porcelain-deep);
  font-size: 9px;
  font-weight: 650;
}

.memory-card__content {
  margin: 12px 0;
  color: var(--ink);
  font-size: 11px;
  line-height: 1.62;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.memory-card--disabled .memory-card__content {
  color: var(--ink-muted);
}

.memory-card__paused {
  margin: -4px 0 10px;
  color: var(--amber);
  font-size: 9px;
}

.memory-card__delete,
.memory-panel__purge-confirm {
  color: var(--danger-deep) !important;
}

.memory-panel__footer {
  align-items: flex-start;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.memory-panel__footer p {
  max-width: 22ch;
  margin: 0;
  color: var(--danger-deep);
  font-size: 10px;
}

@media (max-width: 420px) {
  .memory-panel {
    padding: 16px;
  }

  .memory-panel__toolbar,
  .memory-panel__footer {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
