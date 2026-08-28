<script setup lang="ts">
import { computed, ref } from 'vue'

import type { PermissionMode } from '../../shared/api/types'

const props = defineProps<{ modelValue: PermissionMode; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: PermissionMode] }>()

const menu = ref<HTMLDetailsElement | null>(null)

const copy: Record<PermissionMode, { label: string; detail: string }> = {
  ask: { label: '请求批准', detail: '修改文件和运行命令前询问' },
  agent: { label: '帮我批准', detail: '仅对检测到的风险操作询问' },
  workspace_full: { label: '工作区完全访问', detail: '在当前工作区内自动执行允许的操作' },
}

const description = computed(() => copy[props.modelValue].detail)

function choose(value: PermissionMode): void {
  emit('update:modelValue', value)
  if (menu.value) menu.value.open = false
}
</script>

<template>
  <details ref="menu" class="permission-picker" :class="{ disabled }">
    <summary
      :title="description"
      aria-describedby="permission-boundary"
      @click="disabled && $event.preventDefault()"
    >
      <span class="permission-dot" :class="modelValue" />
      <span>{{ copy[modelValue].label }}</span>
      <span class="chevron" aria-hidden="true">⌄</span>
    </summary>
    <div class="permission-menu" role="menu" aria-label="Agent 权限">
      <p class="menu-title">如何批准 Agent 操作？</p>
      <button
        v-for="(item, value) in copy"
        :key="value"
        type="button"
        role="menuitemradio"
        :aria-checked="modelValue === value"
        :class="['permission-option', value, { selected: modelValue === value }]"
        @click="choose(value)"
      >
        <span class="option-mark" aria-hidden="true">{{ modelValue === value ? '✓' : '' }}</span>
        <span class="option-copy">
          <strong>{{ item.label }}</strong>
          <small>{{ item.detail }}</small>
        </span>
      </button>
    </div>
  </details>
</template>

<style scoped>
.permission-picker {
  position: relative;
}

.permission-picker.disabled {
  opacity: 0.55;
}

summary {
  display: inline-flex;
  height: 31px;
  align-items: center;
  gap: 6px;
  padding: 0 9px;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--ink-soft);
  background: var(--surface-subtle);
  cursor: pointer;
  font-size: 11px;
  font-weight: 580;
  list-style: none;
}

summary::-webkit-details-marker {
  display: none;
}

summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.permission-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ink-muted);
}

.permission-dot.agent {
  background: var(--accent);
}

.permission-dot.workspace_full {
  background: var(--warning);
}

.chevron {
  color: var(--ink-faint);
  font-size: 13px;
  transform: translateY(-1px);
}

.permission-menu {
  position: absolute;
  z-index: 20;
  bottom: calc(100% + 8px);
  left: 0;
  width: min(360px, calc(100vw - 32px));
  padding: 8px;
  border: 1px solid var(--line-strong);
  border-radius: 11px;
  background: var(--surface);
  box-shadow: var(--shadow-composer);
}

.menu-title {
  margin: 0;
  padding: 5px 8px 8px;
  color: var(--ink-muted);
  font-size: 11px;
}

.permission-option {
  display: grid;
  width: 100%;
  grid-template-columns: 18px 1fr;
  gap: 7px;
  padding: 9px 8px;
  border-radius: 7px;
  text-align: left;
}

.permission-option:hover,
.permission-option.selected {
  background: var(--surface-hover);
}

.option-mark {
  padding-top: 1px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
}

.option-copy {
  display: grid;
  gap: 2px;
}

.option-copy strong {
  color: var(--ink);
  font-size: 12px;
  font-weight: 620;
}

.option-copy small {
  color: var(--ink-muted);
  font-size: 10.5px;
  line-height: 1.35;
}

.permission-option.workspace_full strong,
.permission-option.workspace_full small {
  color: var(--warning);
}
</style>
