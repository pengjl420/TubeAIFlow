import { apiClient, unwrap } from './client'

export async function createTimeline(projectId: string) {
  return unwrap(await apiClient.post(`/projects/${projectId}/timeline`))
}

export async function createZhAss(projectId: string) {
  return unwrap(await apiClient.post(`/projects/${projectId}/subtitles/zh`))
}

export async function createEnAss(projectId: string) {
  return unwrap(await apiClient.post(`/projects/${projectId}/subtitles/en`))
}
