export type MemoryKind = 'preference' | 'fact' | 'decision' | 'note'
export type MemorySource = 'manual' | 'run_result'

export interface MemoryEntry {
  id: string
  workspace: string
  kind: MemoryKind
  content: string
  source: MemorySource
  source_run_id: string | null
  pinned: boolean
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface CreateMemoryRequest {
  workspace: string
  kind: MemoryKind
  content: string
  pinned: boolean
  source_run_id?: string
}

export interface UpdateMemoryRequest {
  workspace: string
  kind?: MemoryKind
  content?: string
  pinned?: boolean
  enabled?: boolean
}

export type CreateMemoryInput = Omit<CreateMemoryRequest, 'workspace'>
export type UpdateMemoryInput = Omit<UpdateMemoryRequest, 'workspace'>

export interface MemoryApi {
  list(workspace: string, signal?: AbortSignal): Promise<MemoryEntry[]>
  create(request: CreateMemoryRequest, signal?: AbortSignal): Promise<MemoryEntry>
  update(id: string, request: UpdateMemoryRequest, signal?: AbortSignal): Promise<MemoryEntry>
  remove(id: string, workspace: string, signal?: AbortSignal): Promise<void>
  purge(workspace: string, signal?: AbortSignal): Promise<number>
}

export type MemoryPhase = 'idle' | 'loading' | 'success' | 'error'

export interface MemoryState {
  phase: MemoryPhase
  workspace: string
  items: MemoryEntry[]
  message: string | null
  busy: boolean
}
