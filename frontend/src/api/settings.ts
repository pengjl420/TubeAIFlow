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
  qwen_tts_root: string | null
  qwen_tts_python: string | null
  qwen_tts_model_dir: string | null
  qwen_tts_device: string
  qwen_tts_dtype: 'bfloat16' | 'float16' | 'float32'
  qwen_tts_language: string
  qwen_tts_max_new_tokens: number
  chatterbox_root: string | null
  chatterbox_python: string | null
  chatterbox_model_dir: string | null
  chatterbox_device: string
  chatterbox_language: string
  chatterbox_t3_model: 'v2' | 'v3'
  chatterbox_exaggeration: number
  chatterbox_cfg_weight: number
  chatterbox_temperature: number
  cosyvoice_root: string | null
  cosyvoice_python: string | null
  cosyvoice_model_dir: string | null
  cosyvoice_fp16: boolean
  cosyvoice_speed: number
  cosyvoice_instruction: string
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
