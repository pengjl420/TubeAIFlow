import { apiClient, unwrap } from './client'

export interface SystemSettings {
  app_host: string
  app_port: number
  workspace_dir: string
  ffmpeg_path: string
  ffprobe_path: string
  deepseek_api_key: string
  deepseek_api_key_configured: boolean
  deepseek_base_url: string
  deepseek_model: string
  translation_timeout_seconds: number
  translation_batch_size: number
  translation_max_tokens: number
  translation_retry_count: number
  index_tts_root: string | null
  index_tts_python: string | null
  index_tts_model_dir: string | null
  index_tts_fp16: boolean
}

export async function getSystemSettings(): Promise<SystemSettings> {
  return unwrap<SystemSettings>(await apiClient.get('/settings'))
}

export async function saveSystemSettings(settings: SystemSettings): Promise<SystemSettings> {
  return unwrap<SystemSettings>(await apiClient.put('/settings', settings))
}

export async function clearSystemSecret(field: string): Promise<SystemSettings> {
  return unwrap<SystemSettings>(await apiClient.post('/settings/clear-secret', { field }))
}
