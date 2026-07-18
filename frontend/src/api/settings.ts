import { apiClient, unwrap } from './client'

export type LandscapeTransitionName = 'fade' | 'dissolve' | 'fadeblack' | 'smoothleft' | 'smoothright'

export interface LandscapeTransitionEffect {
  name: LandscapeTransitionName
  enabled: boolean
  percentage: number
}

export interface SystemSettings {
  app_host: string
  app_port: number
  workspace_dir: string
  ffmpeg_path: string
  ffprobe_path: string
  landscape_transition_effects: LandscapeTransitionEffect[]
  deepseek_api_key: string
  deepseek_api_key_configured: boolean
  deepseek_base_url: string
  deepseek_model: string
  deepseek_timeout_seconds: number
  deepseek_max_tokens: number
  deepseek_retry_count: number
  pexels_api_key: string
  pexels_api_key_configured: boolean
  pixabay_api_key: string
  pixabay_api_key_configured: boolean
  media_search_cache_hours: number
  media_search_download_limit: number
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
  cosyvoice_instruction: string
}

export interface FfmpegStatus {
  installed: boolean
  ffmpeg_path: string | null
  ffprobe_path: string | null
  version: string | null
  platform_supported: boolean
}

export interface FfmpegInstallResult {
  settings: SystemSettings
  status: FfmpegStatus
}

export interface MediaProviderStatus {
  provider: 'pexels' | 'pixabay'
  configured: boolean
  status: 'unconfigured' | 'available' | 'cooldown' | 'error'
  rate_limit: number | null
  remaining: number | null
  reset_at: string | null
  last_error: string | null
  updated_at: string | null
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

export async function getMediaProviderStatuses(): Promise<MediaProviderStatus[]> {
  const result = unwrap<{ providers: MediaProviderStatus[] }>(await apiClient.get('/settings/media-providers/status'))
  return result.providers
}

export async function getFfmpegStatus(): Promise<FfmpegStatus> {
  return unwrap<FfmpegStatus>(await apiClient.get('/settings/ffmpeg/status'))
}

export async function installFfmpeg(): Promise<FfmpegInstallResult> {
  return unwrap<FfmpegInstallResult>(await apiClient.post('/settings/ffmpeg/install', undefined, {
    timeout: 10 * 60 * 1000,
  }))
}
