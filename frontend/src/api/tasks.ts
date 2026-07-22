import { apiClient, unwrap } from './client'

export interface ProjectTaskStatus {
  id: string | null
  project_id?: string
  batch_id?: string | null
  status: 'idle' | 'queued' | 'running' | 'paused' | 'review_required' | 'completed' | 'failed' | 'cancelled'
  running: boolean
  queued: boolean
  stage: string | null
  cancelled: boolean
  queue_position: number | null
  error_message?: string | null
  created_at?: string
  started_at?: string | null
  finished_at?: string | null
  workflow_duration_seconds?: number | null
  compensation_count?: number
  workflow?: 'narration_generation' | 'video_synthesis'
  attempt_count?: number
  lease_owner?: string | null
  checkpoint_json?: string
  updated_at?: string
}

export async function listTasks() {
  return unwrap<ProjectTaskStatus[]>(await apiClient.get('/tasks'))
}

export async function cancelProjectTask(projectId: string) {
  return unwrap<{ cancelled: boolean; stage: string | null }>(
    await apiClient.post(`/projects/${projectId}/tasks/cancel`),
  )
}

export async function getProjectTaskStatus(projectId: string) {
  return unwrap<ProjectTaskStatus>(await apiClient.get(`/projects/${projectId}/tasks/status`))
}

export async function startProjectWorkflow(projectId: string) {
  return unwrap<ProjectTaskStatus>(
    await apiClient.post(`/projects/${projectId}/workflows/narration/start`),
  )
}

export async function continueProjectWorkflow(projectId: string) {
  return unwrap<ProjectTaskStatus>(
    await apiClient.post(`/projects/${projectId}/workflows/continue`),
  )
}

export async function startVideoWorkflow(projectId: string) {
  return unwrap<ProjectTaskStatus>(
    await apiClient.post(`/projects/${projectId}/workflows/video/start`),
  )
}

export async function getVideoWorkflowStatus(projectId: string) {
  return unwrap<ProjectTaskStatus>(
    await apiClient.get(`/projects/${projectId}/workflows/video/status`),
  )
}
