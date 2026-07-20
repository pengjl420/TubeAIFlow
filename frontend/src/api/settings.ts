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
  pexels_storage_dir: string | null
  pixabay_storage_dir: string | null
  media_search_cache_hours: number
  media_search_download_limit: number
  auto_fallback_enabled: boolean
  auto_landscape_fallback_enabled: boolean
  auto_fallback_review_required: boolean
  auto_fallback_max_ratio_percent: number
  auto_fallback_max_consecutive_shots: number
  image_generation_model_path: string | null
  image_generation_config_dir: string | null
  image_generation_python: string | null
  image_generation_device: string
  image_generation_dtype: 'bfloat16' | 'float16' | 'float32'
  image_generation_width: number
  image_generation_height: number
  image_generation_steps: number
  image_generation_guidance_scale: number
  image_generation_candidates_per_scene: number
  image_generation_cpu_offload: boolean
  image_generation_negative_prompt: string
  framepack_enabled: boolean
  framepack_auto_start_worker: boolean
  framepack_python: string | null
  framepack_cache_dir: string | null
  framepack_worker_host: string
  framepack_worker_port: number
  framepack_model_id: string
  framepack_base_model_id: string
  framepack_sampling_type: string
  framepack_allow_model_download: boolean
  framepack_width: number
  framepack_height: number
  framepack_steps: number
  framepack_guidance_scale: number
  framepack_cpu_offload: boolean
  framepack_max_ratio: number
  framepack_max_retries: number
  framepack_startup_timeout_seconds: number
  framepack_job_timeout_seconds: number
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

export interface FramePackStatus {
  enabled: boolean
  configured: boolean
  worker: { managed: boolean; running: boolean; pid: number | null }
  health: {
    status: 'starting' | 'loading_model' | 'ready' | 'busy' | 'unavailable' | 'error'
    model_loaded: boolean
    gpu?: string | null
    free_vram_gb?: number | null
    current_job_id?: string | null
    error?: string | null
  } | null
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

export async function getFramePackStatus(): Promise<FramePackStatus> {
  return unwrap<FramePackStatus>(await apiClient.get('/settings/framepack/status'))
}

export async function installFfmpeg(): Promise<FfmpegInstallResult> {
  return unwrap<FfmpegInstallResult>(await apiClient.post('/settings/ffmpeg/install', undefined, {
    timeout: 10 * 60 * 1000,
  }))
}
