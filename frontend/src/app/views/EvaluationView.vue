<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useEvaluationStore } from '../../features/evaluations/store'
import type { EvaluationTaskSummary, EvaluationTrial } from '../../features/evaluations/types'
import AppIcon from '../../shared/components/AppIcon.vue'

defineEmits<{ openSidebar: [] }>()

interface TaskCheckSpec {
  sourceName: string
  title: string
  expected: string
}

interface TaskSpec {
  category: string
  prompt: string
  goal: string
  scope: string[]
  checks: TaskCheckSpec[]
}

const taskSpecs: Record<string, TaskSpec> = {
  date_boundary: {
    category: '边界缺陷修复',
    prompt: '修复日志统计的日期结束边界。传入 --end 2026-03-01 时，要包含 3 月 1 日全天的数据，同时补充回归测试。',
    goal: '判断 Agent 能否找到容易忽略的时间边界错误，并且在修复后保留原有行为。',
    scope: ['日期窗口核心逻辑', 'Service 测试', 'CLI 测试'],
    checks: [
      { sourceName: 'candidate test suite', title: '候选测试套件通过', expected: '原有测试与新增测试均无失败项。' },
      { sourceName: 'regression test added', title: '新增回归测试', expected: '测试数量必须多于原始模板的 4 项。' },
      { sourceName: 'inclusive end-of-day and exclusive next midnight', title: '包含结束日全天，但排除次日零点', expected: '查询 3 月 1 日应得到 3 条记录：INFO 2 条、ERROR 1 条。' },
      { sourceName: 'existing unfiltered behavior', title: '不筛选日期时旧功能不变', expected: '仍得到原来的 5 条记录及完整日志级别统计。' },
    ],
  },
  category_filter: {
    category: '多文件功能开发',
    prompt: '为费用统计增加可重复使用的 --category NAME 参数，让筛选能力贯穿 CLI 和 Service，并保持不传参数时的旧行为。',
    goal: '判断 Agent 能否完成跨 CLI、Service 和测试的功能改动，而不是只修改一个入口文件。',
    scope: ['CLI 参数', 'Service 逻辑', '汇总结果', '回归测试'],
    checks: [
      { sourceName: 'candidate test suite', title: '候选测试套件通过', expected: '原有测试与新增测试均无失败项。' },
      { sourceName: 'regression test added', title: '新增回归测试', expected: '测试数量必须多于原始模板的 4 项。' },
      { sourceName: 'single category', title: '单类别筛选正确', expected: '筛选 food 后得到 2 条记录，总金额 1500 分。' },
      { sourceName: 'multiple categories', title: '多个类别可以组合筛选', expected: '筛选 food 和 travel 后得到 3 条记录，总金额 2300 分。' },
      { sourceName: 'missing category is empty', title: '不存在的类别返回空结果', expected: '记录数和总金额都是 0，不应报错或回退到全部数据。' },
      { sourceName: 'existing unfiltered behavior', title: '不传类别时旧功能不变', expected: '仍得到全部 4 条记录，总金额 4800 分。' },
    ],
  },
  config_precedence: {
    category: '配置优先级回归',
    prompt: '修复配置合并逻辑：0、False 和空字符串是用户明确传入的值，不能因为是假值就回退到下一层配置。',
    goal: '判断 Agent 能否区分“没有提供值”和“明确提供了假值”，并保持 CLI、环境变量、配置文件的优先级。',
    scope: ['CLI 配置', '环境变量', '配置文件', '加载器测试'],
    checks: [
      { sourceName: 'candidate test suite', title: '候选测试套件通过', expected: '原有测试与新增测试均无失败项。' },
      { sourceName: 'regression test added', title: '新增回归测试', expected: '测试数量必须多于原始模板的 4 项。' },
      { sourceName: 'CLI falsey values override environment', title: 'CLI 的假值覆盖环境变量', expected: 'retries=0、debug=False、label="" 必须原样保留。' },
      { sourceName: 'environment falsey values override file', title: '环境变量的假值覆盖配置文件', expected: '环境变量显式给出的 0、False 和空字符串不能被文件值替换。' },
      { sourceName: 'existing file behavior', title: '只使用配置文件时旧行为不变', expected: '仍读取 retries=7、debug=True、label="file"。' },
    ],
  },
}

const fallbackSpec: TaskSpec = {
  category: '编码任务',
  prompt: 'Agent 在固定模板工作区中完成任务，并自行运行测试。',
  goal: '验证 Agent 能否形成从理解、修改到测试的完整闭环。',
  scope: ['代码修改', '自动测试'],
  checks: [],
}

const evaluations = useEvaluationStore()
const run = computed(() => evaluations.current)
const trials = computed(() => run.value?.trials ?? [])
const taskEntries = computed<[string, EvaluationTaskSummary][]>(() =>
  Object.entries(run.value?.tasks ?? {}),
)
const taskReports = computed(() =>
  taskEntries.value.map(([taskId, task]) => {
    const spec = taskSpecs[taskId] ?? fallbackSpec
    const currentTrials = trials.value.filter((trial) => trial.task_id === taskId)
    const verificationChecks = currentTrials[0]?.verification.checks ?? []
    const files = [...new Set(currentTrials.flatMap((trial) => [
      ...trial.workspace.added,
      ...trial.workspace.modified,
      ...trial.workspace.deleted,
    ]))]

    return {
      taskId,
      task,
      spec,
      trials: currentTrials,
      files,
      checks: spec.checks.map((check) => ({
        ...check,
        actual: verificationChecks.find((item) => item.name === check.sourceName),
      })),
    }
  }),
)
const allVerified = computed(
  () => Boolean(run.value?.total_trials) && run.value?.verified_successes === run.value?.total_trials,
)
const totalModelCalls = computed(() => trials.value.reduce((total, trial) => total + trial.agent.model_calls, 0))
const totalToolCalls = computed(() => trials.value.reduce((total, trial) => total + trial.agent.tool_calls, 0))
const totalToolFailures = computed(() => trials.value.reduce((total, trial) => total + trial.agent.failed_tools, 0))

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
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`
  return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`
}

function formatDate(value: string | undefined): string {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date)
}

function runLabel(runId: string): string {
  if (runId.startsWith('formal-3x3')) return '正式 3×3'
  if (runId.startsWith('smoke-')) return '单任务试跑'
  return runId
}

function changedFiles(trial: EvaluationTrial): number {
  return trial.workspace.added.length + trial.workspace.modified.length + trial.workspace.deleted.length
}

onMounted(() => void evaluations.load())
</script>

<template>
  <section class="evaluation-view">
    <header class="evaluation-header">
      <button class="icon-button mobile-menu" type="button" aria-label="打开工作区与会话" @click="$emit('openSidebar')"><AppIcon name="menu" /></button>
      <div class="header-title"><strong>评测结果</strong><span>固定任务独立验收</span></div>
      <div class="header-actions">
        <label for="evaluation-run">评测批次</label>
        <select id="evaluation-run" :value="run?.run_id ?? ''" :disabled="evaluations.loading || evaluations.items.length === 0" @change="selectRun">
          <option v-if="evaluations.items.length === 0" value="">暂无报告</option>
          <option v-for="item in evaluations.items" :key="item.run_id" :value="item.run_id">{{ runLabel(item.run_id) }} · {{ item.verified_successes }}/{{ item.total_trials }}</option>
        </select>
        <button class="icon-button refresh-button" type="button" aria-label="刷新评测报告" title="刷新评测报告" :disabled="evaluations.loading" @click="refresh"><AppIcon name="refresh" /></button>
      </div>
    </header>

    <div class="evaluation-scroll">
      <div v-if="evaluations.error" class="state-panel" role="alert">
        <span class="state-icon danger"><AppIcon name="close" /></span><h1>评测报告没有加载</h1><p>{{ evaluations.error }}</p>
        <button class="secondary-button" type="button" @click="refresh">重新读取</button>
      </div>
      <div v-else-if="evaluations.loading && !run" class="state-panel loading-state" aria-live="polite">
        <span class="loading-pulse" /><h1>正在整理评测记录</h1><p>读取任务、每轮执行结果和独立验收记录。</p>
      </div>
      <div v-else-if="!run" class="state-panel">
        <span class="state-icon"><AppIcon name="beaker" /></span><h1>还没有可展示的评测</h1><p>运行 benchmark 后，报告会自动出现在这里。</p>
        <code>python -m evaluation.run_benchmark --model deepseek-v4-flash --repeats 3</code>
      </div>

      <main v-else class="evaluation-content">
        <section class="result-overview" :class="{ complete: allVerified }">
          <div class="result-score">
            <span class="result-label">独立验收结果</span>
            <h1><strong>{{ run.verified_successes }}</strong><i>/</i>{{ run.total_trials }}</h1>
            <p>{{ allVerified ? '3 类任务 × 3 次独立运行，全部通过验收' : '存在未通过的任务轮次' }}</p>
          </div>
          <div class="result-summary">
            <h2>评测任务覆盖</h2>
            <p>3 类任务 × 3 次独立运行；每轮均由固定原始模板初始化。</p>
            <ul>
              <li v-for="report in taskReports" :key="report.taskId">
                <span>{{ report.spec.category }}</span><strong>{{ report.task.title }}</strong><b>{{ report.task.successes }}/{{ report.task.runs }} 通过</b>
              </li>
            </ul>
          </div>
          <div class="run-meta">
            <span><b>模型</b>{{ run.model_requested }}</span><span><b>代码提交</b><code>{{ run.source_commit?.slice(0, 8) ?? 'unknown' }}</code></span>
            <span><b>源码状态</b>{{ run.source_dirty ? '有未提交改动' : '干净工作区' }}</span><span><b>开始时间</b>{{ formatDate(trials[0]?.started_at) }}</span>
          </div>
        </section>

        <section class="method-panel" aria-labelledby="method-title">
          <div class="method-intro">
            <span class="section-kicker">判定方法</span><h2 id="method-title">独立验收机制</h2>
            <p>成功结论仅依据候选工作区测试与外部验收结果，不采信模型自述。</p>
          </div>
          <ol class="method-steps">
            <li><span>01</span><div><strong>工作区初始化</strong><p>从固定模板创建独立候选工作区，隔离各轮修改。</p></div></li>
            <li><span>02</span><div><strong>Agent 执行</strong><p>完成任务理解、文件修改、命令执行与候选测试。</p></div></li>
            <li><span>03</span><div><strong>独立验收</strong><p>外部脚本验证目标行为、回归测试与兼容性。</p></div></li>
          </ol>
        </section>

        <section class="content-section task-section">
          <div class="section-heading"><div><span class="section-kicker">评测明细</span><h2>任务定义与验收标准</h2></div><p>每类任务分别列示输入要求、实际改动范围、独立验收项与重复运行结果。</p></div>
          <div class="task-list">
            <article v-for="report in taskReports" :key="report.taskId" class="task-report">
              <header class="task-report-header">
                <div class="task-heading-copy"><span class="task-category">{{ report.spec.category }}</span><h3>{{ report.task.title }}</h3><p>{{ report.spec.goal }}</p></div>
                <div class="task-result" :class="{ passed: report.task.successes === report.task.runs }"><span>重复运行结果</span><strong>{{ report.task.successes }}/{{ report.task.runs }}</strong><small>{{ report.task.successes === report.task.runs ? '通过率 100%' : '存在失败轮次' }}</small></div>
              </header>
              <div class="task-report-body">
                <section class="task-brief">
                  <div class="brief-title"><AppIcon name="terminal" /><strong>任务输入</strong></div>
                  <p class="task-prompt">{{ report.spec.prompt }}</p>
                  <div class="brief-group"><span>预期改动范围</span><div class="scope-tags"><b v-for="item in report.spec.scope" :key="item">{{ item }}</b></div></div>
                  <div class="brief-group"><span>候选工作区实际变更</span><div v-if="report.files.length" class="file-list"><code v-for="file in report.files" :key="file">{{ file }}</code></div><p v-else class="muted-copy">没有记录到文件变化。</p></div>
                </section>
                <section class="task-checks">
                  <div class="checks-heading"><div><AppIcon name="shield" /><strong>独立验收项</strong></div><span>3 轮验收标准一致</span></div>
                  <ol>
                    <li v-for="check in report.checks" :key="check.sourceName" :class="{ failed: check.actual && !check.actual.passed }">
                      <span class="check-state"><AppIcon :name="check.actual?.passed ? 'check' : 'close'" /></span>
                      <div class="check-copy"><strong>{{ check.title }}</strong><p>{{ check.expected }}</p><details v-if="check.actual?.detail"><summary>原始验收输出</summary><code>{{ check.actual.detail }}</code></details></div>
                    </li>
                  </ol>
                </section>
              </div>
              <footer class="task-rounds" aria-label="该任务三轮执行状态">
                <div v-for="trial in report.trials" :key="trial.trial_id" :class="{ passed: trial.verification.passed }">
                  <span><AppIcon :name="trial.verification.passed ? 'check' : 'close'" />第 {{ trial.repeat_index }} 次</span><strong>{{ trial.verification.passed ? '全部验收通过' : '验收未通过' }}</strong>
                  <small>{{ formatDuration(trial.agent.duration_ms / 1000) }} · {{ trial.agent.model_calls }} 次模型调用 · {{ trial.agent.tool_calls }} 次工具调用</small>
                </div>
              </footer>
            </article>
          </div>
        </section>

        <section class="content-section metric-section">
          <div class="section-heading compact-heading"><div><span class="section-kicker">执行数据</span><h2>九轮整体表现</h2></div><p>这些数据用于观察执行效率，正确性仍以外部验收结果为准。</p></div>
          <div class="metric-strip" aria-label="评测汇总指标">
            <div><span>平均耗时</span><strong>{{ formatDuration(run.duration_seconds.mean) }}</strong><small>最长 {{ formatDuration(run.duration_seconds.maximum) }}</small></div>
            <div><span>中位 Token</span><strong>{{ formatCompact(run.total_tokens.median) }}</strong><small>均值 {{ formatCompact(run.total_tokens.mean) }}</small></div>
            <div><span>模型 / 工具调用</span><strong>{{ totalModelCalls }} <i>/</i> {{ totalToolCalls }}</strong><small>九轮累计</small></div>
            <div><span>工具错误结果</span><strong>{{ totalToolFailures }}</strong><small>错误会回填给模型继续处理</small></div>
          </div>
        </section>

        <section class="content-section trial-section">
          <div class="section-heading compact-heading"><div><span class="section-kicker">逐轮记录</span><h2>每次运行的资源消耗</h2></div><p>用于比较同一任务重复运行时的稳定性和执行成本。</p></div>
          <div class="trial-table-wrap">
            <table><thead><tr><th>任务 / 次数</th><th>验收结论</th><th>模型调用</th><th>工具调用</th><th>Token</th><th>耗时</th><th>文件变化</th></tr></thead>
              <tbody><tr v-for="trial in trials" :key="trial.trial_id">
                <td><strong>{{ trial.task_title }}</strong><span>第 {{ trial.repeat_index }} 次独立运行</span></td>
                <td><span class="result-pill" :class="{ passed: trial.verification.passed }"><AppIcon :name="trial.verification.passed ? 'check' : 'close'" />{{ trial.verification.passed ? '全部验收通过' : '未通过' }}</span></td>
                <td class="numeric">{{ trial.agent.model_calls }}</td><td class="numeric"><strong>{{ trial.agent.tool_calls }}</strong><small v-if="trial.agent.failed_tools">其中 {{ trial.agent.failed_tools }} 次返回错误</small></td>
                <td class="numeric">{{ formatInteger(trial.agent.usage.total_tokens ?? 0) }}</td><td class="numeric">{{ formatDuration(trial.agent.duration_ms / 1000) }}</td><td class="numeric">{{ changedFiles(trial) }} 个</td>
              </tr></tbody>
            </table>
          </div>
        </section>

        <footer class="method-note"><AppIcon name="shield" /><p><strong>结果边界</strong>本页证明 Agent 在 3 类固定 Python 任务中完成了 9 次代码修改与外部验收，不代表大型仓库、其他语言或操作系统级隔离能力。</p></footer>
      </main>
    </div>
  </section>
</template>

<style scoped src="./EvaluationView.css"></style>
