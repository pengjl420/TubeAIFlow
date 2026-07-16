export interface Segment {
  id: string
  segment_id: string
  project_id: string
  segment_index: number
  text_zh: string
  text_en?: string
  status: string
  audio_path?: string
  duration?: number
  error_message?: string
  created_at?: string
  updated_at?: string
}
