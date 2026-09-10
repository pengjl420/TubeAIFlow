import { apiClient, unwrap } from './client'
import type { VideoGenerationMode } from '../types/project'

export interface BatchItem {
  id: string
  project_id: string
  project_name: string
  original_filename: string
  status: string
  current_stage: string
  error_message?: string | null
}

export interface BatchJob {
  id: string
  name: string
  status: string
  total: number
  completed: number
  failed: number
  created_at: string
  items?: BatchItem[]
}

export interface CreateBatchInput {
  name: string
  scripts: File[]
  outputDir: string
  mediaVideoDir: string
  videoMode: VideoGenerationMode
  voiceProfileId: string
  segmentationMode: 'newline' | 'ai'
  storyboardMode: 'ai' | 'segments'
  continueOnError: boolean
}

export async function listBatches(): Promise<BatchJob[]> {
  return unwrap<BatchJob[]>(await apiClient.get('/batches'))
}

export async function getBatch(id: string): Promise<BatchJob> {
  return unwrap<BatchJob>(await apiClient.get(`/batches/${id}`))
}

export async function createBatch(input: CreateBatchInput): Promise<BatchJob> {
  const form = new FormData()
  input.scripts.forEach(file => form.append('scripts', file))
  form.append('name', input.name)
  form.append('output_dir', input.outputDir)
  form.append('media_video_dir', input.mediaVideoDir)
  form.append('include_video', String(input.videoMode !== 'none'))
  form.append('video_mode', input.videoMode)
  form.append('voice_profile_id', input.voiceProfileId)
  form.append('segmentation_mode', input.segmentationMode)
  form.append('storyboard_mode', input.storyboardMode)
  form.append('continue_on_error', String(input.continueOnError))
  form.append('auto_start', 'true')
  return unwrap<BatchJob>(await apiClient.post('/batches', form))
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
