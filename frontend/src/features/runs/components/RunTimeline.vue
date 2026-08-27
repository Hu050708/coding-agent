<script setup lang="ts">
import type { TimelineEvent } from '../types'

defineProps<{
  events: TimelineEvent[]
  active: boolean
}>()

function timeLabel(timestamp: string): string {
  const parsed = Date.parse(timestamp)
  if (!Number.isFinite(parsed)) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(parsed)
}

function metaLabel(event: TimelineEvent): string | null {
  const parts: string[] = []
  if (event.durationMs !== null) parts.push(`${Math.round(event.durationMs)} ms`)
  if (event.exitCode !== null) parts.push(`exit ${event.exitCode}`)
  if (event.truncated === true) parts.push('输出已截断')
  return parts.length ? parts.join(' / ') : null
}
</script>

<template>
  <section class="timeline-section" aria-labelledby="timeline-title">
    <div class="timeline-heading">
      <h2 id="timeline-title">执行记录</h2>
      <span class="mono">{{ events.length }} events</span>
    </div>

    <div v-if="events.length === 0" class="timeline-empty">
      <span class="timeline-empty__node" aria-hidden="true"></span>
      <div>
        <h3>执行记录尚未开始</h3>
        <p>填写左侧简报并开始运行。模型思考不会显示在此处。</p>
      </div>
    </div>

    <ol v-else class="timeline" :class="{ 'timeline--active': active }">
      <li
        v-for="event in events"
        :key="event.seq"
        class="timeline-event"
        :class="`timeline-event--${event.tone}`"
      >
        <span class="timeline-event__node" aria-hidden="true"></span>
        <div class="timeline-event__body">
          <div class="timeline-event__heading">
            <h3>{{ event.title }}</h3>
            <time class="mono" :datetime="event.timestamp">{{ timeLabel(event.timestamp) }}</time>
          </div>
          <p v-if="event.detail" class="timeline-event__detail">{{ event.detail }}</p>
          <p v-if="metaLabel(event)" class="timeline-event__meta mono">{{ metaLabel(event) }}</p>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.timeline-section {
  margin-top: 34px;
}

.timeline-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.timeline-heading h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 640;
  letter-spacing: -0.025em;
}

.timeline-heading span {
  color: var(--ink-muted);
  font-size: 10px;
}

.timeline-empty {
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: 18px;
  min-height: 190px;
  align-items: start;
  padding-top: 22px;
  border-top: 1px solid var(--line);
}

.timeline-empty__node {
  width: 12px;
  height: 12px;
  margin: 4px 0 0 5px;
  border: 2px solid var(--line-strong);
  border-radius: 50%;
}

.timeline-empty h3 {
  margin: 0;
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 580;
}

.timeline-empty p {
  max-width: 48ch;
  margin: 8px 0 0;
  color: var(--ink-muted);
  font-size: 12px;
}

.timeline {
  position: relative;
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.timeline::before {
  position: absolute;
  top: 10px;
  bottom: 20px;
  left: 11px;
  width: 1px;
  background: var(--line-strong);
  content: '';
}

.timeline--active::after {
  position: absolute;
  top: 10px;
  left: 10px;
  width: 3px;
  height: 52px;
  border-radius: 3px;
  background: linear-gradient(to bottom, transparent, var(--cobalt), transparent);
  content: '';
  pointer-events: none;
}

.timeline-event {
  position: relative;
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 18px;
  min-height: 78px;
  padding: 0 0 20px;
  animation: event-enter 320ms var(--ease-out) both;
}

.timeline-event__node {
  position: relative;
  z-index: 2;
  width: 12px;
  height: 12px;
  margin: 5px 0 0 5px;
  border: 3px solid var(--surface);
  border-radius: 50%;
  background: var(--ink-muted);
  box-shadow: 0 0 0 1px var(--ink-muted);
}

.timeline-event--active .timeline-event__node {
  background: var(--cobalt);
  box-shadow: 0 0 0 1px var(--cobalt);
}

.timeline-event--success .timeline-event__node {
  background: var(--success);
  box-shadow: 0 0 0 1px var(--success);
}

.timeline-event--warning .timeline-event__node {
  background: var(--amber);
  box-shadow: 0 0 0 1px var(--amber);
}

.timeline-event--danger .timeline-event__node {
  background: var(--danger);
  box-shadow: 0 0 0 1px var(--danger);
}

.timeline-event__body {
  min-width: 0;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
}

.timeline-event__heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
}

.timeline-event h3 {
  margin: 0;
  color: var(--ink);
  font-size: 13px;
  font-weight: 650;
}

time,
.timeline-event__meta {
  color: var(--ink-muted);
  font-size: 10px;
}

.timeline-event__detail,
.timeline-event__meta {
  margin: 6px 0 0;
}

.timeline-event__detail {
  color: var(--ink-soft);
  font-size: 12px;
}

@media (prefers-reduced-motion: no-preference) {
  .timeline--active::after {
    animation: spine-pulse 2.2s var(--ease-out) infinite;
  }
}

@keyframes spine-pulse {
  from {
    opacity: 0;
    transform: translateY(0);
  }
  18% {
    opacity: 1;
  }
  to {
    opacity: 0;
    transform: translateY(min(46vh, 360px));
  }
}

@keyframes event-enter {
  from {
    opacity: 0;
    transform: translateY(7px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 560px) {
  .timeline-event__heading {
    display: grid;
    gap: 4px;
  }
}
</style>
