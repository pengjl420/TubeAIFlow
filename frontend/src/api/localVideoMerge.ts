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

export type LocalVideoMergeTaskStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface LocalVideoMergeTask {
  id: string
  media_dir: string
  output_dir: string
  output_filename: string
  target_duration: number
  status: LocalVideoMergeTaskStatus
  queue_sequence: number
  queue_position: number | null
  attempt_count: number
  error_message: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  duration_seconds: number | null
  result: LocalVideoMergeResult | null
}

export async function createLocalVideoMergeTask(input: LocalVideoMergeInput) {
  return unwrap<LocalVideoMergeTask>(
    await apiClient.post('/tools/local-video-merge/tasks', input),
  )
}

export async function listLocalVideoMergeTasks(limit = 100) {
  return unwrap<LocalVideoMergeTask[]>(
    await apiClient.get('/tools/local-video-merge/tasks', { params: { limit } }),
  )
}

export async function composeLocalVideo(input: LocalVideoMergeInput) {
  return unwrap<LocalVideoMergeResult>(
    await apiClient.post('/tools/local-video-merge/compose', input, { timeout: 0 }),
  )
}
