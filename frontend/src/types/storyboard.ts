export interface SubtitleCue {
  id: string
  project_id: string
  source_segment_id: string
  cue_index: number
  start_ms: number
  end_ms: number
  text: string
}

export interface StoryboardContent {
  visual_summary: string
  visual_type: string
  entities: string[]
  locations: string[]
  time_period: string
  scene_category: string
  mood: string
  shot_preference: string
  primary_query: string
  alternative_queries: string[]
  fallback_category: string
  fallback_mood: string
  allow_landscape_fallback: boolean
  must_include: string[]
  avoid: string[]
  confidence: number
  motion_prompt: string
  scene_type: string
  importance_score: number
  motion_score: number
  identity_risk: number
  text_density: number
  subject_count: number
  recommended_source: string
  fact_risk: 'none' | 'low' | 'medium' | 'high'
  visual_brief?: {
    subject: string
    action: string
    environment: string
    semantic_message: string
    composition: string
    camera: string
    era: string
    mood: string
    must_include: string[]
    must_avoid: string[]
  } | null
  image_prompt: string
  negative_prompt: string
}

export interface VisualScene {
  id: string
  project_id?: string
  scene_index: number
  start_ms: number
  end_ms: number
  narration: string
  subtitle_ids: string[]
  storyboard?: StoryboardContent | null
  confidence?: number | null
  status: string
  locked_text: boolean
  locked_audio: boolean
  locked_visual: boolean
  version: number
}

export interface SceneRevision {
  id: string
  scene_id: string
  version: number
  change_type: string
  created_at: string
}

export interface SrtImportResult {
  count: number
  start_ms: number
  end_ms: number
  changed: boolean
  path: string
  cues: SubtitleCue[]
}

export interface StoryboardGenerateResult {
  scenes: VisualScene[]
  warnings: string[]
  model: string
  path?: string
}
