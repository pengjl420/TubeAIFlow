import { apiClient, unwrap } from './client'

export interface TtsStatus {
  total: number
  completed: number
  failed: number
  pending: number
  project_status?: string
  segments?: {
    segment_id: string
    status: string
    audio_path?: string | null
    duration?: number | null
    error_message?: string | null
    updated_at?: string | null
  }[]
  progress?: {
    total?: number
    completed?: number
    failed?: number
    current_segment_id?: string | null
    current_index?: number
    status?: string
  } | null
}

export async function startTts(projectId: string) {
  // IndexTTS loads a large model and may run for several minutes.
  return unwrap(await apiClient.post(`/projects/${projectId}/tts/start`, undefined, { timeout: 0 }))
}

export async function getTtsStatus(projectId: string): Promise<TtsStatus> {
  return unwrap<TtsStatus>(await apiClient.get(`/projects/${projectId}/tts/status`))
}

export async function regenerateSegmentTts(projectId: string, segmentId: string) {
  return unwrap(await apiClient.post(`/projects/${projectId}/tts/regenerate/${segmentId}`, undefined, { timeout: 0 }))
}
