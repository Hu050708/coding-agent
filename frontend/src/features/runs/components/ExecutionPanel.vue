<script setup lang="ts">
import { computed } from 'vue'

import type { HealthResponse, RunConsoleState, RunSummary } from '../types'
import ApprovalCard from './ApprovalCard.vue'
import FinalResult from './FinalResult.vue'
import RunTimeline from './RunTimeline.vue'
import StatusSummary from './StatusSummary.vue'

const props = defineProps<{
  state: RunConsoleState
  active: boolean
  elapsedSeconds: number
  limits: HealthResponse | null
}>()

defineEmits<{
  approve: []
  reject: []
  'save-memory': [run: RunSummary, trigger: HTMLButtonElement]
}>()

const run = computed<RunSummary | null>(() => props.state.run)
const shortRunId = computed(() => {
  if (!run.value) return 'waiting'
  return run.value.run_id.length > 18 ? `${run.value.run_id.slice(0, 8)}...${run.value.run_id.slice(-6)}` : run.value.run_id
})
</script>

<template>
  <main class="execution" aria-labelledby="execution-title">
    <div class="execution__heading">
      <div>
        <p class="execution__label">Run control</p>
        <h1 id="execution-title">运行中枢</h1>
      </div>
      <div class="execution__identity">
        <span>RUN ID</span>
        <code>{{ shortRunId }}</code>
      </div>
    </div>

    <StatusSummary
      :run="run"
      :elapsed-seconds="elapsedSeconds"
      :stream="state.stream"
      :limits="limits"
    />

    <div v-if="state.message" class="execution__message" role="alert">
      <strong>操作未完成</strong>
      <span>{{ state.message }}</span>
    </div>

    <Transition name="approval">
      <ApprovalCard
        v-if="state.pendingApproval"
        :approval="state.pendingApproval"
        :busy="state.action === 'approving' || state.action === 'rejecting'"
        @approve="$emit('approve')"
        @reject="$emit('reject')"
      />
    </Transition>

    <RunTimeline :events="state.timeline" :active="active" />
    <FinalResult v-if="run" :run="run" @save-memory="$emit('save-memory', run, $event)" />
  </main>
</template>

<style scoped>
.execution {
  min-width: 0;
  padding: 4px 0 48px;
}

.execution__heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  min-height: 82px;
  padding-bottom: 18px;
}

.execution__label {
  margin: 0 0 8px;
  color: var(--cobalt);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.execution h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(28px, 3.6vw, 44px);
  font-weight: 640;
  letter-spacing: -0.05em;
  line-height: 0.96;
}

.execution__identity {
  display: grid;
  justify-items: end;
  gap: 4px;
  min-width: 0;
}

.execution__identity span {
  color: var(--ink-muted);
  font-size: 9px;
  letter-spacing: 0.08em;
}

.execution__identity code {
  max-width: 220px;
  overflow: hidden;
  color: var(--ink-soft);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.execution__message {
  display: grid;
  gap: 2px;
  margin-top: 20px;
  padding: 11px 14px;
  border-left: 3px solid var(--danger);
  color: var(--danger-deep);
  background: var(--danger-soft);
  font-size: 12px;
}

.execution__message strong {
  font-size: 11px;
}

.approval-enter-active,
.approval-leave-active {
  transition:
    opacity 220ms var(--ease-out),
    transform 220ms var(--ease-out);
}

.approval-enter-from,
.approval-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

@media (max-width: 560px) {
  .execution__heading {
    display: grid;
    align-items: start;
  }

  .execution__identity {
    justify-items: start;
  }
}
</style>
