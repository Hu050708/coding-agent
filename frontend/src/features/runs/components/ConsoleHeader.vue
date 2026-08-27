<script setup lang="ts">
import { computed } from 'vue'

import type { HealthState } from '../types'

const props = defineProps<{ health: HealthState }>()

const healthLabel = computed(() => {
  if (props.health.phase === 'loading') return '正在连接'
  if (props.health.phase === 'error') return '服务离线'
  if (props.health.data?.status === 'degraded') return '服务受限'
  if (props.health.data?.status === 'ok') return '本机服务在线'
  return '尚未检查'
})

const healthTone = computed(() => {
  if (props.health.phase === 'error') return 'danger'
  if (props.health.data?.status === 'degraded') return 'warning'
  if (props.health.data?.status === 'ok') return 'success'
  return 'neutral'
})
</script>

<template>
  <header class="console-header">
    <div class="brand" aria-label="Coding Agent 本机代理控制台">
      <span class="brand-mark" aria-hidden="true">CL</span>
      <span class="brand-name">Coding Agent</span>
      <span class="brand-context">本机代理控制台</span>
    </div>

    <div class="service-state" :class="`service-state--${healthTone}`" role="status">
      <span class="service-state__signal" aria-hidden="true"></span>
      <span>{{ healthLabel }}</span>
      <span v-if="health.data" class="service-state__capacity mono">
        {{ health.data.active_runs }}/{{ health.data.max_active_runs }} 运行中
      </span>
    </div>
  </header>
</template>

<style scoped>
.console-header {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  min-height: var(--header-height);
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 0 var(--page-gutter);
  border-bottom: 1px solid rgba(174, 191, 197, 0.78);
  background: rgba(243, 247, 248, 0.94);
  backdrop-filter: blur(14px);
}

.brand,
.service-state {
  display: flex;
  align-items: center;
}

.brand {
  gap: 10px;
  min-width: 0;
}

.brand-mark {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid var(--ink);
  border-radius: 7px;
  color: var(--porcelain);
  background: var(--ink);
  font: 700 12px/1 var(--font-mono);
  letter-spacing: -0.04em;
}

.brand-name {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 650;
  letter-spacing: -0.035em;
}

.brand-context {
  padding-left: 10px;
  border-left: 1px solid var(--line-strong);
  color: var(--ink-muted);
  font-size: 12px;
}

.service-state {
  gap: 8px;
  color: var(--ink-soft);
  font-size: 12px;
  white-space: nowrap;
}

.service-state__signal {
  width: 8px;
  height: 8px;
  border: 2px solid currentColor;
  border-radius: 50%;
  background: transparent;
}

.service-state--success {
  color: var(--success);
}

.service-state--warning {
  color: var(--amber);
}

.service-state--danger {
  color: var(--danger);
}

.service-state__capacity {
  margin-left: 4px;
  padding-left: 10px;
  border-left: 1px solid var(--line);
  color: var(--ink-muted);
}

@supports not (backdrop-filter: blur(14px)) {
  .console-header {
    background: var(--porcelain);
  }
}

@media (max-width: 680px) {
  .brand-context,
  .service-state__capacity {
    display: none;
  }

  .console-header {
    gap: 12px;
  }
}
</style>
