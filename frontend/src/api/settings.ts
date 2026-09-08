import { apiClient, unwrap } from './client'

export async function selectDirectory(initialPath: string, title: string): Promise<string | null> {
  const result = unwrap<{ path: string | null }>(await apiClient.post(
    '/tools/select-directory',
    { initial_path: initialPath || null, title },
    { timeout: 0 },
  ))
  return result.path
}

export type StoryboardTransitionName = 'fade' | 'dissolve' | 'fadeblack' | 'smoothleft' | 'smoothright'

export interface StoryboardTransitionEffect {
  name: StoryboardTransitionName
  enabled: boolean
  percentage: number
}

export interface SystemSettings {
  subtitle_max_display_units: number
  subtitle_min_cue_duration_ms: number
  subtitle_max_cue_duration_ms: number
  subtitle_target_characters_per_second: number
  subtitle_alignment_enabled: boolean
  subtitle_whisper_model_path: string | null
  subtitle_whisper_device: string
  subtitle_whisper_compute_type: 'float16' | 'int8_float16' | 'int8' | 'float32'
  subtitle_whisper_beam_size: number
  app_host: string
  app_port: number
  workspace_dir: string
  cleanup_enabled: boolean
  cleanup_retention_days: number
  cleanup_daily_time: string
  cleanup_completed_voice_tasks: boolean
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
  storyboard_llm_strategy: 'local' | 'hybrid' | 'cloud'
  local_llm_base_url: string
  local_llm_model: string
  local_llm_models_dir: string
  local_llm_timeout_seconds: number
  local_llm_max_tokens: number
  storyboard_cloud_confidence_threshold: number
  storyboard_cloud_identity_risk_threshold: number
  storyboard_llm_cache_enabled: boolean
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
  index_tts_root: string | null
  index_tts_python: string | null
  index_tts_model_dir: string | null
  index_tts_device: string
  index_tts_max_text_tokens_per_sentence: number
  moss_tts_root: string | null
  moss_tts_python: string | null
  moss_tts_model_dir: string | null
  moss_tts_codec_dir: string | null
  moss_tts_device: string
  moss_tts_dtype: 'bfloat16' | 'float16' | 'float32'
  moss_tts_max_new_tokens: number
}

export interface ModelDownloadJob {
  id: string
  model_id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'interrupted'
  progress: number
  downloaded_bytes: number
  total_bytes: number
  path: string | null
  message: string
  error: string | null
}

export interface LocalLLMModel {
  id: string
  display_name: string
  description: string
  repo_id: string
  filename: string
  size_bytes: number
  min_ram_gb: number
  recommended_vram_gb: number
  quality: 'fast' | 'balanced' | 'quality'
  recommended: boolean
  license: string
  installed: boolean
  path: string | null
  download: ModelDownloadJob | null
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

export interface PremiereStatus {
  installed: boolean
  path: string | null
  configured_path: string | null
}

export async function getSystemSettings(): Promise<SystemSettings> {
  return unwrap<SystemSettings>(await apiClient.get('/settings'))
}

export async function saveSystemSettings(settings: SystemSettings): Promise<SystemSettings> {
  const result = unwrap<SystemSettings>(await apiClient.put('/settings', settings))
  if (typeof result.cleanup_enabled !== 'boolean') {
    throw new Error('当前后端不支持自动清理，清理设置未保存。请重启 TubeAiFolw 后重新设置。')
  }
  return result
}

export async function listLocalLLMModels(): Promise<LocalLLMModel[]> {
  return unwrap<LocalLLMModel[]>(await apiClient.get('/models/llm'))
}

export async function downloadLocalLLMModel(modelId: string): Promise<ModelDownloadJob> {
  return unwrap<ModelDownloadJob>(await apiClient.post(`/models/llm/${encodeURIComponent(modelId)}/download`))
}

export interface CleanupStatus {
  enabled: boolean
  retention_days: number
  daily_time: string
  completed_voice_tasks: boolean
  worker_alive: boolean
  catchup_pending: boolean
  next_run_at: string | null
  last_run: { finished_at: string; deleted_tasks: number; deleted_logs: number; errors: number } | null
  error: string | null
}

export async function getCleanupStatus(): Promise<CleanupStatus> {
  return unwrap<CleanupStatus>(await apiClient.get('/settings/cleanup/status'))
}

export async function clearSystemSecret(field: string): Promise<SystemSettings> {
  return unwrap<SystemSettings>(await apiClient.post('/settings/clear-secret', { field }))
}

export async function getFfmpegStatus(): Promise<FfmpegStatus> {
  return unwrap<FfmpegStatus>(await apiClient.get('/settings/ffmpeg/status'))
}

export async function getPremiereStatus(): Promise<PremiereStatus> {
  return unwrap<PremiereStatus>(await apiClient.get('/settings/premiere/status'))
}

export async function installFfmpeg(): Promise<FfmpegInstallResult> {
  return unwrap<FfmpegInstallResult>(await apiClient.post('/settings/ffmpeg/install', undefined, {
    timeout: 10 * 60 * 1000,
  }))
}
