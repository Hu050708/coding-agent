<script setup lang="ts">
import { computed } from 'vue'

import type { HealthResponse } from '../types'

const props = defineProps<{ limits: HealthResponse | null }>()

const wallTime = computed(() => {
  if (!props.limits) return '读取中'
  const seconds = props.limits.wall_time_seconds
  if (seconds % 60 === 0) return `${seconds / 60} 分钟`
  return `${seconds} 秒`
})

const compactWallTime = computed(() => {
  if (!props.limits) return '...'
  const seconds = props.limits.wall_time_seconds
  return seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds} sec`
})
</script>

<template>
  <details class="budget">
    <summary>
      <span>运行预算</span>
      <span class="budget__summary mono">
        <template v-if="limits">
          {{ compactWallTime }} / {{ limits.max_model_calls }} model / {{ limits.max_tool_calls }} tools
        </template>
        <template v-else>正在读取服务配置</template>
      </span>
      <span class="budget__chevron" aria-hidden="true"></span>
    </summary>
    <dl class="budget__grid">
      <div>
        <dt>总墙钟</dt>
        <dd class="mono">{{ wallTime }}</dd>
      </div>
      <div>
        <dt>模型调用</dt>
        <dd class="mono">{{ limits ? `${limits.max_model_calls} 次` : '—' }}</dd>
      </div>
      <div>
        <dt>工具调用</dt>
        <dd class="mono">{{ limits ? `${limits.max_tool_calls} 次` : '—' }}</dd>
      </div>
    </dl>
  </details>
</template>

<style scoped>
.budget {
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

summary {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 10px;
  align-items: center;
  padding: 13px 0;
  color: var(--ink-soft);
  font-size: 13px;
  list-style: none;
  cursor: pointer;
}

summary::-webkit-details-marker {
  display: none;
}

.budget__summary {
  overflow: hidden;
  color: var(--ink-muted);
  font-size: 10.5px;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.budget__chevron {
  width: 7px;
  height: 7px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: rotate(45deg) translateY(-2px);
  transition: transform 180ms var(--ease-out);
}

details[open] .budget__chevron {
  transform: rotate(225deg) translate(-1px, -1px);
}

.budget__grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  margin: 0 0 14px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--line);
}

.budget__grid div {
  min-width: 0;
  padding: 9px;
  background: var(--surface);
}

dt {
  color: var(--ink-muted);
  font-size: 10px;
}

dd {
  margin: 4px 0 0;
  color: var(--ink);
  font-size: 12px;
}
</style>
