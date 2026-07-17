export interface MediaKeyframe {
  id: string
  frame_index: number
  timestamp_ms: number
  url: string
}

export type LibraryRole = 'semantic' | 'themed_fallback' | 'landscape_fallback'
export type ReviewStatus = 'pending' | 'approved' | 'rejected'

export interface MediaShot {
  id: string
  shot_index: number
  start_ms: number
  end_ms: number | null
  description: string
  tags: string[]
  thumbnail_path: string | null
  thumbnail_url: string | null
  keyframes: MediaKeyframe[]
  vector_id: number | null
  vector_model: string | null
  library_role: LibraryRole
  fallback_category: string
  mood: string
  status: string
  technical: Record<string, unknown>
}

export interface MediaAsset {
  id: string
  provider: string
  provider_asset_id: string | null
  path: string
  filename: string
  media_type: 'video' | 'image'
  file_hash: string
  size_bytes: number
  duration_ms: number | null
  width: number | null
  height: number | null
  library_role: LibraryRole
  fallback_category: string
  mood: string
  review_status: ReviewStatus
  enabled: boolean
  status: string
  created_at: string
  shots: MediaShot[]
}

export interface SceneCandidate {
  id: string
  scene_id: string
  media_shot_id: string
  source: string
  query: string
  scores: {
    semantic: number
    text: number
    tags: number
    technical: number
    total: number
  }
  status: 'NO_RESULT' | 'LOW_RELEVANCE' | 'QUALIFIED' | 'FALLBACK_REQUIRED'
  selection_stage: 'local_semantic' | 'remote_semantic' | 'themed_fallback' | 'landscape_fallback'
  is_fallback: boolean
  conflicts: string[]
  retrieval: {
    vector_model: string | null
    vector_id: number | null
  }
  shot: MediaShot
  media: {
    id: string
    filename: string
    path: string
    media_type: 'video' | 'image'
    duration_ms: number | null
    width: number | null
    height: number | null
    provider: string
    library_role: LibraryRole
    fallback_category: string
    mood: string
  }
}

export interface AssetImportResult {
  directory: string
  discovered: number
  imported: Array<Omit<MediaAsset, 'shots'>>
  skipped: Array<{ path: string; reason: string; media_id: string }>
  errors: Array<{ path: string; error: string }>
}

export interface SceneSearchResult {
  scene_id: string
  status: string
  candidates: SceneCandidate[]
  online_search?: Array<{
    provider: 'pexels' | 'pixabay'
    status: string
    reset_at?: string | null
    downloaded: string[]
    errors: Array<{ asset_id: string; error: string }>
  }>
}
