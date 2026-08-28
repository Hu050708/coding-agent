<script setup lang="ts">
import { computed, ref } from 'vue'

import type { ApprovalRequest, RunEventEnvelope, RunStatus } from '../../../shared/api/types'
import { presentRunEvent } from '../../runs/runPresentation'
import ApprovalCard from './ApprovalCard.vue'

const props = defineProps<{
  events: RunEventEnvelope[]
  status: RunStatus
  approval: ApprovalRequest | null
  actionBusy: boolean
}>()

defineEmits<{ approve: []; reject: [] }>()

const expanded = ref(true)
const items = computed(() => props.events.map(presentRunEvent))
const active = computed(() =>
  ['starting', 'running', 'waiting_approval', 'cancelling'].includes(props.status),
)
</script>

<template>
  <section class="activity-spine" aria-label="Agent 活动">
    <button class="spine-toggle" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
      <span class="pulse" :class="{ active }" />
      <span>{{ active ? 'Agent 活动中' : 'Agent 活动' }}</span>
      <span class="event-count">{{ items.length }} 项</span>
      <span class="chevron" :class="{ expanded }">⌄</span>
    </button>

    <div v-if="expanded" class="spine-items">
      <div v-for="item in items" :key="item.seq" class="spine-item" :class="item.tone">
        <span class="node" />
        <div class="event-copy">
          <div class="event-title-row">
            <span>{{ item.title }}</span>
            <span v-if="item.meta" class="event-meta">{{ item.meta }}</span>
          </div>
          <p v-if="item.detail">{{ item.detail }}</p>
        </div>
      </div>
      <div v-if="items.length === 0" class="spine-item active">
        <span class="node" />
        <div class="event-copy"><span>正在等待第一个事件…</span></div>
      </div>
    </div>

    <ApprovalCard
      v-if="approval?.status === 'pending'"
      :approval="approval"
      :busy="actionBusy"
      @approve="$emit('approve')"
      @reject="$emit('reject')"
    />
  </section>
</template>

<style scoped>
.activity-spine {
  margin: 2px 0 16px;
  padding: 10px 12px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-subtle);
}

.spine-toggle {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 8px;
  padding: 0;
  background: transparent;
  color: var(--ink-soft);
  font-family: var(--font-utility);
  font-size: 11px;
  font-weight: 650;
  text-align: left;
}

.pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-faint);
}

.pulse.active {
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.event-count {
  margin-left: auto;
  color: var(--ink-faint);
  font-size: 10px;
  font-weight: 500;
}

.chevron {
  transform: rotate(-90deg);
  transition: transform 140ms var(--ease-out);
}

.chevron.expanded {
  transform: rotate(0);
}

.spine-items {
  position: relative;
  margin: 10px 0 0 3px;
  padding-left: 17px;
}

.spine-items::before {
  position: absolute;
  top: 8px;
  bottom: 8px;
  left: 3px;
  width: 1px;
  background: var(--activity-line);
  content: '';
}

.spine-item {
  position: relative;
  display: flex;
  min-height: 29px;
  align-items: flex-start;
  padding: 4px 0 6px;
  color: var(--ink-soft);
  font-size: 11.5px;
}

.node {
  position: absolute;
  top: 9px;
  left: -17px;
  width: 7px;
  height: 7px;
  border: 2px solid var(--surface-subtle);
  border-radius: 50%;
  background: var(--ink-faint);
  box-sizing: content-box;
}

.spine-item.active .node {
  background: var(--accent);
}

.spine-item.success .node {
  background: var(--success);
}

.spine-item.warning .node {
  background: var(--warning);
}

.spine-item.danger .node {
  background: var(--danger);
}

.event-copy {
  min-width: 0;
  flex: 1;
}

.event-title-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.event-copy p {
  margin: 2px 0 0;
  overflow: hidden;
  color: var(--ink-muted);
  font-family: var(--font-mono);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.event-meta {
  flex: none;
  color: var(--ink-faint);
  font-family: var(--font-mono);
  font-size: 9px;
}
</style>
