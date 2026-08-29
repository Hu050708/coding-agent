<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

import type { ApprovalRequest } from '../../runs/types'
import AppIcon from '../../../shared/components/AppIcon.vue'
import { formatCommandArguments } from '../../permissions/commandDisplay'

const props = defineProps<{
  approval: ApprovalRequest
  busy: boolean
}>()

const emit = defineEmits<{
  approve: []
  reject: []
}>()

const rejectButton = ref<HTMLButtonElement | null>(null)

async function focusSafeAction(): Promise<void> {
  await nextTick()
  rejectButton.value?.focus()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    rejectButton.value?.focus()
  }
}

onMounted(() => void focusSafeAction())
watch(() => props.approval.id, () => void focusSafeAction())
</script>

<template>
  <div class="approval-zone">
    <section
      class="approval-card"
      aria-labelledby="approval-title"
      aria-describedby="approval-description"
      @keydown="onKeydown"
    >
      <header class="approval-heading">
        <span class="approval-mark" aria-hidden="true"><AppIcon name="shield" /></span>
        <div class="approval-copy">
          <p class="eyebrow">需要人工确认</p>
          <h2 id="approval-title">允许执行这项操作？</h2>
          <p id="approval-description" class="approval-reason">{{ approval.reason }}</p>
        </div>
        <span class="one-time-label">仅本次</span>
      </header>

      <div class="approval-detail-grid">
        <div class="command-block">
          <div class="command-label">
            <span>{{ approval.tool_name === 'run_command' ? '待执行命令' : '待执行操作' }}</span>
          </div>
          <pre v-if="approval.argv.length" aria-label="待执行命令的参数数组"><code>{{ formatCommandArguments(approval.argv) }}</code></pre>
          <p v-else class="action-summary">{{ approval.action_summary }}</p>
        </div>

        <dl class="approval-facts">
          <div v-if="approval.tool_name === 'run_command'">
            <dt>工作目录</dt>
            <dd>{{ approval.cwd_label }}</dd>
          </div>
          <div>
            <dt>授权范围</dt>
            <dd>只允许当前这一次操作</dd>
          </div>
        </dl>
      </div>

      <footer class="approval-footer">
        <p class="safety-note">
          拒绝后 Agent 会收到结果并调整方案。
        </p>
        <div class="approval-actions">
          <button ref="rejectButton" class="approval-decision reject" type="button" :disabled="busy" @click="emit('reject')">
            拒绝
          </button>
          <button class="approval-decision approve" type="button" :disabled="busy" @click="emit('approve')">
            {{ busy ? '正在处理…' : '允许本次操作' }}
          </button>
        </div>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.approval-zone {
  position: relative;
  z-index: 4;
  flex: none;
  padding: 12px 24px 18px;
  background: linear-gradient(to bottom, rgb(245 247 250 / 20%), var(--canvas) 25%);
}

.approval-card {
  width: min(840px, 100%);
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid var(--warning-border);
  border-radius: 15px;
  background: var(--surface);
  box-shadow: var(--shadow-composer);
}

.approval-heading {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 14px 16px 12px;
}

.approval-mark {
  display: grid;
  width: 36px;
  height: 36px;
  flex: none;
  place-items: center;
  border-radius: 9px;
  color: var(--warning);
  background: var(--warning-soft);
}

.approval-mark :deep(svg) {
  width: 18px;
  height: 18px;
}

.approval-copy {
  min-width: 0;
  flex: 1;
}

.eyebrow,
h2,
.approval-reason,
.action-summary,
.safety-note {
  margin: 0;
}

.eyebrow {
  color: var(--warning);
  font-family: var(--font-utility);
  font-size: 9px;
  font-weight: 750;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h2 {
  margin-top: 2px;
  font-size: 16px;
  font-weight: 720;
  letter-spacing: -0.015em;
}

.approval-reason {
  margin-top: 4px;
  color: var(--ink-muted);
  font-size: 11px;
  line-height: 1.45;
}

.one-time-label {
  flex: none;
  margin-top: 2px;
  padding: 4px 7px;
  border: 1px solid var(--warning-border);
  border-radius: 999px;
  color: #8a570d;
  background: var(--warning-soft);
  font-family: var(--font-utility);
  font-size: 9px;
  font-weight: 700;
}

.approval-detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(190px, 0.7fr);
  gap: 10px;
  padding: 0 16px 12px;
}

.command-block {
  overflow: hidden;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  background: #111827;
}

.command-label {
  display: flex;
  align-items: center;
  padding: 7px 10px;
  border-bottom: 1px solid #2b3648;
  color: #9eacc0;
  font-family: var(--font-utility);
  font-size: 9px;
}

pre,
.action-summary {
  max-width: 100%;
  max-height: 92px;
  margin: 0;
  padding: 10px 12px;
  overflow: auto;
  color: #e5edf8;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-all;
}

.approval-facts {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
  margin: 0;
}

.approval-facts > div {
  min-width: 0;
  flex: 1;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-subtle);
}

dt {
  color: var(--ink-muted);
  font-size: 10px;
}

dd {
  margin: 3px 0 0;
  overflow: hidden;
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.approval-footer {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 12px 11px 16px;
  border-top: 1px solid var(--line);
  background: var(--surface-subtle);
}

.safety-note {
  min-width: 0;
  flex: 1;
  color: var(--ink-muted);
  font-size: 10px;
  line-height: 1.4;
}

.approval-actions {
  display: flex;
  flex: none;
  gap: 10px;
}

.approval-decision {
  min-width: 112px;
  min-height: 40px;
  padding: 0 14px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  font-size: 12px;
  font-weight: 700;
}

.approval-decision.reject {
  color: var(--ink);
  background: var(--surface);
}

.approval-decision.approve {
  border-color: var(--warning-border);
  color: #744506;
  background: var(--warning-soft);
}

.approval-decision:hover:not(:disabled) {
  box-shadow: inset 0 0 0 1px currentColor;
}

@media (max-width: 640px) {
  .approval-zone {
    padding: 8px 10px calc(10px + env(safe-area-inset-bottom));
  }

  .approval-heading {
    padding: 12px;
  }

  .approval-detail-grid {
    grid-template-columns: 1fr;
    padding: 0 12px 10px;
  }

  .approval-facts {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .approval-footer {
    align-items: stretch;
    flex-direction: column;
    gap: 8px;
    padding: 10px 12px 12px;
  }

  .approval-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .approval-decision {
    min-width: 0;
  }
}
</style>
