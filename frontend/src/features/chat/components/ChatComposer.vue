<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import type { PermissionMode } from '../../../shared/api/types'
import AppIcon from '../../../shared/components/AppIcon.vue'
import PermissionPicker from '../../permissions/PermissionPicker.vue'

const props = defineProps<{
  disabled: boolean
  active: boolean
  busy: boolean
  permissionMode: PermissionMode
  useMemory: boolean
}>()

const emit = defineEmits<{
  send: [content: string]
  stop: []
  'update:permissionMode': [value: PermissionMode]
  'update:useMemory': [value: boolean]
}>()

const content = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)
const submittedContent = ref<string | null>(null)

function resize(): void {
  const element = textarea.value
  if (!element) return
  element.style.height = '0px'
  element.style.height = `${Math.min(210, Math.max(56, element.scrollHeight))}px`
}

function submit(): void {
  const value = content.value.trim()
  if (!value || props.disabled || props.active || props.busy) return
  submittedContent.value = value
  emit('send', value)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}

watch(content, resize)
watch(
  () => props.active,
  (isActive) => {
    if (!isActive || submittedContent.value === null) return
    if (content.value.trim() === submittedContent.value) content.value = ''
    submittedContent.value = null
    void nextTick(resize)
  },
)
</script>

<template>
  <div class="composer-zone">
    <div class="composer" :class="{ disabled, active }">
      <label class="sr-only" for="task-input">输入编码任务</label>
      <textarea
        id="task-input"
        ref="textarea"
        v-model="content"
        rows="1"
        maxlength="12000"
        :disabled="disabled"
        :placeholder="disabled ? '先选择工作区并创建会话' : active ? 'Agent 正在处理当前任务，你仍可以准备下一条消息…' : '描述问题、期望结果和不能触碰的范围…'"
        @keydown="onKeydown"
      />
      <div class="composer-toolbar">
        <div class="composer-options">
          <PermissionPicker
            :model-value="permissionMode"
            :disabled="active || disabled"
            @update:model-value="emit('update:permissionMode', $event)"
          />
          <label class="memory-toggle" title="运行开始时读取当前工作区记忆快照">
            <input
              type="checkbox"
              :checked="useMemory"
              :disabled="active || disabled"
              @change="emit('update:useMemory', ($event.target as HTMLInputElement).checked)"
            >
            <span class="toggle-track" aria-hidden="true"><span /></span>
            <span>使用记忆</span>
          </label>
        </div>
        <span v-if="!active" class="shortcut-hint">Enter 发送 · Shift Enter 换行</span>
        <button v-if="active" class="composer-action stop-button" type="button" aria-label="停止任务" :disabled="busy" @click="emit('stop')">
          <AppIcon name="stop" />
          <span>{{ busy ? '停止中' : '停止' }}</span>
        </button>
        <button v-else class="composer-action send-button" type="button" aria-label="发送任务" :disabled="disabled || busy || !content.trim()" @click="submit">
          <span>发送</span>
          <AppIcon name="arrow-up" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.composer-zone {
  position: relative;
  z-index: 4;
  flex: none;
  padding: 12px 24px 18px;
  background: linear-gradient(to bottom, rgb(245 247 250 / 20%), var(--canvas) 25%);
}

.composer {
  width: min(840px, 100%);
  margin: 0 auto;
  overflow: visible;
  border: 1px solid var(--line-strong);
  border-radius: 15px;
  background: var(--surface);
  box-shadow: var(--shadow-composer);
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.composer:focus-within {
  border-color: var(--accent-border);
  box-shadow: 0 0 0 3px var(--accent-soft), var(--shadow-composer);
}

.composer.disabled {
  opacity: 0.62;
}

textarea {
  display: block;
  width: 100%;
  min-height: 64px;
  max-height: 210px;
  padding: 16px 16px 8px;
  overflow-y: auto;
  resize: none;
  border: 0;
  outline: 0;
  color: var(--ink);
  background: transparent;
  font-size: 15px;
  line-height: 1.6;
}

textarea::placeholder {
  color: var(--ink-faint);
}

.composer-toolbar {
  display: flex;
  min-height: 56px;
  align-items: center;
  gap: 10px;
  padding: 8px 9px 9px;
}

.composer-options {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.memory-toggle {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  gap: 7px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--ink-soft);
  background: var(--surface-subtle);
  font-size: 11px;
  font-weight: 650;
  cursor: pointer;
}

.memory-toggle input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}

.toggle-track {
  position: relative;
  width: 24px;
  height: 14px;
  border-radius: 999px;
  background: var(--line-strong);
  transition: background 160ms ease;
}

.toggle-track span {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: white;
  box-shadow: 0 1px 2px rgb(24 32 43 / 20%);
  transition: transform 160ms ease;
}

.memory-toggle input:checked + .toggle-track {
  background: var(--accent);
}

.memory-toggle input:checked + .toggle-track span {
  transform: translateX(10px);
}

.memory-toggle input:focus-visible + .toggle-track {
  outline: 3px solid rgb(49 95 204 / 38%);
  outline-offset: 2px;
}

.shortcut-hint {
  color: var(--ink-faint);
  font-family: var(--font-utility);
  font-size: 9px;
  white-space: nowrap;
}

.composer-action {
  display: inline-flex;
  min-width: 76px;
  min-height: 44px;
  flex: none;
  align-items: center;
  justify-content: center;
  gap: 7px;
  margin-left: auto;
  padding: 0 13px;
  border-radius: 9px;
  color: white;
  background: var(--accent);
  font-size: 12px;
  font-weight: 700;
}

.composer-action :deep(svg) {
  width: 15px;
  height: 15px;
}

.send-button:hover:not(:disabled) {
  background: var(--accent-strong);
}

.composer-action:disabled {
  color: var(--ink-faint);
  background: var(--surface-hover);
}

.stop-button {
  border: 1px solid var(--danger-border);
  color: var(--danger);
  background: var(--danger-soft);
}

.stop-button:hover:not(:disabled) {
  background: #f8dfe4;
}

@media (max-width: 760px) {
  .composer-zone {
    padding: 8px 10px calc(10px + env(safe-area-inset-bottom));
  }

  textarea {
    min-height: 60px;
    padding: 14px 14px 7px;
    font-size: 16px;
  }

  .composer-toolbar {
    align-items: flex-end;
    padding: 7px;
  }

  .shortcut-hint {
    display: none;
  }

  .composer-options {
    gap: 6px;
  }

  .memory-toggle {
    min-width: 44px;
    min-height: 44px;
    justify-content: center;
    padding: 0 9px;
  }

  .memory-toggle > span:last-child {
    display: none;
  }

  .composer-action {
    min-width: 44px;
    width: 44px;
    padding: 0;
  }

  .composer-action span {
    display: none;
  }
}
</style>
