import { apiClient, unwrap } from './client'

export interface LocalVideoMergeInput {
  media_dir: string
  output_dir: string
  output_filename: string
  target_duration: number
}

export interface LocalVideoMergeResult {
  output_path: string
  manifest_path: string
  requested_duration: number
  actual_duration: number
  scanned_file_count: number
  unique_filename_count: number
  selected_file_count: number
  transition_count: number
  selected_files: string[]
}

export async function composeLocalVideo(input: LocalVideoMergeInput) {
  return unwrap<LocalVideoMergeResult>(
    await apiClient.post('/tools/local-video-merge/compose', input, { timeout: 0 }),
  )
}
