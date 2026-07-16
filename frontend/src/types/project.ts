export interface Project {
  id: string
  name: string
  status: string
  output_dir?: string
  reference_audio_path?: string
  config?: {
    reference_audio_filename?: string
    voice_profile_name?: string
    tts_engine?: string
    [key: string]: unknown
  }
  config_json?: string
  created_at: string
  updated_at: string
}
