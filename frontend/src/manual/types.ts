import type {SyncResult} from '../types'

interface Dimensions {width: number; height: number}

export interface ManualDetail {
  asset: string
  kind: string
  path: string
  version: string
  exists: boolean
  fields: Record<string, string>
  nfo_valid: boolean
  nfo?: string
  image: Dimensions | {damaged: true} | null
  image_url?: string
  requirements: {min_width: number; min_height: number}[]
  reasons: string[]
  blocked_fields: string[]
}

export interface ManualCandidate {label: string; nfo?: string; image?: string; error?: string}
export interface ManualCandidateList {items: ManualCandidate[]; message?: string}
export interface ManualChange {fields?: Record<string, string>; nfo?: string; image?: string}
export interface ManualPreview {
  changed: boolean
  fields: Record<string, {before: string; after: string}>
  image: Dimensions | null
  remaining_reasons: string[]
}
export interface ManualResult {
  changed: boolean
  remaining_reasons: string[]
  sync: SyncResult[]
  message: string
}
