import { apiClient, unwrap } from './client'

export type StoryboardTransitionName = 'fade' | 'dissolve' | 'fadeblack' | 'smoothleft' | 'smoothright'

export interface StoryboardTransitionEffect {
  name: StoryboardTransitionName
  enabled: boolean
  percentage: number
}

export interface SystemSettings {
  app_host: string
  app_port: number
  workspace_dir: string
  ffmpeg_path: string
  ffprobe_path: string
  premiere_pro_path: string | null
  storyboard_transition_effects: StoryboardTransitionEffect[]
  storyboard_transition_group_min_clips: number
  storyboard_transition_group_max_clips: number
  storyboard_transition_min_per_group: number
  storyboard_transition_max_per_group: number
  storyboard_transition_duration_seconds: number
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
  image_selection_semantic_weight: number
  image_selection_technical_weight: number
  image_selection_min_semantic_score: number
  image_selection_min_total_score: number
  image_selection_min_score_margin: number
  image_selection_min_sharpness: number
  image_selection_max_clipped_ratio: number
  vision_embedding_model_dir: string | null
  vision_embedding_device: string
  vision_embedding_dtype: 'bfloat16' | 'float16' | 'float32'
  vision_embedding_max_images: number
  vision_embedding_max_pixels: number
  vision_embedding_instruction: string
  qwen_tts_root: string | null
  qwen_tts_python: string | null
  qwen_tts_model_dir: string | null
  qwen_tts_device: string
  qwen_tts_dtype: 'bfloat16' | 'float16' | 'float32'
  qwen_tts_language: string
  qwen_tts_max_new_tokens: number
  cosyvoice_root: string | null
  cosyvoice_python: string | null
  cosyvoice_model_dir: string | null
  cosyvoice_fp16: boolean
  cosyvoice_instruction: string
  cosyvoice_max_attempts: number
  cosyvoice_min_chars_per_second: number
  cosyvoice_duration_slack_seconds: number
  cosyvoice_duration_outlier_ratio: number
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
