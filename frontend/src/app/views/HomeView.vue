<script setup lang="ts">
import AppIcon from '../../shared/components/AppIcon.vue'

defineEmits<{ openSidebar: []; addWorkspace: [] }>()
</script>

<template>
  <section class="gate-view">
    <header class="mobile-only-header">
      <button class="icon-button" type="button" aria-label="打开工作区与会话" @click="$emit('openSidebar')">
        <AppIcon name="menu" />
      </button>
      <div>
        <strong>Coding Agent</strong>
        <span>Local workbench</span>
      </div>
    </header>

    <main class="gate-content">
      <div class="hero-panel">
        <div class="hero-copy">
          <span class="hero-mark" aria-hidden="true"><AppIcon name="terminal" /></span>
          <p class="eyebrow">LOCAL CODING WORKBENCH</p>
          <h1>从一个受控工作区开始</h1>
          <p class="hero-description">工作区决定 Agent 可以读取、修改和运行命令的目录。选择边界后，你可以在会话中审阅每次模型决策和工具反馈。</p>
          <button class="primary-action" type="button" @click="$emit('addWorkspace')">
            <AppIcon name="folder" />
            选择工作区
          </button>
          <p class="existing-hint">已经添加过工作区？可直接从左侧“当前工作区”切换。</p>
        </div>

        <div class="trust-panel" aria-label="本机 Agent 安全特性">
          <div class="trust-heading">
            <AppIcon name="shield" />
            <div><strong>边界清晰，可随时停止</strong><span>Local by design</span></div>
          </div>
          <ul>
            <li><span>01</span><div><strong>工作区隔离</strong><p>文件工具只接受当前工作区内的规范路径。</p></div></li>
            <li><span>02</span><div><strong>危险操作确认</strong><p>需要审批的操作会在执行前明确展示。</p></div></li>
            <li><span>03</span><div><strong>事实与结论分离</strong><p>模型最终回答不会被冒充为独立验证成功。</p></div></li>
          </ul>
        </div>
      </div>
    </main>
  </section>
</template>

<style scoped>
.gate-view {
  height: 100%;
  background:
    radial-gradient(circle at 25% 20%, rgb(49 95 204 / 6%), transparent 34%),
    var(--canvas);
}

.mobile-only-header {
  display: none;
}

.gate-content {
  display: grid;
  height: 100%;
  place-items: center;
  padding: 48px;
}

.hero-panel {
  display: grid;
  width: min(980px, 100%);
  grid-template-columns: minmax(0, 1.25fr) minmax(310px, 0.75fr);
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: var(--surface);
  box-shadow: 0 24px 70px rgb(24 32 43 / 9%);
}

.hero-copy {
  padding: 54px 56px;
}

.hero-mark {
  display: grid;
  width: 52px;
  height: 52px;
  place-items: center;
  margin-bottom: 22px;
  border: 1px solid var(--line-strong);
  border-radius: 14px;
  color: var(--accent);
  background: var(--surface-subtle);
}

.eyebrow,
h1,
.hero-description,
.existing-hint {
  margin: 0;
}

.eyebrow {
  color: var(--accent);
  font-family: var(--font-utility);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.11em;
}

h1 {
  max-width: 520px;
  margin-top: 8px;
  font-family: var(--font-display);
  font-size: clamp(30px, 4vw, 44px);
  font-weight: 750;
  letter-spacing: -0.035em;
  line-height: 1.12;
}

.hero-description {
  max-width: 580px;
  margin-top: 18px;
  color: var(--ink-muted);
  font-size: 15px;
  line-height: 1.75;
}

.primary-action {
  display: inline-flex;
  min-height: 48px;
  align-items: center;
  gap: 9px;
  margin-top: 28px;
  padding: 0 18px;
  border-radius: 10px;
  color: white;
  background: var(--accent);
  font-size: 14px;
  font-weight: 700;
  box-shadow: 0 8px 20px rgb(49 95 204 / 20%);
}

.primary-action:hover {
  background: var(--accent-strong);
}

.existing-hint {
  margin-top: 10px;
  color: var(--ink-faint);
  font-size: 10px;
}

.trust-panel {
  padding: 38px 32px;
  color: #d9e2ef;
  background: #111827;
}

.trust-heading {
  display: flex;
  align-items: center;
  gap: 11px;
  padding-bottom: 20px;
  border-bottom: 1px solid #2a3649;
}

.trust-heading > :deep(svg) {
  color: #7da4ff;
}

.trust-heading div {
  display: grid;
}

.trust-heading strong {
  color: white;
  font-size: 13px;
}

.trust-heading span {
  color: #8f9eb2;
  font-family: var(--font-utility);
  font-size: 9px;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

ul {
  display: grid;
  gap: 20px;
  margin: 25px 0 0;
  padding: 0;
  list-style: none;
}

li {
  display: grid;
  grid-template-columns: 27px 1fr;
  gap: 11px;
}

li > span {
  color: #7da4ff;
  font-family: var(--font-mono);
  font-size: 9px;
}

li strong,
li p {
  margin: 0;
}

li strong {
  color: #f5f8fc;
  font-size: 12px;
}

li p {
  margin-top: 3px;
  color: #9eacc0;
  font-size: 10.5px;
  line-height: 1.55;
}

@media (max-width: 900px) {
  .mobile-only-header {
    display: flex;
    min-height: var(--header-height);
    align-items: center;
    gap: 9px;
    padding: 0 10px;
    border-bottom: 1px solid var(--line);
    background: var(--surface);
  }

  .mobile-only-header div {
    display: grid;
  }

  .mobile-only-header strong {
    font-size: 13px;
  }

  .mobile-only-header span {
    color: var(--ink-muted);
    font-size: 9px;
  }

  .gate-content {
    height: calc(100% - var(--header-height));
    padding: 24px;
  }
}

@media (max-width: 760px) {
  .gate-content {
    display: block;
    padding: 18px 14px 30px;
    overflow-y: auto;
  }

  .hero-panel {
    grid-template-columns: 1fr;
    border-radius: 16px;
  }

  .hero-copy {
    padding: 32px 24px;
  }

  h1 {
    font-size: 30px;
  }

  .hero-description {
    font-size: 14px;
  }

  .primary-action {
    width: 100%;
    justify-content: center;
  }

  .trust-panel {
    padding: 28px 24px;
  }
}
</style>
