<script setup lang="ts">
import { computed } from 'vue'

import type { RunSummary } from '../types'

const props = defineProps<{ run: RunSummary }>()
const emit = defineEmits<{ 'save-memory': [trigger: HTMLButtonElement] }>()

const terminal = computed(() =>
  ['completed', 'failed', 'cancelled', 'budget_exhausted'].includes(props.run.status),
)

const heading = computed(() => {
  if (props.run.status === 'completed') return '最终结果'
  if (props.run.status === 'cancelled') return '运行已取消'
  if (props.run.status === 'budget_exhausted') return '运行预算已耗尽'
  return '运行失败'
})

const message = computed(() => {
  if (props.run.error) return `${props.run.error.code}: ${props.run.error.message}`
  if (props.run.reason) return props.run.reason
  if (props.run.status === 'completed' && !props.run.final_content) return '运行完成，但没有返回最终文本。'
  if (props.run.status === 'cancelled') return '本次运行已停止，没有继续执行后续步骤。'
  return null
})

const memoryLabel = computed(() => {
  const memory = props.run.memory
  if (memory.status === 'loaded') return `本次使用了 ${memory.loaded_count} 条项目记忆`
  if (memory.status === 'empty') return '本次未找到可用的项目记忆'
  if (memory.status === 'disabled') return '本次未启用项目记忆'
  if (memory.status === 'unavailable') return '本次运行时项目记忆不可用'
  return '项目记忆正在准备'
})

const canSaveMemory = computed(
  () => props.run.status === 'completed' && Boolean(props.run.final_content?.trim()),
)

function requestSaveMemory(event: MouseEvent): void {
  if (event.currentTarget instanceof HTMLButtonElement) {
    emit('save-memory', event.currentTarget)
  }
}
</script>

<template>
  <section v-if="terminal" class="result" :class="`result--${run.status}`" aria-labelledby="result-title">
    <div class="result__heading">
      <div>
        <p class="result__status mono">{{ run.status }}</p>
        <h2 id="result-title">{{ heading }}</h2>
      </div>
      <span v-if="run.duration_seconds !== null" class="result__duration mono">
        {{ run.duration_seconds.toFixed(1) }} s
      </span>
    </div>

    <p v-if="message" class="result__message">{{ message }}</p>
    <pre v-if="run.final_content" tabindex="0">{{ run.final_content }}</pre>

    <footer class="result__footer">
      <span class="result__memory-note">{{ memoryLabel }}</span>
      <button v-if="canSaveMemory" type="button" @click="requestSaveMemory">
        保存为项目记忆
      </button>
    </footer>
  </section>
</template>

<style scoped>
.result {
  margin-top: 30px;
  padding: 24px 0 10px;
  border-top: 2px solid var(--ink);
}

.result--completed {
  border-top-color: var(--success);
}

.result--failed,
.result--budget_exhausted {
  border-top-color: var(--danger);
}

.result--cancelled {
  border-top-color: var(--amber);
}

.result__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.result__status {
  margin: 0 0 5px;
  color: var(--ink-muted);
  font-size: 10px;
}

h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(23px, 3vw, 31px);
  font-weight: 640;
  letter-spacing: -0.04em;
}

.result__duration {
  color: var(--ink-muted);
  font-size: 11px;
}

.result__message {
  max-width: 72ch;
  margin: 16px 0 0;
  color: var(--ink-soft);
  font-size: 13px;
}

pre {
  max-height: 460px;
  margin: 20px 0 0;
  padding: 18px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  color: var(--ink);
  background: var(--surface);
  font-size: 12px;
  line-height: 1.65;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.result__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 15px;
}

.result__memory-note {
  color: var(--ink-muted);
  font-size: 10px;
}

.result__footer button {
  padding: 5px 0;
  color: var(--cobalt);
  background: transparent;
  font-size: 11px;
  font-weight: 650;
}

.result__footer button:hover {
  color: var(--cobalt-deep);
  text-decoration: underline;
  text-underline-offset: 3px;
}

@media (max-width: 520px) {
  .result__footer {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
