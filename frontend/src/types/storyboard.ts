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
  must_include: string[]
  avoid: string[]
  confidence: number
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
