<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'

import {
  demoSteps,
  demoTask,
  sectionValue,
  snapshotSections,
  type JsonObject,
  type SnapshotSection,
} from '../../features/workflow/workflow'
import AppIcon from '../../shared/components/AppIcon.vue'

defineEmits<{ openSidebar: [] }>()

const stepIndex = ref(0)
const activeSection = ref<SnapshotSection>('complete')
const playing = ref(false)
const copied = ref(false)
let playTimer: number | undefined
let copiedTimer: number | undefined

const currentStep = computed(() => demoSteps[stepIndex.value] ?? demoSteps[0]!)
const currentRun = computed(() => currentStep.value.state.run as JsonObject)
const visibleValue = computed(() => sectionValue(currentStep.value.state, activeSection.value))
const jsonText = computed(() => JSON.stringify(visibleValue.value, null, 2))
const progressText = computed(() => `${stepIndex.value + 1} / ${demoSteps.length}`)

function clearPlayTimer(): void {
  if (playTimer !== undefined) window.clearInterval(playTimer)
  playTimer = undefined
}

function stopPlaying(): void {
  playing.value = false
  clearPlayTimer()
}

function selectStep(index: number): void {
  stopPlaying()
  stepIndex.value = index
}

function previousStep(): void {
  stopPlaying()
  stepIndex.value = Math.max(0, stepIndex.value - 1)
}

function nextStep(): void {
  stopPlaying()
  stepIndex.value = Math.min(demoSteps.length - 1, stepIndex.value + 1)
}

function advancePlayback(): void {
  if (stepIndex.value >= demoSteps.length - 1) {
    stopPlaying()
    return
  }
  stepIndex.value += 1
}

function togglePlayback(): void {
  if (playing.value) {
    stopPlaying()
    return
  }
  if (stepIndex.value >= demoSteps.length - 1) stepIndex.value = 0
  playing.value = true
  playTimer = window.setInterval(advancePlayback, 1400)
}

async function copyJson(): Promise<void> {
  try {
    await navigator.clipboard.writeText(jsonText.value)
    copied.value = true
    if (copiedTimer !== undefined) window.clearTimeout(copiedTimer)
    copiedTimer = window.setTimeout(() => { copied.value = false }, 1500)
  } catch {
    copied.value = false
  }
}

onBeforeUnmount(() => {
  clearPlayTimer()
  if (copiedTimer !== undefined) window.clearTimeout(copiedTimer)
})
</script>

<template>
  <section class="workflow-view">
    <header class="workflow-header">
      <button class="icon-button mobile-menu" type="button" aria-label="打开工作区与会话" @click="$emit('openSidebar')">
        <AppIcon name="menu" />
      </button>
      <div class="header-title">
        <span>DEMO RUN REPLAY</span>
        <strong>Agent 示例工作流</strong>
      </div>
      <div class="header-state">
        <span>{{ progressText }}</span>
        <strong>{{ String(currentRun.status) }}</strong>
      </div>
    </header>

    <div class="workflow-scroll">
      <main class="workflow-content">
        <section class="task-strip" aria-labelledby="demo-task-title">
          <div class="task-label">
            <span>固定演示任务</span>
            <small>不连接后端</small>
          </div>
          <h1 id="demo-task-title">“{{ demoTask }}”</h1>
          <dl>
            <div><dt>模型</dt><dd>deepseek-v4-flash</dd></div>
            <div><dt>权限</dt><dd>ask</dd></div>
            <div><dt>目标文件</dt><dd>hello.py</dd></div>
          </dl>
        </section>

        <section class="replay-toolbar" aria-label="示例回放控制">
          <div>
            <span>当前步骤</span>
            <strong>{{ currentStep.number }} · {{ currentStep.title }}</strong>
          </div>
          <div class="toolbar-actions">
            <button type="button" :disabled="stepIndex === 0" @click="previousStep">上一步</button>
            <button class="play-button" type="button" @click="togglePlayback">
              {{ playing ? '暂停' : stepIndex === demoSteps.length - 1 ? '重新播放' : '自动播放' }}
            </button>
            <button type="button" :disabled="stepIndex === demoSteps.length - 1" @click="nextStep">下一步</button>
          </div>
        </section>

        <div class="replay-layout">
          <nav class="step-rail" aria-label="示例执行步骤">
            <button
              v-for="(step, index) in demoSteps"
              :key="step.id"
              type="button"
              :class="{
                active: index === stepIndex,
                completed: index < stepIndex,
                pending: index > stepIndex,
              }"
              :aria-current="index === stepIndex ? 'step' : undefined"
              @click="selectStep(index)"
            >
              <span class="rail-marker">{{ step.number }}</span>
              <span class="rail-copy">
                <small>{{ step.actor }}</small>
                <strong>{{ step.title }}</strong>
                <code>{{ step.event }}</code>
              </span>
            </button>
          </nav>

          <section class="state-panel" aria-labelledby="state-title">
            <header class="state-heading">
              <div class="state-number">{{ currentStep.number }}</div>
              <div class="state-title">
                <span>{{ currentStep.actor }}</span>
                <h2 id="state-title">{{ currentStep.title }}</h2>
                <p>{{ currentStep.summary }}</p>
              </div>
              <code class="event-name">{{ currentStep.event }}</code>
            </header>

            <div class="change-strip">
              <strong>这一步改变了什么</strong>
              <ul>
                <li v-for="change in currentStep.changes" :key="change">{{ change }}</li>
              </ul>
            </div>

            <div class="json-toolbar">
              <div class="section-tabs" role="tablist" aria-label="选择 JSON 数据范围">
                <button
                  v-for="section in snapshotSections"
                  :key="section.id"
                  type="button"
                  role="tab"
                  :aria-selected="activeSection === section.id"
                  :class="{ active: activeSection === section.id }"
                  @click="activeSection = section.id"
                >
                  {{ section.label }}
                </button>
              </div>
              <button class="copy-button" type="button" @click="copyJson">
                <AppIcon name="copy" />
                {{ copied ? '已复制' : '复制 JSON' }}
              </button>
            </div>

            <div class="json-viewer" aria-live="polite">
              <div class="json-gutter" aria-hidden="true">
                <span v-for="line in jsonText.split('\n').length" :key="line">{{ line }}</span>
              </div>
              <pre>{{ jsonText }}</pre>
            </div>
          </section>
        </div>

        <footer class="demo-note">
          这是一组固定演示快照，用来解释一次任务内部的数据变化，不代表真实 API 延迟和 Token 数值。
        </footer>
      </main>
    </div>
  </section>
</template>

<style scoped src="./WorkflowView.css"></style>
