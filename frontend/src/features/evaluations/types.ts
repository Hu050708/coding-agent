export interface EvaluationMetricStats {
  mean: number
  median: number
  maximum: number
}

export interface EvaluationTaskSummary {
  title: string
  runs: number
  successes: number
  success_rate: number
}

export interface EvaluationCheck {
  name: string
  passed: boolean
  detail: string
}

export interface EvaluationTrial {
  trial_id: string
  task_id: string
  task_title: string
  category: string
  repeat_index: number
  started_at: string
  classification: string
  agent_exit_code: number | null
  agent: {
    status: string | null
    reason: string | null
    model_calls: number
    tool_calls: number
    usage: Record<string, number>
    duration_ms: number
    successful_tools: number
    failed_tools: number
    tool_counts: Record<string, number>
    error_counts: Record<string, number>
    repeat_warnings: number
  }
  workspace: {
    added: string[]
    modified: string[]
    deleted: string[]
  }
  verification: {
    passed: boolean
    exit_code: number | null
    checks: EvaluationCheck[]
    error: string | null
  }
}

export interface EvaluationRunListItem {
  run_id: string
  model_requested: string
  source_commit: string | null
  source_dirty: boolean | null
  total_trials: number
  verified_successes: number
  verified_success_rate: number
  end_to_end_successes: number
  end_to_end_success_rate: number
  duration_seconds: EvaluationMetricStats
  total_tokens: EvaluationMetricStats
  tasks: Record<string, EvaluationTaskSummary>
}

export interface EvaluationRun extends EvaluationRunListItem {
  classifications: Record<string, number>
  trials: EvaluationTrial[]
}
