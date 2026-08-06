import { API_BASE_URL, apiClient, unwrap } from './client'

export interface AvatarProfile {
  id: string
  name: string
  template_video_path: string
  duration_ms: number | null
  width: number | null
  height: number | null
  enabled: boolean
  created_at: string
}

export interface AvatarClip {
  id: string
  clip_index: number
  start_ms: number
  end_ms: number
  status: string
  progress: number
  error_message: string | null
}

export interface AvatarTask {
  id: string
  avatar_profile_id: string
  output_filename: string
  chunk_seconds: number
  context_ms: number
  audio_duration_ms: number
  status: string
  queue_position: number | null
  total_chunks: number
  completed_chunks: number
  current_chunk: number | null
  progress: number
  result_path: string | null
  error_message: string | null
  created_at: string
  clips: AvatarClip[]
  continuity_report: { seam_count: number; warning_count: number } | null
}

export async function healthCheckDuix() {
  return unwrap<{ available: boolean; service_code?: number; message?: string; error?: string }>(
    await apiClient.get('/avatars/duix/health-check'),
  )
}

export async function listAvatarProfiles() {
  return unwrap<AvatarProfile[]>(await apiClient.get('/avatars'))
}

export async function createAvatarProfile(name: string, templateVideo: File) {
  const form = new FormData()
  form.append('name', name)
  form.append('template_video', templateVideo)
  return unwrap<AvatarProfile>(await apiClient.post('/avatars', form, { timeout: 0 }))
}

export async function createAvatarTask(
  avatarProfileId: string,
  audio: File,
  outputFilename: string,
  chunkSeconds: number,
  contextMs: number,
) {
  const form = new FormData()
  form.append('avatar_profile_id', avatarProfileId)
  form.append('audio', audio)
  form.append('output_filename', outputFilename)
  form.append('chunk_seconds', String(chunkSeconds))
  form.append('context_ms', String(contextMs))
  return unwrap<AvatarTask>(await apiClient.post('/avatars/tasks', form, { timeout: 0 }))
}

export async function listAvatarTasks() {
  return unwrap<AvatarTask[]>(await apiClient.get('/avatars/tasks/list'))
}

export async function retryAvatarTask(taskId: string) {
  return unwrap<AvatarTask>(await apiClient.post(`/avatars/tasks/${taskId}/retry`))
}

export function avatarVideoUrl(profileId: string) {
  return `${API_BASE_URL}/avatars/${profileId}/video`
}

export function avatarOutputUrl(taskId: string, download = false) {
  return `${API_BASE_URL}/avatars/tasks/${taskId}/output${download ? '?download=true' : ''}`
}
