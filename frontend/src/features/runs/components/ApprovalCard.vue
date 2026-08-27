<script setup lang="ts">
import { computed } from 'vue'

import type { ApprovalRequest } from '../types'

const props = defineProps<{
  approval: ApprovalRequest
  busy: boolean
}>()

defineEmits<{
  approve: []
  reject: []
}>()

function displayArgument(argument: string): string {
  if (argument.length === 0) return '""'
  if (!/[\s"]/u.test(argument)) return argument
  return `"${argument.replaceAll('"', '\\"')}"`
}

const command = computed(() => props.approval.argv.map(displayArgument).join(' '))
const expiry = computed(() => {
  const value = Date.parse(props.approval.expires_at)
  if (!Number.isFinite(value)) return '有效期未知'
  return `有效至 ${new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(value)}`
})
</script>

<template>
  <section class="approval" aria-labelledby="approval-title">
    <div class="approval__heading">
      <div>
        <p>需要人工决策</p>
        <h2 id="approval-title">批准这条本机命令？</h2>
      </div>
      <span class="approval__expiry mono">{{ expiry }}</span>
    </div>

    <div class="approval__command">
      <span class="approval__cwd mono">{{ approval.cwd }}</span>
      <code>{{ command || '命令参数不可用' }}</code>
    </div>

    <p class="approval__reason">{{ approval.reason }}</p>

    <div class="approval__actions">
      <button class="reject-button" type="button" :disabled="busy" @click="$emit('reject')">
        拒绝
      </button>
      <button class="approve-button" type="button" :disabled="busy" @click="$emit('approve')">
        {{ busy ? '正在提交' : '批准一次' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.approval {
  margin: 28px 0;
  padding: clamp(18px, 2.4vw, 26px);
  border: 1px solid #d8ad75;
  border-radius: var(--radius-panel);
  background: var(--amber-soft);
  box-shadow: var(--shadow-approval);
}

.approval__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.approval__heading p {
  margin: 0 0 5px;
  color: #94580f;
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h2 {
  margin: 0;
  color: var(--ink);
  font-family: var(--font-display);
  font-size: clamp(20px, 2.4vw, 27px);
  font-weight: 640;
  letter-spacing: -0.035em;
}

.approval__expiry {
  color: #7d5b31;
  font-size: 10px;
  white-space: nowrap;
}

.approval__command {
  display: grid;
  gap: 9px;
  margin-top: 20px;
  padding: 14px 16px;
  overflow: hidden;
  border: 1px solid rgba(148, 88, 15, 0.28);
  border-radius: var(--radius-control);
  background: rgba(249, 251, 251, 0.72);
}

.approval__cwd {
  overflow: hidden;
  color: #7d5b31;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

code {
  overflow-wrap: anywhere;
  color: var(--ink);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.approval__reason {
  max-width: 70ch;
  margin: 14px 0 0;
  color: #65451e;
  font-size: 12px;
}

.approval__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.approve-button,
.reject-button {
  min-width: 92px;
  min-height: 40px;
  padding: 0 16px;
  border-radius: var(--radius-control);
  font-weight: 650;
  white-space: nowrap;
  transition:
    transform 150ms var(--ease-out),
    background 150ms var(--ease-out),
    opacity 150ms var(--ease-out);
}

.approve-button {
  color: #f8fbfc;
  background: var(--cobalt);
}

.approve-button:hover:not(:disabled) {
  background: var(--cobalt-deep);
}

.reject-button {
  border: 1px solid #aa7332;
  color: #6d4515;
  background: transparent;
}

.reject-button:hover:not(:disabled) {
  background: rgba(200, 121, 26, 0.1);
}

.approve-button:active:not(:disabled),
.reject-button:active:not(:disabled) {
  transform: translateY(1px);
}

button:disabled {
  opacity: 0.52;
}

@media (max-width: 560px) {
  .approval__heading {
    display: grid;
  }

  .approval__actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
}
</style>
