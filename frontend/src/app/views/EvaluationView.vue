<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useEvaluationStore } from '../../features/evaluations/store'
import type { EvaluationCheck, EvaluationTaskSummary, EvaluationTrial } from '../../features/evaluations/types'
import AppIcon from '../../shared/components/AppIcon.vue'

defineEmits<{ openSidebar: [] }>()

const evaluations = useEvaluationStore()
const run = computed(() => evaluations.current)
const trials = computed(() => run.value?.trials ?? [])
const taskEntries = computed<[string, EvaluationTaskSummary][]>(() =>
  Object.entries(run.value?.tasks ?? {}),
)
const allVerified = computed(
  () => Boolean(run.value?.total_trials) && run.value?.verified_successes === run.value?.total_trials,
)
const totalModelCalls = computed(() =>
  trials.value.reduce((total, trial) => total + trial.agent.model_calls, 0),
)
const totalToolCalls = computed(() =>
  trials.value.reduce((total, trial) => total + trial.agent.tool_calls, 0),
)
const totalToolFailures = computed(() =>
  trials.value.reduce((total, trial) => total + trial.agent.failed_tools, 0),
)

const taskDescriptions: Record<string, string> = {
  date_boundary: '定位包含式日期上界缺陷，修改核心逻辑并补充边界回归测试。',
  category_filter: '跨 CLI、Service 与测试实现可重复类别筛选，并保持旧输出兼容。',
  config_precedence: '沿 CLI、环境变量和文件的数据流修复 0、False 与空字符串回退。',
}

const taskShortNames: Record<string, string> = {
  date_boundary: '日期',
  category_filter: '类别',
  config_precedence: '配置',
}

async function selectRun(event: Event): Promise<void> {
  const runId = (event.target as HTMLSelectElement).value
  if (runId) await evaluations.open(runId)
}

function refresh(): void {
  void evaluations.load(run.value?.run_id)
}

function formatInteger(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatCompact(value: number): string {
  return new Intl.NumberFormat('zh-CN', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`
  return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`
}

function formatDate(value: string | undefined): string {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function runLabel(runId: string): string {
  if (runId.startsWith('formal-3x3')) return '正式 3×3'
  if (runId.startsWith('smoke-')) return '单任务 smoke'
  return runId
}

function taskDescription(taskId: string): string {
  return taskDescriptions[taskId] ?? '由固定任务模板、全新工作区和独立验收器完成验证。'
}

function shortTask(trial: EvaluationTrial): string {
  return taskShortNames[trial.task_id] ?? trial.task_title.slice(0, 2)
}

function checksForTask(taskId: string): EvaluationCheck[] {
  return trials.value.find((trial) => trial.task_id === taskId)?.verification.checks ?? []
}

function changedFiles(trial: EvaluationTrial): number {
  return trial.workspace.added.length + trial.workspace.modified.length + trial.workspace.deleted.length
}

onMounted(() => void evaluations.load())
</script>

<template>
  <section class="evaluation-view">
    <header class="evaluation-header">
      <button class="icon-button mobile-menu" type="button" aria-label="打开工作区与会话" @click="$emit('openSidebar')">
        <AppIcon name="menu" />
      </button>
      <div class="header-title">
        <span>Benchmark ledger</span>
        <strong>评测结果</strong>
      </div>
      <div class="header-actions">
        <label for="evaluation-run">评测批次</label>
        <select id="evaluation-run" :value="run?.run_id ?? ''" :disabled="evaluations.loading || evaluations.items.length === 0" @change="selectRun">
          <option v-if="evaluations.items.length === 0" value="">暂无报告</option>
          <option v-for="item in evaluations.items" :key="item.run_id" :value="item.run_id">
            {{ runLabel(item.run_id) }} · {{ item.verified_successes }}/{{ item.total_trials }}
          </option>
        </select>
        <button class="icon-button refresh-button" type="button" aria-label="刷新评测报告" title="刷新评测报告" :disabled="evaluations.loading" @click="refresh">
          <AppIcon name="refresh" />
        </button>
      </div>
    </header>

    <div class="evaluation-scroll">
      <div v-if="evaluations.error" class="state-panel" role="alert">
        <span class="state-icon danger"><AppIcon name="close" /></span>
        <h1>评测报告没有加载</h1>
        <p>{{ evaluations.error }}</p>
        <button class="secondary-button" type="button" @click="refresh">重新读取</button>
      </div>

      <div v-else-if="evaluations.loading && !run" class="state-panel loading-state" aria-live="polite">
        <span class="loading-pulse" />
        <h1>正在整理评测记录</h1>
        <p>读取任务、trial、独立验收和调用指标。</p>
      </div>

      <div v-else-if="!run" class="state-panel">
        <span class="state-icon"><AppIcon name="beaker" /></span>
        <h1>还没有可展示的评测</h1>
        <p>运行 benchmark 后，报告会自动出现在这里。</p>
        <code>python -m evaluation.run_benchmark --model deepseek-v4-flash --repeats 3</code>
      </div>

      <main v-else class="evaluation-content">
        <section class="verdict-panel" :class="{ complete: allVerified }">
          <div class="verdict-copy">
            <p class="eyebrow">INDEPENDENT VERIFICATION</p>
            <h1>
              <span>{{ run.verified_successes }}</span><i>/</i>{{ run.total_trials }}
              <small>独立验收通过</small>
            </h1>
            <p class="verdict-description">
              每轮从固定模板复制全新工作区。模型最终回答不计成功，只有工作区外 verifier 全部通过才点亮记录。
            </p>
            <div class="run-meta">
              <span><b>模型</b>{{ run.model_requested }}</span>
              <span><b>提交</b><code>{{ run.source_commit?.slice(0, 8) ?? 'unknown' }}</code></span>
              <span :class="{ warning: run.source_dirty }"><b>源码</b>{{ run.source_dirty ? '有未提交改动' : '干净工作区' }}</span>
              <span><b>开始</b>{{ formatDate(trials[0]?.started_at) }}</span>
            </div>
          </div>

          <div class="track-card">
            <div class="track-heading">
              <div>
                <span>TRIAL RECORD</span>
                <strong>{{ allVerified ? '连续通过' : '存在未通过轮次' }}</strong>
              </div>
              <span class="track-count">{{ trials.length }} runs</span>
            </div>
            <ol class="verification-track" aria-label="试验验证轨道">
              <li v-for="(trial, index) in trials" :key="trial.trial_id" :class="{ passed: trial.verification.passed }" :title="`${trial.task_title} · 第 ${trial.repeat_index} 轮`">
                <span class="track-marker"><AppIcon v-if="trial.verification.passed" name="check" /></span>
                <span class="track-index">{{ String(index + 1).padStart(2, '0') }}</span>
                <strong>{{ shortTask(trial) }}</strong>
                <small>R{{ trial.repeat_index }}</small>
              </li>
            </ol>
          </div>
        </section>

        <section class="metric-strip" aria-label="评测汇总指标">
          <div><span>平均耗时</span><strong>{{ formatDuration(run.duration_seconds.mean) }}</strong><small>最长 {{ formatDuration(run.duration_seconds.maximum) }}</small></div>
          <div><span>中位 Token</span><strong>{{ formatCompact(run.total_tokens.median) }}</strong><small>均值 {{ formatCompact(run.total_tokens.mean) }}</small></div>
          <div><span>模型 / 工具调用</span><strong>{{ totalModelCalls }} <i>/</i> {{ totalToolCalls }}</strong><small>九轮累计</small></div>
          <div><span>工具错误结果</span><strong>{{ totalToolFailures }}</strong><small>均被回填并继续执行</small></div>
        </section>

        <section class="content-section">
          <div class="section-heading">
            <div><span>WHAT WAS TESTED</span><h2>测了什么</h2></div>
            <p>{{ taskEntries.length }} 类任务，覆盖 Bug 修复、多文件功能和跨来源回归。</p>
          </div>
          <div class="task-grid">
            <article v-for="([taskId, task], index) in taskEntries" :key="taskId" class="task-card">
              <span class="task-sequence">{{ String(index + 1).padStart(2, '0') }}</span>
              <div class="task-title-row"><h3>{{ task.title }}</h3><span>{{ task.successes }}/{{ task.runs }}</span></div>
              <p>{{ taskDescription(taskId) }}</p>
              <div class="task-meter"><span :style="{ width: `${task.success_rate * 100}%` }" /></div>
              <small>固定模板 · 隐藏验收 · {{ Math.round(task.success_rate * 100) }}% 通过</small>
            </article>
          </div>
        </section>

        <section class="content-section trial-section">
          <div class="section-heading">
            <div><span>RUN BY RUN</span><h2>每轮结果</h2></div>
            <p>调用量和失败工具用于观察效率，不替代 verifier 的正确性结论。</p>
          </div>
          <div class="trial-table-wrap">
            <table>
              <thead>
                <tr><th>任务 / 轮次</th><th>结论</th><th>模型调用</th><th>工具调用</th><th>Token</th><th>耗时</th><th>文件变化</th></tr>
              </thead>
              <tbody>
                <tr v-for="trial in trials" :key="trial.trial_id">
                  <td><strong>{{ trial.task_title }}</strong><span>Round {{ trial.repeat_index }}</span></td>
                  <td><span class="result-pill" :class="{ passed: trial.verification.passed }"><AppIcon :name="trial.verification.passed ? 'check' : 'close'" />{{ trial.verification.passed ? '通过' : trial.classification }}</span></td>
                  <td class="numeric">{{ trial.agent.model_calls }}</td>
                  <td class="numeric"><strong>{{ trial.agent.tool_calls }}</strong><small v-if="trial.agent.failed_tools">{{ trial.agent.failed_tools }} 次错误结果</small></td>
                  <td class="numeric">{{ formatInteger(trial.agent.usage.total_tokens ?? 0) }}</td>
                  <td class="numeric">{{ formatDuration(trial.agent.duration_ms / 1000) }}</td>
                  <td class="numeric">{{ changedFiles(trial) }} 个</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="content-section evidence-section">
          <div class="section-heading">
            <div><span>VERIFIER EVIDENCE</span><h2>如何判定成功</h2></div>
            <p>展示每类任务第一轮的验收项；同类三轮使用相同 verifier。</p>
          </div>
          <div class="evidence-grid">
            <article v-for="([taskId, task]) in taskEntries" :key="taskId">
              <header><span><AppIcon name="shield" /></span><div><strong>{{ task.title }}</strong><small>{{ checksForTask(taskId).length }} 项验收</small></div></header>
              <ul>
                <li v-for="check in checksForTask(taskId)" :key="check.name">
                  <AppIcon :name="check.passed ? 'check' : 'close'" />
                  <div><strong>{{ check.name }}</strong><span>{{ check.detail }}</span></div>
                </li>
              </ul>
            </article>
          </div>
        </section>

        <footer class="method-note">
          <AppIcon name="shield" />
          <p><strong>解释边界</strong>这是小样本描述性评测。它证明固定 Python 合成任务上的 Coding Agent 闭环，不代表大型仓库、其他语言或操作系统沙箱能力。</p>
        </footer>
      </main>
    </div>
  </section>
</template>

<style scoped src="./EvaluationView.css"></style>
