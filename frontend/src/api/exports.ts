import { apiClient, unwrap } from './client'

export async function exportProject(projectId: string) {
  return unwrap(await apiClient.post(`/projects/${projectId}/export`))
}

export async function exportProjectFcpxml(projectId: string) {
  return unwrap(await apiClient.post(`/projects/${projectId}/exports/fcpxml`, undefined, { timeout: 0 }))
}

export async function exportProjectPrproj(projectId: string) {
  return unwrap(await apiClient.post(`/projects/${projectId}/exports/prproj`, undefined, { timeout: 0 }))
}

export async function mergeProjectAudio(projectId: string): Promise<{ path: string }> {
  return unwrap<{ path: string }>(await apiClient.post(`/projects/${projectId}/audio/merge`, undefined, { timeout: 0 }))
}
