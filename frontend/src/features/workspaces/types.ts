export interface Workspace {
  id: string
  display_name: string
  path_hint?: string
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface DirectoryEntry {
  name: string
  path: string
  selectable: boolean
}

export interface DirectoryListing {
  current_path: string
  parent_path: string | null
  allowed_root: string
  entries: DirectoryEntry[]
}
