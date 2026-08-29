export type PermissionMode = 'ask' | 'agent' | 'workspace_full'

export interface ApiFailure {
  code: string
  message: string
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  service: string
  model: string
  database: 'ready' | 'unavailable'
  provider_configured: boolean
  allowed_root_label?: string
}
