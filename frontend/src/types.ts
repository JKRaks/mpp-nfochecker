export interface Condition {
  op: string
  field: string
  value: string
}
export interface NfoField {
  value: string
  label: string
  group: string
  kinds: string[]
  note: string
}
export interface ImageCheck {
  type: string
  missing: boolean
  damaged: boolean
  min_width: number
  min_height: number
}
export interface Rule {
  id: string
  name: string
  enabled: boolean
  category: string
  match: string
  conditions: Condition[]
  images: ImageCheck[]
  action: string
  selected_images: string[]
  translation_policy: string
  translation_fields: string[]
}
export interface TranslationInfo {
  enabled: boolean
  message?: string
  fields: Record<string, string>
  policies: { id: string; name: string; target_language: string; fields: string[] }[]
}
export interface RuleSet {
  id: string
  name: string
  enabled: boolean
  roots: string[]
  kinds: string[]
  excludes: string[]
  exclude_regex: string
  exclude_season_zero: boolean
  emby: string
  rules: Rule[]
}
export interface Config {
  version: number
  enabled: boolean
  rule_sets: RuleSet[]
  backup: {
    nfo: boolean
    images: boolean
    directory: string
    cleanup: boolean
    days: number
    versions: number
  }
  batch_limit: number
  auto_continue: boolean
  max_batches_per_run: number
  interval: number
  stable_seconds: number
  cooldown_days: number
  max_no_improvement: number
  history_days: number
  emby_servers: {
    name: string
    libraries: string[]
    mappings: { local: string; remote: string }[]
  }[]
  emby_poll: number
  emby_timeout: number
  notify: string
  notify_channels: string[]
}
export interface Hit {
  name: string
  set: string
  rule: string
  reasons: string[]
  actions?: string[]
}
export interface AssetResult {
  status: string
  message?: string
  path?: string
  error_code?: string
  details?: Record<string, unknown>
  attempts?: number
  next_retry_at?: number
  translation_pending_fields?: string[]
}
export interface SyncResult {
  server: string
  status: string
  message?: string
  submitted?: boolean
  signature?: string
}
export interface Item {
  id: string
  target: { path: string; kind: string }
  status: string
  hits: Hit[]
  remaining_hits?: Hit[]
  remaining_assets?: string[]
  conflicts: string[]
  actions: string[]
  results: Record<string, AssetResult>
  sync: SyncResult[]
  emby_mode?: string
  needs_recheck?: boolean
  translation_conflict?: string
}
export interface RunSummary {
  id: string
  created: number
  updated: number
  status: string
  summary: string
  dry_run: boolean
  item_count: number
  error_count: number
  schema_version?: number
  phase?: string
  outcome?: string
  exit_reason?: string
  counts?: Record<string, number>
  batches?: number
  emby_enabled?: boolean
}
export interface Report extends RunSummary {
  errors: string[]
  items: Item[]
  page: number
  page_size: number
  total: number
  statuses: string[]
  set_ids?: string[]
}
export interface PendingEntry {
  key: string
  target?: { path: string; kind: string }
  server: string
  status: string
  message?: string
  updated: number
  version?: string
}
export interface PendingPage {
  items: PendingEntry[]
  total: number
  page: number
  page_size: number
}
export interface HostProps {
  api: {
    get<T>(path: string, options?: unknown): Promise<T>
    post<T>(path: string, body?: unknown, options?: unknown): Promise<T>
  }
  pluginId: string
}
