export interface MemoryEntry {
  id: string
  workspace_id: string
  kind: 'preference' | 'fact' | 'decision' | 'note'
  content: string
  pinned: boolean
  enabled: boolean
  created_at: string
  updated_at: string
}
