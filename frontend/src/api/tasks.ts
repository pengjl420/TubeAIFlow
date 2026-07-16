import { apiClient, unwrap } from './client'

export interface ProjectTaskStatus {
  running: boolean
  stage: string | null
  cancelled: boolean
}

export async function cancelProjectTask(projectId: string) {
  return unwrap<{ cancelled: boolean; stage: string | null }>(
    await apiClient.post(`/projects/${projectId}/tasks/cancel`),
  )
}

export async function getProjectTaskStatus(projectId: string) {
  return unwrap<ProjectTaskStatus>(await apiClient.get(`/projects/${projectId}/tasks/status`))
}
