<script setup lang="ts">
defineProps<{
  name:
    | 'plus'
    | 'folder'
    | 'chat'
    | 'memory'
    | 'menu'
    | 'close'
    | 'arrow-up'
    | 'chevron-left'
    | 'chevron-down'
    | 'stop'
    | 'refresh'
    | 'panel-right'
    | 'shield'
    | 'terminal'
    | 'check'
    | 'copy'
}>()
</script>

<template>
  <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
    <path v-if="name === 'plus'" d="M12 5v14M5 12h14" />
    <path v-else-if="name === 'folder'" d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" />
    <path v-else-if="name === 'chat'" d="M5 18.5l-2 2v-15a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2z" />
    <path v-else-if="name === 'memory'" d="M9 4.5a3 3 0 0 0-5 2.2 3 3 0 0 0 .7 5.7A3 3 0 0 0 8 17.3V20M15 4.5a3 3 0 0 1 5 2.2 3 3 0 0 1-.7 5.7 3 3 0 0 1-3.3 4.9V20M9 4v16M15 4v16M9 8h3M12 12h3M9 16h3" />
    <path v-else-if="name === 'menu'" d="M4 7h16M4 12h16M4 17h16" />
    <path v-else-if="name === 'close'" d="m6 6 12 12M18 6 6 18" />
    <path v-else-if="name === 'arrow-up'" d="m12 19 0-14m-6 6 6-6 6 6" />
    <path v-else-if="name === 'chevron-left'" d="m15 18-6-6 6-6" />
    <path v-else-if="name === 'chevron-down'" d="m6 9 6 6 6-6" />
    <rect v-else-if="name === 'stop'" x="7" y="7" width="10" height="10" rx="1" />
    <path v-else-if="name === 'refresh'" d="M20 6v5h-5M4 18v-5h5M18.5 10A7 7 0 0 0 6 7.5L4 11M5.5 14A7 7 0 0 0 18 16.5l2-3.5" />
    <path v-else-if="name === 'panel-right'" d="M4 4h16v16H4zM15 4v16" />
    <path v-else-if="name === 'shield'" d="M12 3.5 19 6v5.2c0 4.1-2.8 7.7-7 9.3-4.2-1.6-7-5.2-7-9.3V6zM9 12l2 2 4-4" />
    <path v-else-if="name === 'terminal'" d="m5 7 4 4-4 4M11 16h8" />
    <path v-else-if="name === 'check'" d="m5 12 4 4L19 6" />
    <path v-else-if="name === 'copy'" d="M9 8h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2zM16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h2" />
  </svg>
</template>

<style scoped>
svg {
  display: block;
  width: 1.2rem;
  height: 1.2rem;
}
</style>
