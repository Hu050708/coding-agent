<script setup lang="ts">
import AppIcon from '../../shared/components/AppIcon.vue'

defineEmits<{ openSidebar: [] }>()
</script>

<template>
  <section class="gate-view">
    <header class="mobile-only-header">
      <button class="icon-button" type="button" aria-label="打开侧栏" @click="$emit('openSidebar')">
        <AppIcon name="menu" />
      </button>
      <span>Coding Agent</span>
    </header>
    <div class="gate-content">
      <span class="gate-command" aria-hidden="true">cd</span>
      <h1>先选择一个工作区</h1>
      <p>工作区决定 Agent 可以读取和修改的目录。使用左侧选择已有工作区，或从允许根目录添加一个。</p>
      <button class="mobile-workspace-button" type="button" @click="$emit('openSidebar')">
        <AppIcon name="folder" />
        选择工作区
      </button>
    </div>
  </section>
</template>

<style scoped>
.gate-view {
  height: 100%;
}

.gate-content {
  display: flex;
  height: 100%;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  padding: 32px;
  text-align: center;
}

.gate-command {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  margin-bottom: 18px;
  border: 1px solid var(--line-strong);
  border-radius: 9px;
  color: var(--accent);
  background: var(--surface-subtle);
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 650;
}

h1 {
  margin: 0;
  font-size: 21px;
  font-weight: 640;
}

p {
  max-width: 480px;
  margin: 10px 0 0;
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 1.65;
}

.mobile-only-header,
.mobile-workspace-button {
  display: none;
}

@media (max-width: 900px) {
  .mobile-only-header {
    display: flex;
    height: var(--header-height);
    align-items: center;
    gap: 12px;
    padding: 0 14px;
    border-bottom: 1px solid var(--line);
    font-size: 14px;
    font-weight: 630;
  }

  .gate-content {
    height: calc(100% - var(--header-height));
  }

  .mobile-workspace-button {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-top: 20px;
    padding: 9px 12px;
    border: 1px solid var(--line-strong);
    border-radius: 7px;
    background: var(--surface-subtle);
  }
}
</style>
