export interface Segment {
  id: string
  segment_id: string
  project_id: string
  segment_index: number
  text: string
  status: string
  audio_path?: string
  duration?: number
  error_message?: string
  created_at?: string
  updated_at?: string
}
