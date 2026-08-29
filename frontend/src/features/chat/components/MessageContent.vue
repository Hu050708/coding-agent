<script setup lang="ts">
import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { computed, ref } from 'vue'

const props = defineProps<{ content: string }>()
const copiedIndex = ref<number | null>(null)
let activeCodeBlocks: string[] = []

const markdown = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: false,
})

const defaultLinkOpen = markdown.renderer.rules.link_open
  ?? ((tokens, index, options, _environment, renderer) => renderer.renderToken(tokens, index, options))

markdown.renderer.rules.link_open = (tokens, index, options, environment, renderer) => {
  tokens[index]?.attrSet('target', '_blank')
  tokens[index]?.attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, index, options, environment, renderer)
}

markdown.renderer.rules.image = (tokens, index) => {
  const alternative = tokens[index]?.content.trim() || '未命名图片'
  return `<span class="image-reference">[图片引用：${markdown.utils.escapeHtml(alternative)}]</span>`
}

markdown.renderer.rules.table_open = () => '<div class="table-scroll"><table>'
markdown.renderer.rules.table_close = () => '</table></div>'

markdown.renderer.rules.fence = (tokens, index) => {
  const token = tokens[index]
  const content = token?.content ?? ''
  const language = (token?.info ?? '')
    .trim()
    .split(/\s+/u)[0]
    ?.replace(/[^\w+-]/gu, '')
    .slice(0, 24) || ''
  const codeIndex = activeCodeBlocks.push(content) - 1
  const copied = copiedIndex.value === codeIndex
  const label = language || '代码'

  return `<div class="code-block">
    <div class="code-toolbar">
      <span>${markdown.utils.escapeHtml(label)}</span>
      <button type="button" class="copy-code" data-code-index="${codeIndex}" aria-label="${copied ? '已复制代码' : '复制代码'}">
        <span class="copy-symbol" aria-hidden="true">${copied ? '✓' : '⧉'}</span>
        <span>${copied ? '已复制' : '复制'}</span>
      </button>
    </div>
    <pre><code${language ? ` class="language-${language}"` : ''}>${markdown.utils.escapeHtml(content)}</code></pre>
  </div>`
}

const rendered = computed(() => {
  activeCodeBlocks = []
  const unsafeHtml = markdown.render(props.content)
  const html = DOMPurify.sanitize(unsafeHtml, {
    USE_PROFILES: { html: true },
    ADD_ATTR: ['target', 'rel', 'data-code-index', 'aria-label'],
    FORBID_TAGS: ['style', 'iframe', 'form', 'input', 'video', 'audio'],
    FORBID_ATTR: ['style'],
  })
  return { html, codeBlocks: [...activeCodeBlocks] }
})

async function writeClipboard(content: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(content)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = content
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  textarea.remove()
}

async function onContentClick(event: MouseEvent): Promise<void> {
  const target = event.target instanceof Element
    ? event.target.closest<HTMLButtonElement>('button[data-code-index]')
    : null
  if (!target) return
  const index = Number.parseInt(target.dataset.codeIndex ?? '', 10)
  const content = rendered.value.codeBlocks[index]
  if (!Number.isInteger(index) || content === undefined) return
  try {
    await writeClipboard(content)
    copiedIndex.value = index
    window.setTimeout(() => {
      if (copiedIndex.value === index) copiedIndex.value = null
    }, 1800)
  } catch {
    copiedIndex.value = null
  }
}
</script>

<template>
  <div class="markdown-body" @click="onContentClick" v-html="rendered.html" />
</template>

<style scoped>
.markdown-body {
  min-width: 0;
  color: var(--ink);
  font-size: 15px;
  line-height: 1.72;
  overflow-wrap: anywhere;
}

.markdown-body :deep(> :first-child) {
  margin-top: 0;
}

.markdown-body :deep(> :last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(p),
.markdown-body :deep(blockquote),
.markdown-body :deep(ul),
.markdown-body :deep(ol),
.markdown-body :deep(.table-scroll),
.markdown-body :deep(.code-block) {
  margin: 0 0 15px;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 25px 0 10px;
  color: var(--ink);
  font-family: var(--font-display);
  font-weight: 730;
  letter-spacing: -0.018em;
  line-height: 1.35;
}

.markdown-body :deep(h1) {
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
  font-size: 21px;
}

.markdown-body :deep(h2) {
  font-size: 18px;
}

.markdown-body :deep(h3) {
  font-size: 16px;
}

.markdown-body :deep(h4) {
  font-size: 15px;
}

.markdown-body :deep(strong) {
  color: #111827;
  font-weight: 720;
}

.markdown-body :deep(em) {
  color: var(--ink-soft);
}

.markdown-body :deep(a) {
  color: var(--accent);
  font-weight: 550;
  text-decoration-color: rgb(49 95 204 / 38%);
  text-underline-offset: 3px;
}

.markdown-body :deep(a:hover) {
  color: var(--accent-strong);
  text-decoration-color: currentColor;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 25px;
}

.markdown-body :deep(li) {
  padding-left: 2px;
}

.markdown-body :deep(li + li) {
  margin-top: 5px;
}

.markdown-body :deep(li > ul),
.markdown-body :deep(li > ol) {
  margin: 6px 0 0;
}

.markdown-body :deep(li::marker) {
  color: var(--ink-faint);
  font-family: var(--font-mono);
  font-size: 0.85em;
}

.markdown-body :deep(blockquote) {
  padding: 10px 14px;
  border-left: 3px solid var(--accent-border);
  border-radius: 0 8px 8px 0;
  color: var(--ink-soft);
  background: var(--accent-soft);
}

.markdown-body :deep(blockquote > :last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(code) {
  padding: 0.15em 0.38em;
  border: 1px solid #d9e0e9;
  border-radius: 5px;
  color: #9b3150;
  background: #f3f5f8;
  font-family: var(--font-mono);
  font-size: 0.88em;
}

.markdown-body :deep(.code-block) {
  overflow: hidden;
  border: 1px solid #2b3648;
  border-radius: 11px;
  background: #111827;
  box-shadow: 0 5px 16px rgb(15 23 42 / 9%);
}

.markdown-body :deep(.code-toolbar) {
  display: flex;
  min-height: 40px;
  align-items: center;
  justify-content: space-between;
  padding: 0 8px 0 14px;
  border-bottom: 1px solid #2b3648;
  color: #9eacc0;
  font-family: var(--font-utility);
  font-size: 10px;
  text-transform: lowercase;
}

.markdown-body :deep(.copy-code) {
  display: inline-flex;
  min-height: 32px;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  border-radius: 6px;
  color: #c8d3e1;
  background: transparent;
  font-size: 10px;
  text-transform: none;
}

.markdown-body :deep(.copy-code:hover) {
  color: white;
  background: #263247;
}

.markdown-body :deep(.copy-symbol) {
  font-family: var(--font-mono);
  font-size: 13px;
}

.markdown-body :deep(pre) {
  max-width: 100%;
  margin: 0;
  padding: 16px 17px;
  overflow-x: auto;
  color: #e5edf8;
  background: #111827;
  font-size: 12px;
  line-height: 1.65;
  tab-size: 2;
}

.markdown-body :deep(pre code) {
  padding: 0;
  border: 0;
  border-radius: 0;
  color: inherit;
  background: transparent;
  font-size: inherit;
  white-space: pre;
  overflow-wrap: normal;
}

.markdown-body :deep(.table-scroll) {
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
}

.markdown-body :deep(table) {
  width: 100%;
  min-width: 460px;
  border-collapse: collapse;
  font-size: 12.5px;
  line-height: 1.5;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 10px 12px;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}

.markdown-body :deep(th:last-child),
.markdown-body :deep(td:last-child) {
  border-right: 0;
}

.markdown-body :deep(tr:last-child td) {
  border-bottom: 0;
}

.markdown-body :deep(th) {
  color: var(--ink-soft);
  background: var(--surface-subtle);
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.markdown-body :deep(tbody tr:hover) {
  background: #fafbfd;
}

.markdown-body :deep(hr) {
  height: 1px;
  margin: 24px 0;
  border: 0;
  background: var(--line);
}

.markdown-body :deep(.image-reference) {
  display: inline-block;
  padding: 2px 7px;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--ink-muted);
  background: var(--surface-subtle);
  font-size: 11px;
}

@media (max-width: 640px) {
  .markdown-body {
    font-size: 14.5px;
  }

  .markdown-body :deep(h1) {
    font-size: 19px;
  }

  .markdown-body :deep(pre) {
    padding: 14px;
    font-size: 11.5px;
  }
}
</style>
