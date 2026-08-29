<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { localizedError } from '../../shared/api/http'
import type { DirectoryListing } from './types'
import AppIcon from '../../shared/components/AppIcon.vue'
import { workspaceApi } from './api'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  close: []
  select: [path: string]
}>()

const dialog = ref<HTMLElement | null>(null)
const listing = ref<DirectoryListing | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
let generation = 0
let previousFocus: HTMLElement | null = null

async function browse(path?: string): Promise<void> {
  const current = ++generation
  loading.value = true
  error.value = null
  try {
    const result = await workspaceApi.browse(path)
    if (current === generation) listing.value = result
  } catch (reason) {
    if (current === generation) error.value = localizedError(reason)
  } finally {
    if (current === generation) loading.value = false
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (!props.open) return
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }
  if (event.key !== 'Tab' || !dialog.value) return
  const controls = [...dialog.value.querySelectorAll<HTMLElement>('button:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])')]
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

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) {
      previousFocus?.focus()
      previousFocus = null
      return
    }
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await browse()
    await nextTick()
    dialog.value?.focus()
  },
  { immediate: true },
)

window.addEventListener('keydown', onKeydown)
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="dialog-backdrop" @mousedown.self="emit('close')">
      <section ref="dialog" class="directory-dialog" role="dialog" aria-modal="true" aria-labelledby="directory-title" tabindex="-1">
        <header class="dialog-header">
          <div>
            <p class="eyebrow">受限目录浏览</p>
            <h2 id="directory-title">选择工作区</h2>
          </div>
          <button class="icon-button" type="button" aria-label="关闭目录选择" @click="emit('close')">
            <AppIcon name="close" />
          </button>
        </header>

        <div v-if="listing" class="path-bar" :title="listing.current_path">
          <AppIcon name="folder" />
          <span>{{ listing.current_path }}</span>
        </div>

        <p class="root-note">只能浏览后端配置的允许根目录；网页不能任意访问本机文件系统。</p>

        <div class="directory-list" aria-live="polite" :aria-busy="loading">
          <button
            v-if="listing?.parent_path"
            type="button"
            class="directory-row back-row"
            @click="browse(listing.parent_path)"
          >
            <AppIcon name="chevron-left" />
            <span>返回上一级</span>
          </button>
          <button
            v-for="entry in listing?.entries ?? []"
            :key="entry.path"
            type="button"
            class="directory-row"
            @click="browse(entry.path)"
          >
            <AppIcon name="folder" />
            <span>{{ entry.name }}</span>
          </button>
          <p v-if="loading" class="directory-empty">正在读取目录…</p>
          <p v-else-if="error" class="directory-error">{{ error }}</p>
          <p v-else-if="listing && listing.entries.length === 0" class="directory-empty">这个文件夹没有子目录。</p>
        </div>

        <footer class="dialog-actions">
          <button class="secondary-button" type="button" @click="emit('close')">取消</button>
          <button
            class="primary-button"
            type="button"
            :disabled="!listing || loading"
            @click="listing && emit('select', listing.current_path)"
          >
            使用这个文件夹
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgb(23 28 38 / 38%);
}

.directory-dialog {
  width: min(620px, 100%);
  max-height: min(720px, calc(100dvh - 40px));
  overflow: hidden;
  border: 1px solid var(--line-strong);
  border-radius: 14px;
  background: var(--surface);
  box-shadow: var(--shadow-dialog);
}

.dialog-header,
.dialog-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 22px;
}

.dialog-header {
  border-bottom: 1px solid var(--line);
}

.dialog-header h2 {
  margin: 2px 0 0;
  font-size: 19px;
  font-weight: 620;
}

.eyebrow {
  margin: 0;
  color: var(--ink-muted);
  font-family: var(--font-utility);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.path-bar {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 18px 22px 8px;
  padding: 10px 12px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-subtle);
  font-family: var(--font-mono);
  font-size: 12px;
}

.path-bar span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.root-note {
  margin: 0 22px 14px;
  color: var(--ink-muted);
  font-size: 12px;
}

.directory-list {
  min-height: 220px;
  max-height: 360px;
  padding: 0 14px 12px;
  overflow-y: auto;
}

.directory-row {
  display: flex;
  width: 100%;
  min-height: 44px;
  align-items: center;
  gap: 10px;
  padding: 10px 9px;
  border-radius: 7px;
  background: transparent;
  text-align: left;
}

.directory-row:hover {
  background: var(--surface-hover);
}

.back-row {
  color: var(--ink-soft);
}

.directory-empty,
.directory-error {
  padding: 28px 12px;
  color: var(--ink-muted);
  text-align: center;
}

.directory-error {
  color: var(--danger);
}

.dialog-actions {
  justify-content: flex-end;
  border-top: 1px solid var(--line);
}

@media (max-width: 640px) {
  .dialog-backdrop {
    align-items: end;
    padding: 0;
  }

  .directory-dialog {
    max-height: 88dvh;
    border-radius: 14px 14px 0 0;
  }
}
</style>
