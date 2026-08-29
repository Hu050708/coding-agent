import { defineStore } from 'pinia'
import { ref } from 'vue'

import { localizedError } from '../../shared/api/http'
import type { EvaluationRun, EvaluationRunListItem } from './types'
import { evaluationApi } from './api'

export const useEvaluationStore = defineStore('evaluations', () => {
  const items = ref<EvaluationRunListItem[]>([])
  const current = ref<EvaluationRun | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let generation = 0

  async function load(preferredRunId?: string): Promise<void> {
    const request = ++generation
    loading.value = true
    error.value = null
    try {
      const runs = await evaluationApi.list()
      if (request !== generation) return
      items.value = runs
      const runId =
        preferredRunId && runs.some((item) => item.run_id === preferredRunId)
          ? preferredRunId
          : runs[0]?.run_id
      if (!runId) {
        current.value = null
        return
      }
      const detail = await evaluationApi.get(runId)
      if (request === generation) current.value = detail
    } catch (reason) {
      if (request !== generation) return
      current.value = null
      error.value = localizedError(reason)
    } finally {
      if (request === generation) loading.value = false
    }
  }

  async function open(runId: string): Promise<void> {
    const request = ++generation
    loading.value = true
    error.value = null
    try {
      const detail = await evaluationApi.get(runId)
      if (request === generation) current.value = detail
    } catch (reason) {
      if (request === generation) error.value = localizedError(reason)
    } finally {
      if (request === generation) loading.value = false
    }
  }

  return { items, current, loading, error, load, open }
})
