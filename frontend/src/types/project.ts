export interface Project {
  id: string
  name: string
  status: string
  output_dir?: string
  reference_audio_path?: string
  config?: {
    reference_audio_filename?: string
    voice_profile_name?: string
    tts_engine?: string
    include_video?: boolean
    video_mode?: VideoGenerationMode
    semantic_review_mode?: SemanticReviewMode
    video_output_format?: VideoOutputFormat
    storyboard_transition_enabled?: boolean
    segmentation_mode?: SegmentationMode
    storyboard_mode?: StoryboardMode
    [key: string]: unknown
  }
  config_json?: string
  created_at: string
  updated_at: string
  audio_duration_seconds?: number
  workflow_started_at?: string | null
  workflow_finished_at?: string | null
  workflow_duration_seconds?: number | null
  latest_task_status?: string | null
}

export type VideoGenerationMode = 'none' | 'landscape' | 'ai_semantic' | 'ai_generated_images'
export type SemanticReviewMode = 'manual' | 'automatic'
export type VideoOutputFormat = 'mp4' | 'fcpxml'
export type SegmentationMode = 'newline' | 'ai'
export type StoryboardMode = 'ai' | 'segments'
