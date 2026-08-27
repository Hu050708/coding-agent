<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import type { MemoryKind } from './types'
import { MEMORY_CONTENT_LIMIT, toMemoryDraftContent } from './viewState'

interface EditorValue {
  kind: MemoryKind
  content: string
  pinned: boolean
}

const props = defineProps<{
  mode: 'create' | 'edit'
  initial: EditorValue
  busy: boolean
  sourceRunId?: string | null
}>()

const emit = defineEmits<{
  save: [value: EditorValue]
  cancel: []
}>()

const kind = ref<MemoryKind>('note')
const content = ref('')
const pinned = ref(false)
const contentInput = ref<HTMLTextAreaElement | null>(null)

watch(
  () => props.initial,
  (value) => {
    kind.value = value.kind
    content.value = toMemoryDraftContent(value.content)
    pinned.value = value.pinned
    void nextTick(() => contentInput.value?.focus())
  },
  { deep: true, immediate: true },
)

const canSave = computed(() => content.value.trim().length > 0 && !props.busy)

function submit(): void {
  if (!canSave.value) return
  emit('save', {
    kind: kind.value,
    content: content.value.trim(),
    pinned: pinned.value,
  })
}
</script>

<template>
  <form class="memory-editor" :aria-busy="busy" @submit.prevent="submit">
    <div class="memory-editor__heading">
      <div>
        <p class="memory-editor__eyebrow mono">{{ mode === 'edit' ? 'EDIT INDEX' : 'NEW INDEX' }}</p>
        <h3>{{ mode === 'edit' ? '编辑项目记忆' : '记录项目约定' }}</h3>
      </div>
      <button class="memory-editor__close" type="button" :disabled="busy" @click="emit('cancel')">
        取消
      </button>
    </div>

    <p v-if="sourceRunId" class="memory-editor__source">
      将本次运行结果整理后保存；结果较长时只预填前 2000 个字符，保存前可以删改。
    </p>

    <div class="memory-editor__fields">
      <label>
        <span>类别</span>
        <select v-model="kind" :disabled="busy">
          <option value="preference">偏好</option>
          <option value="fact">事实</option>
          <option value="decision">决策</option>
          <option value="note">备注</option>
        </select>
      </label>

      <label>
        <span>内容</span>
        <textarea
          ref="contentInput"
          v-model="content"
          rows="6"
          :maxlength="MEMORY_CONTENT_LIMIT"
          :disabled="busy"
          placeholder="写下以后执行任务时仍然有用、并且可以核实的信息。"
          aria-describedby="memory-editor-count"
        ></textarea>
      </label>
      <span id="memory-editor-count" class="memory-editor__count mono">
        {{ content.length }}/{{ MEMORY_CONTENT_LIMIT }}
      </span>

      <label class="memory-editor__pin">
        <input v-model="pinned" type="checkbox" :disabled="busy" />
        <span>置顶，在相关记忆中优先使用</span>
      </label>
    </div>

    <button class="memory-editor__save" type="submit" :disabled="!canSave">
      {{ busy ? '正在保存' : mode === 'edit' ? '保存修改' : '保存记忆' }}
    </button>
  </form>
</template>

<style scoped>
.memory-editor {
  display: grid;
  gap: 16px;
  padding: 17px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-control);
  background: var(--surface);
}

.memory-editor__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.memory-editor__eyebrow {
  margin: 0 0 4px;
  color: var(--cobalt);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

h3 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 640;
  letter-spacing: -0.025em;
}

.memory-editor__close {
  padding: 2px 0;
  color: var(--ink-muted);
  background: transparent;
  font-size: 11px;
}

.memory-editor__close:hover:not(:disabled) {
  color: var(--ink);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.memory-editor__source {
  margin: -4px 0 0;
  color: var(--ink-soft);
  font-size: 11px;
  line-height: 1.5;
}

.memory-editor__fields {
  display: grid;
  gap: 12px;
}

.memory-editor__fields > label:not(.memory-editor__pin) {
  display: grid;
  gap: 6px;
  color: var(--ink);
  font-size: 11px;
  font-weight: 650;
}

select,
textarea {
  width: 100%;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  color: var(--ink);
  background: #fff;
  font: inherit;
}

select {
  height: 38px;
  padding: 0 10px;
}

textarea {
  min-height: 116px;
  padding: 9px 10px;
  font-family: var(--font-body);
  font-size: 12px;
  font-weight: 400;
  line-height: 1.55;
  resize: vertical;
}

select:focus,
textarea:focus {
  border-color: var(--cobalt);
  outline: 0;
  box-shadow: 0 0 0 3px rgba(45, 91, 206, 0.13);
}

.memory-editor__count {
  justify-self: end;
  margin-top: -9px;
  color: var(--ink-muted);
  font-size: 9px;
}

.memory-editor__pin {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ink-soft);
  font-size: 11px;
}

.memory-editor__pin input {
  width: 15px;
  height: 15px;
  margin: 0;
  accent-color: var(--cobalt);
}

.memory-editor__save {
  min-height: 38px;
  padding: 0 14px;
  border-radius: 6px;
  color: #f8fbfc;
  background: var(--cobalt);
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 650;
}

.memory-editor__save:hover:not(:disabled) {
  background: var(--cobalt-deep);
}

.memory-editor__save:disabled,
.memory-editor__close:disabled,
select:disabled,
textarea:disabled {
  opacity: 0.5;
}
</style>
