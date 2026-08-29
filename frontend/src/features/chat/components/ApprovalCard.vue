<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

import type { ApprovalRequest } from '../../../shared/api/types'
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

const dialog = ref<HTMLElement | null>(null)
const rejectButton = ref<HTMLButtonElement | null>(null)

async function focusSafeAction(): Promise<void> {
  await nextTick()
  rejectButton.value?.focus()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    rejectButton.value?.focus()
    return
  }
  if (event.key !== 'Tab' || !dialog.value) return
  const controls = [...dialog.value.querySelectorAll<HTMLElement>('button:not(:disabled)')]
  if (controls.length === 0) return
  const first = controls[0]
  const last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

onMounted(() => void focusSafeAction())
watch(() => props.approval.id, () => void focusSafeAction())
</script>

<template>
  <Teleport to="body">
    <div class="approval-backdrop">
      <section
        ref="dialog"
        class="approval-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="approval-title"
        aria-describedby="approval-description"
        @keydown="onKeydown"
      >
        <header class="approval-heading">
          <span class="approval-mark" aria-hidden="true"><AppIcon name="shield" /></span>
          <div>
            <p class="eyebrow">需要人工确认</p>
            <h2 id="approval-title">允许执行这项操作？</h2>
          </div>
        </header>

        <p id="approval-description" class="approval-reason">{{ approval.reason }}</p>

        <div class="command-block">
          <div class="command-label">
            <span>{{ approval.tool_name === 'run_command' ? '待执行命令' : '待执行操作' }}</span>
            <span>仅本次</span>
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

        <p class="safety-note">
          拒绝不会丢失会话；Agent 会收到拒绝结果并决定是否调整方案。
        </p>

        <div class="approval-actions">
          <button ref="rejectButton" class="approval-decision reject" type="button" :disabled="busy" @click="emit('reject')">
            拒绝
          </button>
          <button class="approval-decision approve" type="button" :disabled="busy" @click="emit('approve')">
            {{ busy ? '正在处理…' : '允许本次操作' }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.approval-backdrop {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgb(15 23 42 / 52%);
  backdrop-filter: blur(3px);
}

.approval-dialog {
  width: min(600px, 100%);
  max-height: calc(100dvh - 40px);
  padding: 24px;
  overflow-y: auto;
  border: 1px solid var(--warning-border);
  border-radius: 16px;
  background: var(--surface);
  box-shadow: var(--shadow-dialog);
}

.approval-heading {
  display: flex;
  align-items: center;
  gap: 13px;
}

.approval-mark {
  display: grid;
  width: 42px;
  height: 42px;
  flex: none;
  place-items: center;
  border-radius: 11px;
  color: var(--warning);
  background: var(--warning-soft);
}

.approval-mark :deep(svg) {
  width: 22px;
  height: 22px;
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
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h2 {
  margin-top: 1px;
  font-size: 20px;
  font-weight: 720;
  letter-spacing: -0.015em;
}

.approval-reason {
  margin-top: 16px;
  color: var(--ink-soft);
  font-size: 14px;
  line-height: 1.55;
}

.command-block {
  margin-top: 18px;
  overflow: hidden;
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  background: #111827;
}

.command-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 12px;
  border-bottom: 1px solid #2b3648;
  color: #9eacc0;
  font-family: var(--font-utility);
  font-size: 10px;
}

.command-label span:last-child {
  color: #e6bd70;
}

pre,
.action-summary {
  max-width: 100%;
  margin: 0;
  padding: 14px;
  overflow-x: auto;
  color: #e5edf8;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-all;
}

.approval-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin: 14px 0 0;
}

.approval-facts > div {
  min-width: 0;
  padding: 10px 11px;
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

.safety-note {
  margin-top: 14px;
  color: var(--ink-muted);
  font-size: 11px;
  line-height: 1.5;
}

.approval-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 20px;
}

.approval-decision {
  min-height: 46px;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  font-size: 14px;
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
  .approval-backdrop {
    align-items: end;
    padding: 0;
  }

  .approval-dialog {
    max-height: 92dvh;
    padding: 20px 16px calc(18px + env(safe-area-inset-bottom));
    border-radius: 16px 16px 0 0;
  }

  .approval-facts {
    grid-template-columns: 1fr;
  }

  h2 {
    font-size: 18px;
  }
}
</style>
