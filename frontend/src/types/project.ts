export interface Project {
  id: string
  name: string
  status: string
  output_dir?: string
  reference_audio_path?: string
  config_json?: string
  created_at: string
  updated_at: string
}
