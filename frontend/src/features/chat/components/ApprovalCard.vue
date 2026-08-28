<script setup lang="ts">
import type { ApprovalRequest } from '../../../shared/api/types'
import { formatCommandArguments } from '../../permissions/commandDisplay'

defineProps<{
  approval: ApprovalRequest
  busy: boolean
}>()

defineEmits<{
  approve: []
  reject: []
}>()
</script>

<template>
  <section class="approval-card" aria-labelledby="approval-title">
    <div class="approval-heading">
      <span class="approval-mark" aria-hidden="true">!</span>
      <div>
        <h3 id="approval-title">操作需要确认</h3>
        <p>{{ approval.reason }}</p>
      </div>
    </div>
    <pre v-if="approval.argv.length" aria-label="待执行命令的参数数组"><code>{{ formatCommandArguments(approval.argv) }}</code></pre>
    <p v-else class="action-summary">{{ approval.action_summary }}</p>
    <p v-if="approval.tool_name === 'run_command'" class="cwd">工作目录：{{ approval.cwd_label }}</p>
    <div class="approval-actions">
      <button class="secondary-button" type="button" :disabled="busy" @click="$emit('reject')">拒绝</button>
      <button class="primary-button" type="button" :disabled="busy" @click="$emit('approve')">
        {{ busy ? '正在处理…' : '允许本次操作' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.approval-card {
  margin-top: 13px;
  padding: 14px;
  border: 1px solid var(--warning-border);
  border-radius: 9px;
  background: var(--warning-soft);
}

.approval-heading {
  display: flex;
  gap: 10px;
}

.approval-mark {
  display: grid;
  width: 22px;
  height: 22px;
  flex: none;
  place-items: center;
  border-radius: 50%;
  color: white;
  background: var(--warning);
  font-family: var(--font-utility);
  font-size: 12px;
  font-weight: 750;
}

h3,
p {
  margin: 0;
}

h3 {
  font-size: 13px;
  font-weight: 650;
}

.approval-heading p,
.cwd,
.action-summary {
  margin-top: 2px;
  color: var(--ink-soft);
  font-size: 11px;
}

.action-summary {
  margin-top: 10px;
  font-weight: 600;
}

pre {
  max-width: 100%;
  margin: 12px 0 7px;
  padding: 9px 10px;
  overflow-x: auto;
  border: 1px solid rgb(163 111 35 / 22%);
  border-radius: 6px;
  background: rgb(255 255 255 / 60%);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
}

.approval-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
</style>
