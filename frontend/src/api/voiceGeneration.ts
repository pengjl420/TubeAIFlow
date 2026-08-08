import { API_BASE_URL, apiClient, unwrap } from './client'

export type VoiceGenerationStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface VoiceGenerationTask {
  id: string
  voice_profile_id: string
  voice_profile_name: string
  tts_engine: import('./voices').VoiceTtsEngine
  language: import('./voices').VoiceLanguage
  text: string
  output_filename: string
  output_path: string | null
  duration: number | null
  status: VoiceGenerationStatus
  queue_sequence: number
  queue_position: number | null
  attempt_count: number
  error_message: string | null
  audio_url: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  duration_seconds: number | null
  segment_count: number
  segments: VoiceGenerationSegment[]
}

export interface VoiceGenerationSegment {
  index: number
  text: string
  filename: string
  duration: number | null
  audio_url: string | null
}

export interface VoiceGenerationInput {
  voice_profile_id: string
  text: string
  output_filename: string
}

export async function createVoiceGenerationTask(input: VoiceGenerationInput) {
  return unwrap<VoiceGenerationTask>(await apiClient.post('/tools/voice-generation/tasks', input))
}

export async function listVoiceGenerationTasks(limit = 100) {
  return unwrap<VoiceGenerationTask[]>(
    await apiClient.get('/tools/voice-generation/tasks', { params: { limit } }),
  )
}

export function voiceGenerationAudioUrl(task: VoiceGenerationTask, download = false) {
  if (!task.audio_url) return ''

  const url = new URL(task.audio_url, `${API_BASE_URL}/`)
  if (download) url.searchParams.set('download', 'true')
  return url.toString()
}

export function voiceGenerationSegmentAudioUrl(segment: VoiceGenerationSegment, download = false) {
  if (!segment.audio_url) return ''
  const url = new URL(segment.audio_url, `${API_BASE_URL}/`)
  if (download) url.searchParams.set('download', 'true')
  return url.toString()
}
