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
  selection_stage: 'local_semantic' | 'remote_semantic' | 'themed_fallback' | 'landscape_fallback' | 'manual_upload' | 'local_generated_image'
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
  auto_fallback?: {
    selected_assignment_ids: string[]
    covered_ms: number
    remaining_ms: number
    complete: boolean
    ratio_threshold_exceeded: boolean
  }
}

export interface SceneCoverage {
  covered_ms: number
  duration_ms: number
  remaining_ms: number
  complete: boolean
  review_required: boolean
}

export interface SceneAssignment {
  id: string
  candidate_id: string | null
  media_shot_id: string
  sequence_index: number
  scene_offset_start_ms: number
  scene_offset_end_ms: number
  trim_start_ms: number
  trim_end_ms: number | null
  playback_speed: number
  display_duration_ms: number | null
  motion_type:
    | 'auto'
    | 'static'
    | 'slow_zoom_in'
    | 'slow_zoom_out'
    | 'pan_left_to_right'
    | 'pan_right_to_left'
    | 'pan_top_to_bottom'
    | 'pan_bottom_to_top'
    | 'diagonal_top_left'
    | 'diagonal_top_right'
    | 'portrait_push_in'
    | 'environment_pull_out'
    | 'subtle_breathing'
    | 'random_safe'
    | 'zoom_in'
    | 'zoom_out'
    | 'pan_left'
    | 'pan_right'
    | 'still'
  zoom_start: number
  zoom_end: number
  pan_direction: 'center' | 'left' | 'right' | 'up' | 'down'
  crop_anchor: 'center' | 'left' | 'right' | 'top' | 'bottom'
  transition: string
  manual_confirmed: boolean
  selection_stage: SceneCandidate['selection_stage'] | 'manual'
  selection_reason: string
  is_fallback: boolean
  shot: MediaShot
  media: {
    id: string
    filename: string
    media_type: 'video' | 'image'
    duration_ms: number | null
    width: number | null
    height: number | null
    provider: string
  }
}

export interface SceneAssignmentTrack {
  assignments: SceneAssignment[]
  coverage: SceneCoverage
}
