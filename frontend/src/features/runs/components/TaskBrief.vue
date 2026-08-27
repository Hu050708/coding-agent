<script setup lang="ts">
import { computed } from 'vue'

import type { HealthResponse, WorkspaceValidationState } from '../types'
import BudgetDisclosure from './BudgetDisclosure.vue'

const props = defineProps<{
  workspace: string
  task: string
  useMemory: boolean
  validation: WorkspaceValidationState
  memoryAvailable: boolean
  memoryPhase: 'idle' | 'loading' | 'ready' | 'error'
  memoryCount: number
  memoryOpen: boolean
  memoryBusy: boolean
  active: boolean
  canStart: boolean
  action: string
  message: string | null
  limits: HealthResponse | null
}>()

const emit = defineEmits<{
  'update:workspace': [value: string]
  'update:task': [value: string]
  'update:useMemory': [value: boolean]
  validate: []
  'manage-memory': [trigger: HTMLButtonElement]
  start: []
  cancel: []
}>()

const memoryStatus = computed(() => {
  if (!props.memoryAvailable) return '验证路径后可查看和管理'
  if (props.memoryBusy) return '项目记忆操作进行中'
  if (props.memoryPhase === 'loading') return '正在读取项目记忆'
  if (props.memoryPhase === 'error') return '读取失败，可打开面板重试'
  if (props.memoryPhase === 'ready') {
    return props.memoryCount > 0 ? `${props.memoryCount} 条已保存` : '当前工作区还没有记忆'
  }
  return '尚未读取项目记忆'
})

const formLocked = computed(() => props.active || props.action === 'starting')

function manageMemory(event: MouseEvent): void {
  if (event.currentTarget instanceof HTMLButtonElement) {
    emit('manage-memory', event.currentTarget)
  }
}
</script>

<template>
  <aside class="brief-panel" aria-labelledby="brief-title">
    <div class="brief-heading">
      <p class="brief-heading__label">新任务</p>
      <h1 id="brief-title">任务简报</h1>
      <p>设定边界和目标，然后在右侧审阅每一步执行。</p>
    </div>

    <form class="brief-form" @submit.prevent="emit('start')">
      <div class="field-group">
        <div class="field-label-row">
          <label for="workspace">工作区</label>
          <button
            class="text-button"
            type="button"
            :disabled="validation.phase === 'loading' || formLocked"
            @click="emit('validate')"
          >
            {{ validation.phase === 'loading' ? '验证中' : '验证路径' }}
          </button>
        </div>
        <input
          id="workspace"
          :value="workspace"
          type="text"
          autocomplete="off"
          spellcheck="false"
          placeholder="E:\code\my-project"
          :disabled="formLocked"
          :aria-invalid="validation.phase === 'error'"
          aria-describedby="workspace-help workspace-status"
          @input="emit('update:workspace', ($event.target as HTMLInputElement).value)"
        />
        <p id="workspace-help" class="field-help">必须位于服务允许的本机根目录内。</p>
        <p
          v-if="validation.phase === 'success'"
          id="workspace-status"
          class="field-status field-status--success"
          role="status"
        >
          路径有效
        </p>
        <p
          v-else-if="validation.phase === 'error'"
          id="workspace-status"
          class="field-status field-status--error"
          role="alert"
        >
          {{ validation.message }}
        </p>
      </div>

      <div class="field-group">
        <label for="task">任务</label>
        <textarea
          id="task"
          :value="task"
          rows="7"
          maxlength="12000"
          placeholder="描述要完成的代码任务、验收条件和明确限制。"
          :disabled="formLocked"
          @input="emit('update:task', ($event.target as HTMLTextAreaElement).value)"
        ></textarea>
        <p class="field-help field-help--count mono">{{ task.length }}/12000</p>
      </div>

      <section class="memory-control" aria-labelledby="memory-control-title">
        <div class="memory-control__heading">
          <div>
            <p id="memory-control-title">项目记忆</p>
            <span>{{ memoryStatus }}</span>
          </div>
          <button
            class="text-button"
            type="button"
            :disabled="!memoryAvailable || action === 'starting'"
            :aria-expanded="memoryOpen"
            aria-controls="project-memory-panel"
            @click="manageMemory"
          >
            管理
          </button>
        </div>

        <label class="memory-control__toggle">
          <input
            class="sr-only"
            type="checkbox"
            :checked="useMemory"
            :disabled="formLocked"
            @change="emit('update:useMemory', ($event.target as HTMLInputElement).checked)"
          />
          <span class="memory-control__track" aria-hidden="true"><span></span></span>
          <span>
            <strong>使用项目记忆</strong>
            <small>运行开始时读取已启用的历史参考</small>
          </span>
        </label>
      </section>

      <BudgetDisclosure :limits="limits" />

      <p v-if="message" class="brief-error" role="alert">{{ message }}</p>

      <div class="brief-actions">
        <button
          v-if="!active"
          class="primary-button"
          type="submit"
          :disabled="!canStart || memoryBusy"
        >
          {{ memoryBusy ? '等待记忆操作' : action === 'starting' ? '正在启动' : '开始运行' }}
        </button>
        <button
          v-else
          class="danger-button"
          type="button"
          :disabled="action !== 'idle'"
          @click="emit('cancel')"
        >
          {{ action === 'cancelling' ? '正在取消' : '取消运行' }}
        </button>
      </div>
    </form>
  </aside>
</template>

<style scoped>
.brief-panel {
  padding: clamp(22px, 2.2vw, 30px);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-panel);
  background: rgba(249, 251, 251, 0.9);
  box-shadow: var(--shadow-panel);
}

.brief-heading__label {
  margin: 0 0 10px;
  color: var(--cobalt);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(28px, 3vw, 38px);
  font-weight: 640;
  letter-spacing: -0.045em;
  line-height: 1;
}

.brief-heading > p:last-child {
  max-width: 32ch;
  margin: 14px 0 0;
  color: var(--ink-soft);
  font-size: 13px;
}

.brief-form {
  display: grid;
  gap: 22px;
  margin-top: 28px;
}

.field-group {
  display: grid;
  gap: 8px;
}

.field-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

label {
  color: var(--ink);
  font-size: 12px;
  font-weight: 650;
}

input:not(.sr-only),
textarea {
  width: 100%;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-control);
  color: var(--ink);
  background: var(--surface);
  transition:
    border-color 160ms var(--ease-out),
    box-shadow 160ms var(--ease-out),
    background 160ms var(--ease-out);
}

input:not(.sr-only) {
  height: 42px;
  padding: 0 12px;
  font-family: var(--font-mono);
  font-size: 12px;
}

textarea {
  min-height: 148px;
  padding: 11px 12px;
  line-height: 1.55;
  resize: vertical;
}

input:not(.sr-only)::placeholder,
textarea::placeholder {
  color: #72848b;
}

input:not(.sr-only):hover:not(:disabled),
textarea:hover:not(:disabled) {
  border-color: #8ca1a9;
}

input:not(.sr-only):focus,
textarea:focus {
  border-color: var(--cobalt);
  outline: 0;
  box-shadow: 0 0 0 3px rgba(45, 91, 206, 0.14);
}

input:not(.sr-only):disabled,
textarea:disabled {
  color: var(--ink-muted);
  background: var(--surface-strong);
}

.field-help,
.field-status {
  margin: 0;
  font-size: 11px;
}

.field-help {
  color: var(--ink-muted);
}

.field-help--count {
  justify-self: end;
}

.field-status--success {
  color: var(--success);
}

.field-status--error,
.brief-error {
  color: var(--danger-deep);
}

.memory-control {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: rgba(237, 243, 244, 0.6);
}

.memory-control__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.memory-control__heading p,
.memory-control__heading span {
  margin: 0;
}

.memory-control__heading p {
  color: var(--ink);
  font-size: 11px;
  font-weight: 650;
}

.memory-control__heading span {
  display: block;
  margin-top: 2px;
  color: var(--ink-muted);
  font-size: 10px;
}

.memory-control__toggle {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.memory-control__toggle:has(input:disabled) {
  cursor: not-allowed;
  opacity: 0.58;
}

.memory-control__track {
  position: relative;
  width: 30px;
  height: 17px;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  background: var(--surface-strong);
  transition:
    border-color 150ms var(--ease-out),
    background 150ms var(--ease-out);
}

.memory-control__track > span {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: var(--ink-muted);
  transition:
    transform 150ms var(--ease-out),
    background 150ms var(--ease-out);
}

.memory-control__toggle input:checked + .memory-control__track {
  border-color: var(--cobalt);
  background: var(--cobalt-soft);
}

.memory-control__toggle input:checked + .memory-control__track > span {
  background: var(--cobalt);
  transform: translateX(13px);
}

.memory-control__toggle input:focus-visible + .memory-control__track {
  outline: 3px solid rgba(45, 91, 206, 0.28);
  outline-offset: 2px;
}

.memory-control__toggle strong,
.memory-control__toggle small {
  display: block;
}

.memory-control__toggle strong {
  color: var(--ink);
  font-size: 11px;
  font-weight: 650;
}

.memory-control__toggle small {
  margin-top: 1px;
  color: var(--ink-muted);
  font-size: 9px;
  font-weight: 400;
}

.text-button {
  padding: 2px 0;
  color: var(--cobalt);
  background: transparent;
  font-size: 11px;
  font-weight: 650;
}

.text-button:hover:not(:disabled) {
  color: var(--cobalt-deep);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.text-button:disabled {
  color: var(--ink-muted);
}

.brief-error {
  margin: -6px 0 0;
  padding: 10px 12px;
  border-left: 3px solid var(--danger);
  background: var(--danger-soft);
  font-size: 12px;
}

.brief-actions {
  display: grid;
}

.primary-button,
.danger-button {
  min-height: 44px;
  padding: 0 18px;
  border-radius: var(--radius-control);
  color: #f8fbfc;
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 650;
  white-space: nowrap;
  transition:
    transform 150ms var(--ease-out),
    background 150ms var(--ease-out),
    opacity 150ms var(--ease-out);
}

.primary-button {
  background: var(--cobalt);
}

.primary-button:hover:not(:disabled) {
  background: var(--cobalt-deep);
}

.danger-button {
  background: var(--danger);
}

.danger-button:hover:not(:disabled) {
  background: var(--danger-deep);
}

.primary-button:active:not(:disabled),
.danger-button:active:not(:disabled) {
  transform: translateY(1px);
}

.primary-button:disabled,
.danger-button:disabled {
  opacity: 0.48;
}

@media (max-width: 920px) {
  .brief-panel {
    box-shadow: 0 12px 34px rgba(44, 78, 91, 0.08);
  }
}
</style>
