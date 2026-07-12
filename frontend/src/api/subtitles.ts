import { apiClient, unwrap } from './client'

export async function createTimeline(projectId: string) {
  return unwrap(await apiClient.post(`/projects/${projectId}/timeline`))
}

export async function createZhSrt(projectId: string) {
  return unwrap<{
    zh_path: string
    en_path: string
    translation_path: string
    segments: number
  }>(await apiClient.post(`/projects/${projectId}/subtitles/zh`, undefined, { timeout: 0 }))
}

export async function createEnSrt(projectId: string) {
  return unwrap<{ path: string; translation_path: string }>(
    await apiClient.post(`/projects/${projectId}/subtitles/en`, undefined, { timeout: 0 }),
  )
}
