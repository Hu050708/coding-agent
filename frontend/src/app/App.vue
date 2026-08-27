<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

import MemoryPanel from '../features/memory/MemoryPanel.vue'
import type { MemoryEntry, MemoryKind } from '../features/memory/types'
import { useMemory } from '../features/memory/useMemory'
import {
  toMemoryPanelBusy,
  toMemoryPanelPhase,
  toMemoryDraftContent,
  type MemoryBusyAction,
} from '../features/memory/viewState'
import ConsoleHeader from '../features/runs/components/ConsoleHeader.vue'
import ExecutionPanel from '../features/runs/components/ExecutionPanel.vue'
import TaskBrief from '../features/runs/components/TaskBrief.vue'
import type { RunSummary } from '../features/runs/types'
import { useRunConsole } from '../features/runs/useRunConsole'

const consoleState = useRunConsole()
const projectMemory = useMemory()
const memoryPanelOpen = ref(false)
const memoryAction = ref<MemoryBusyAction | null>(null)
const memoryPanel = ref<InstanceType<typeof MemoryPanel> | null>(null)
const memoryTrigger = ref<HTMLButtonElement | null>(null)
let appDisposed = false

interface MemoryEditorState {
  mode: 'create' | 'edit'
  memoryId: string | null
  initial: { kind: MemoryKind; content: string; pinned: boolean }
  sourceRunId: string | null
}

const memoryEditor = ref<MemoryEditorState | null>(null)
const memoryInteractionBusy = computed(
  () => projectMemory.state.busy || memoryEditor.value !== null,
)
const memoryReadOnly = computed(
  () => consoleState.active.value || consoleState.state.action === 'starting',
)
const memoryAvailable = computed(
  () =>
    consoleState.state.validation.phase === 'success' &&
    consoleState.state.validation.data?.workspace === consoleState.form.workspace.trim(),
)
const memoryPanelPhase = computed(() => toMemoryPanelPhase(projectMemory.state.phase))
const memoryPanelBusy = computed(() =>
  toMemoryPanelBusy(projectMemory.state.busy, memoryAction.value),
)

async function withMemoryAction<T>(
  action: MemoryBusyAction,
  operation: () => Promise<T>,
): Promise<T> {
  memoryAction.value = action
  try {
    return await operation()
  } finally {
    memoryAction.value = null
  }
}

function resetMemoryView(): void {
  projectMemory.reset()
  memoryPanelOpen.value = false
  memoryEditor.value = null
}

function updateWorkspace(value: string): void {
  const changed = value.trim() !== consoleState.form.workspace.trim()
  consoleState.updateWorkspace(value)
  if (changed) resetMemoryView()
}

async function loadValidatedMemory(): Promise<void> {
  await withMemoryAction('loading', () => projectMemory.load(consoleState.form.workspace))
}

async function validateWorkspace(): Promise<boolean> {
  const valid = await consoleState.validateWorkspace()
  if (!valid) {
    const validation = consoleState.state.validation
    if (
      validation.phase === 'error' &&
      (validation.checkedValue === null || validation.checkedValue === consoleState.form.workspace.trim())
    ) {
      resetMemoryView()
    }
    return false
  }
  await loadValidatedMemory()
  return true
}

async function ensureMemoryWorkspace(workspace: string): Promise<boolean> {
  if (consoleState.form.workspace.trim() !== workspace) updateWorkspace(workspace)
  if (!memoryAvailable.value && !(await consoleState.validateWorkspace())) return false
  if (
    projectMemory.state.workspace !== workspace ||
    projectMemory.state.phase === 'idle'
  ) {
    await loadValidatedMemory()
  }
  return true
}

async function startRun(): Promise<void> {
  if (memoryInteractionBusy.value) return
  if (
    memoryAvailable.value &&
    (projectMemory.state.workspace !== consoleState.form.workspace.trim() ||
      projectMemory.state.phase === 'idle')
  ) {
    void loadValidatedMemory()
  }
  await consoleState.startRun()
  if (
    memoryAvailable.value &&
    (projectMemory.state.workspace !== consoleState.form.workspace.trim() ||
      projectMemory.state.phase === 'idle')
  ) {
    void loadValidatedMemory()
  }
}

function openMemoryPanel(trigger: HTMLButtonElement): void {
  if (!memoryAvailable.value) return
  memoryTrigger.value = trigger
  memoryPanelOpen.value = true
  if (projectMemory.state.phase === 'idle') void loadValidatedMemory()
  void nextTick(() => memoryPanel.value?.focusPanel())
}

async function closeMemoryPanel(): Promise<void> {
  const trigger = memoryTrigger.value
  memoryPanelOpen.value = false
  memoryEditor.value = null
  memoryTrigger.value = null
  await nextTick()
  trigger?.focus()
}

function createMemory(): void {
  memoryEditor.value = {
    mode: 'create',
    memoryId: null,
    initial: { kind: 'note', content: '', pinned: false },
    sourceRunId: null,
  }
}

function editMemory(entry: MemoryEntry): void {
  memoryEditor.value = {
    mode: 'edit',
    memoryId: entry.id,
    initial: { kind: entry.kind, content: entry.content, pinned: entry.pinned },
    sourceRunId: entry.source_run_id,
  }
}

async function saveMemory(value: { kind: MemoryKind; content: string; pinned: boolean }): Promise<void> {
  const editor = memoryEditor.value
  if (!editor) return
  const safeValue = { ...value, content: toMemoryDraftContent(value.content) }
  const saved = await withMemoryAction('saving', () =>
    editor.mode === 'edit' && editor.memoryId
      ? projectMemory.update(editor.memoryId, safeValue)
      : projectMemory.create({
          ...safeValue,
          ...(editor.sourceRunId ? { source_run_id: editor.sourceRunId } : {}),
        }),
  )
  if (saved) memoryEditor.value = null
}

async function updateMemory(
  entry: MemoryEntry,
  operation: (entry: MemoryEntry) => Promise<MemoryEntry | null>,
): Promise<void> {
  await withMemoryAction('updating', () => operation(entry))
}

async function removeMemory(entry: MemoryEntry): Promise<void> {
  await withMemoryAction('deleting', () => projectMemory.remove(entry.id))
}

async function purgeMemory(): Promise<void> {
  await withMemoryAction('purging', () => projectMemory.purge())
}

async function saveRunResult(run: RunSummary, trigger: HTMLButtonElement): Promise<void> {
  memoryTrigger.value = trigger
  if (!(await ensureMemoryWorkspace(run.workspace)) || !run.final_content) {
    memoryTrigger.value = null
    return
  }
  memoryPanelOpen.value = true
  memoryEditor.value = {
    mode: 'create',
    memoryId: null,
    initial: {
      kind: 'note',
      content: toMemoryDraftContent(run.final_content),
      pinned: false,
    },
    sourceRunId: run.run_id,
  }
}

onMounted(() => {
  void (async () => {
    await Promise.all([consoleState.checkHealth(), consoleState.restoreRun()])
    if (appDisposed) return
    if (
      consoleState.form.workspace &&
      consoleState.state.validation.phase === 'idle'
    ) {
      const valid = await consoleState.validateWorkspace()
      if (!appDisposed && valid) await loadValidatedMemory()
    }
  })()
})

onBeforeUnmount(() => {
  appDisposed = true
  consoleState.dispose()
  projectMemory.reset()
})
</script>

<template>
  <div class="app-shell">
    <ConsoleHeader :health="consoleState.state.health" />

    <div class="console-grid">
      <div class="brief-column">
        <TaskBrief
          :workspace="consoleState.form.workspace"
          :task="consoleState.form.task"
          :use-memory="consoleState.form.useMemory"
          :validation="consoleState.state.validation"
          :memory-available="memoryAvailable"
          :memory-phase="memoryPanelPhase"
          :memory-count="projectMemory.state.items.length"
          :memory-open="memoryPanelOpen"
          :memory-busy="memoryInteractionBusy"
          :active="consoleState.active.value"
          :can-start="consoleState.canStart.value && !memoryInteractionBusy"
          :action="consoleState.state.action"
          :message="consoleState.state.message"
          :limits="consoleState.state.health.data"
          @update:workspace="updateWorkspace"
          @update:task="consoleState.updateTask"
          @update:use-memory="consoleState.form.useMemory = $event"
          @validate="validateWorkspace"
          @manage-memory="openMemoryPanel"
          @start="startRun"
          @cancel="consoleState.cancelRun"
        />

        <Transition name="memory-panel">
          <MemoryPanel
            v-if="memoryPanelOpen"
            ref="memoryPanel"
            :workspace="projectMemory.state.workspace || consoleState.form.workspace"
            :phase="memoryPanelPhase"
            :items="projectMemory.state.items"
            :message="projectMemory.state.message"
            :busy="memoryPanelBusy"
            :editor="memoryEditor"
            :read-only="memoryReadOnly"
            @close="closeMemoryPanel"
            @retry="loadValidatedMemory"
            @create="createMemory"
            @edit="editMemory"
            @toggle-pinned="updateMemory($event, projectMemory.togglePinned)"
            @toggle-enabled="updateMemory($event, projectMemory.toggleEnabled)"
            @remove="removeMemory"
            @purge="purgeMemory"
            @save="saveMemory"
            @cancel-editor="memoryEditor = null"
          />
        </Transition>
      </div>

      <ExecutionPanel
        :state="consoleState.state"
        :active="consoleState.active.value"
        :elapsed-seconds="consoleState.elapsedSeconds.value"
        :limits="consoleState.state.health.data"
        @approve="consoleState.decideApproval('approve')"
        @reject="consoleState.decideApproval('reject')"
        @save-memory="saveRunResult"
      />
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100dvh;
}

.console-grid {
  display: grid;
  grid-template-columns: minmax(310px, 382px) minmax(0, 1fr);
  gap: clamp(34px, 5vw, 76px);
  width: min(1480px, 100%);
  margin: 0 auto;
  padding: clamp(24px, 4vw, 54px) var(--page-gutter) 60px;
}

.brief-column {
  align-self: start;
}

.memory-panel-enter-active,
.memory-panel-leave-active {
  transition:
    opacity 180ms var(--ease-out),
    transform 180ms var(--ease-out);
}

.memory-panel-enter-from,
.memory-panel-leave-to {
  opacity: 0;
  transform: translateY(-5px);
}

@media (min-width: 921px) {
  .brief-column {
    position: sticky;
    top: calc(var(--header-height) + 28px);
    max-height: calc(100dvh - var(--header-height) - 48px);
    overflow: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--line-strong) transparent;
  }
}

@media (max-width: 920px) {
  .console-grid {
    grid-template-columns: 1fr;
    gap: 36px;
    width: min(760px, 100%);
    padding-top: 24px;
  }
}
</style>
