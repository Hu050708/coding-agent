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
  element.style.height = `${Math.min(180, Math.max(48, element.scrollHeight))}px`
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
    <div class="composer" :class="{ disabled }">
      <label class="sr-only" for="task-input">输入任务</label>
      <textarea
        id="task-input"
        ref="textarea"
        v-model="content"
        rows="1"
        maxlength="12000"
        :disabled="disabled"
        :placeholder="disabled ? '先选择工作区并创建会话' : '描述要完成的编码任务…'"
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
            <span>使用记忆</span>
          </label>
        </div>
        <button v-if="active" class="send-button stop-button" type="button" aria-label="停止任务" :disabled="busy" @click="emit('stop')">
          <AppIcon name="stop" />
        </button>
        <button v-else class="send-button" type="button" aria-label="发送任务" :disabled="disabled || busy || !content.trim()" @click="submit">
          <AppIcon name="arrow-up" />
        </button>
      </div>
    </div>
    <p id="permission-boundary" class="boundary-copy">
      权限限制在当前工作区；危险与提权操作始终禁止。代码和测试仍以当前 Windows 用户身份运行，并非系统沙箱。
    </p>
  </div>
</template>

<style scoped>
.composer-zone {
  position: relative;
  z-index: 2;
  flex: none;
  padding: 10px 24px 16px;
  background: var(--surface);
}

.composer {
  width: min(780px, 100%);
  margin: 0 auto;
  overflow: visible;
  border: 1px solid var(--line-strong);
  border-radius: 13px;
  background: var(--surface);
  box-shadow: var(--shadow-composer);
  transition: border-color 140ms ease, box-shadow 140ms ease;
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
  min-height: 54px;
  max-height: 180px;
  padding: 13px 14px 7px;
  overflow-y: auto;
  resize: none;
  border: 0;
  outline: 0;
  background: transparent;
  font-size: 13.5px;
  line-height: 1.55;
}

textarea::placeholder {
  color: var(--ink-faint);
}

.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 8px 8px;
}

.composer-options {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 7px;
}

.memory-toggle {
  display: inline-flex;
  height: 31px;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--ink-soft);
  background: var(--surface-subtle);
  font-size: 11px;
}

.memory-toggle input {
  width: 12px;
  height: 12px;
  margin: 0;
  accent-color: var(--accent);
}

.send-button {
  display: grid;
  width: 32px;
  height: 32px;
  flex: none;
  place-items: center;
  border-radius: 8px;
  color: white;
  background: var(--accent);
}

.send-button:hover:not(:disabled) {
  background: var(--accent-strong);
}

.send-button:disabled {
  color: var(--ink-faint);
  background: var(--surface-hover);
}

.stop-button {
  color: var(--danger);
  background: var(--danger-soft);
}

.boundary-copy {
  width: min(780px, 100%);
  margin: 6px auto 0;
  color: var(--ink-faint);
  font-family: var(--font-utility);
  font-size: 9.5px;
  line-height: 1.4;
  text-align: center;
}

@media (max-width: 640px) {
  .composer-zone {
    padding: 8px 10px 10px;
  }

  .boundary-copy {
    display: none;
  }

  .memory-toggle span {
    display: none;
  }
}
</style>
