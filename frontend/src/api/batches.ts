import { apiClient, unwrap } from './client'

export interface BatchItem {
  id: string
  batch_id: string
  project_id: string
  project_name: string
  project_status: string
  order_index: number
  original_filename: string
  status: string
  current_stage: string
  error_message?: string | null
  started_at?: string | null
  finished_at?: string | null
  audio_duration_seconds?: number
  workflow_started_at?: string | null
  workflow_finished_at?: string | null
  workflow_duration_seconds?: number | null
}

export interface BatchJob {
  id: string
  name: string
  status: string
  total: number
  completed: number
  failed: number
  config_json: string
  created_at: string
  updated_at: string
  started_at?: string | null
  finished_at?: string | null
  workflow_duration_seconds?: number | null
  items?: BatchItem[]
}

export interface CreateBatchInput {
  name: string
  scripts: File[]
  voiceProfileId: string
  outputDir: string
  mediaVideoDir: string
  includeVideo: boolean
  continueOnError: boolean
}

export async function listBatches(): Promise<BatchJob[]> {
  return unwrap<BatchJob[]>(await apiClient.get('/batches'))
}

export async function getBatch(id: string): Promise<BatchJob> {
  return unwrap<BatchJob>(await apiClient.get(`/batches/${id}`))
}

export async function deleteBatch(id: string): Promise<{
  batch_id: string
  project_ids: string[]
  projects_preserved: boolean
}> {
  return unwrap(await apiClient.delete(`/batches/${id}`))
}

export async function createBatch(input: CreateBatchInput): Promise<BatchJob> {
  const form = new FormData()
  form.append('name', input.name)
  for (const script of input.scripts) form.append('scripts', script)
  form.append('voice_profile_id', input.voiceProfileId)
  form.append('output_dir', input.outputDir)
  form.append('media_video_dir', input.mediaVideoDir)
  form.append('include_video', String(input.includeVideo))
  form.append('continue_on_error', String(input.continueOnError))
  form.append('auto_start', 'true')
  return unwrap<BatchJob>(await apiClient.post('/batches', form, { timeout: 0 }))
}

export async function startBatch(id: string): Promise<BatchJob> {
  return unwrap<BatchJob>(await apiClient.post(`/batches/${id}/start`))
}

export async function pauseBatch(id: string): Promise<BatchJob> {
  return unwrap<BatchJob>(await apiClient.post(`/batches/${id}/pause`))
}

export async function retryBatchItem(batchId: string, itemId: string): Promise<BatchItem> {
  return unwrap<BatchItem>(await apiClient.post(`/batches/${batchId}/items/${itemId}/retry`))
}
