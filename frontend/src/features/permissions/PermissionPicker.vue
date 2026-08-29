<script setup lang="ts">
import { computed, ref } from 'vue'

import type { PermissionMode } from '../../shared/api/types'
import AppIcon from '../../shared/components/AppIcon.vue'

const props = defineProps<{ modelValue: PermissionMode; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: PermissionMode] }>()

const menu = ref<HTMLDetailsElement | null>(null)

const copy: Record<PermissionMode, { label: string; detail: string }> = {
  ask: { label: '严格确认', detail: '修改文件和执行命令前逐次询问' },
  agent: { label: '风险确认', detail: '常规工作区操作自动执行，删除文件与风险命令询问' },
  workspace_full: { label: '工作区自动执行', detail: '在当前工作区内自动执行允许的操作' },
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
      :aria-disabled="disabled || undefined"
      aria-describedby="permission-boundary"
      @click="disabled && $event.preventDefault()"
    >
      <AppIcon name="shield" />
      <span>{{ copy[modelValue].label }}</span>
      <AppIcon class="chevron" name="chevron-down" />
    </summary>
    <div class="permission-menu" role="menu" aria-label="Agent 权限">
      <div class="menu-heading">
        <strong>选择运行权限</strong>
        <span>权限会在任务开始时冻结</span>
      </div>
      <button
        v-for="(item, value) in copy"
        :key="value"
        type="button"
        role="menuitemradio"
        :aria-checked="modelValue === value"
        :class="['permission-option', value, { selected: modelValue === value }]"
        @click="choose(value)"
      >
        <span class="option-mark" aria-hidden="true"><AppIcon v-if="modelValue === value" name="check" /></span>
        <span class="option-copy">
          <strong>{{ item.label }}</strong>
          <small>{{ item.detail }}</small>
        </span>
      </button>
      <p class="menu-boundary">危险、提权和工作区外操作始终禁止。</p>
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
  list-style: none;
}

summary::-webkit-details-marker {
  display: none;
}

summary :deep(svg) {
  width: 14px;
  height: 14px;
}

summary .chevron {
  width: 12px;
  height: 12px;
  color: var(--ink-faint);
  transition: transform 160ms var(--ease-out);
}

details[open] summary .chevron {
  transform: rotate(180deg);
}

.permission-menu {
  position: absolute;
  z-index: 30;
  bottom: calc(100% + 9px);
  left: 0;
  width: min(380px, calc(100vw - 24px));
  padding: 8px;
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  background: var(--surface);
  box-shadow: var(--shadow-composer);
}

.menu-heading {
  display: grid;
  gap: 1px;
  padding: 7px 9px 10px;
}

.menu-heading strong {
  font-size: 12px;
}

.menu-heading span,
.menu-boundary {
  color: var(--ink-muted);
  font-size: 10px;
}

.permission-option {
  display: grid;
  width: 100%;
  min-height: 56px;
  grid-template-columns: 20px 1fr;
  gap: 8px;
  align-items: flex-start;
  padding: 9px;
  border-radius: 8px;
  background: transparent;
  text-align: left;
}

.permission-option:hover,
.permission-option.selected {
  background: var(--surface-hover);
}

.option-mark {
  display: grid;
  width: 18px;
  height: 18px;
  place-items: center;
  margin-top: 1px;
  color: var(--accent);
}

.option-mark :deep(svg) {
  width: 14px;
  height: 14px;
}

.option-copy {
  display: grid;
  gap: 2px;
}

.option-copy strong {
  color: var(--ink);
  font-size: 12px;
  font-weight: 700;
}

.option-copy small {
  color: var(--ink-muted);
  font-size: 10.5px;
  line-height: 1.4;
}

.permission-option.workspace_full strong,
.permission-option.workspace_full small {
  color: var(--warning);
}

.menu-boundary {
  margin: 7px 9px 4px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
  line-height: 1.4;
}

@media (max-width: 640px) {
  summary {
    min-height: 44px;
  }

  .permission-menu {
    position: fixed;
    inset: auto 10px calc(92px + env(safe-area-inset-bottom)) 10px;
    width: auto;
  }
}
</style>
