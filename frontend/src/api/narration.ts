import { apiClient, unwrap } from './client'
import type { Segment } from '../types/narration'

export async function listSegments(projectId: string): Promise<Segment[]> {
  return unwrap<Segment[]>(await apiClient.get(`/projects/${projectId}/segments`))
}

export async function updateSegment(
  projectId: string,
  segmentId: string,
  payload: Partial<Pick<Segment, 'text'>>,
): Promise<Segment> {
  return unwrap<Segment>(await apiClient.put(`/projects/${projectId}/segments/${segmentId}`, payload))
}

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
  // Local TTS engines load large models and may run for several minutes.
  return unwrap(await apiClient.post(`/projects/${projectId}/tts/start`, undefined, { timeout: 0 }))
}

export async function getTtsStatus(projectId: string): Promise<TtsStatus> {
  return unwrap<TtsStatus>(await apiClient.get(`/projects/${projectId}/tts/status`))
}

export async function regenerateSegmentTts(projectId: string, segmentId: string) {
  return unwrap(await apiClient.post(`/projects/${projectId}/tts/regenerate/${segmentId}`, undefined, { timeout: 0 }))
}

export async function createTimeline(projectId: string) {
  return unwrap(await apiClient.post(`/projects/${projectId}/timeline`))
}

export async function createSrt(projectId: string) {
  return unwrap<{
    srt_path: string
    segments: number
  }>(await apiClient.post(`/projects/${projectId}/subtitles/srt`, undefined, { timeout: 0 }))
}
