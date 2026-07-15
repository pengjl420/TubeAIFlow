import { apiClient, unwrap } from './client'

export async function createTimeline(projectId: string) {
  return unwrap(await apiClient.post(`/projects/${projectId}/timeline`))
}

export async function createZhSrt(projectId: string, includeTranslation = true) {
  return unwrap<{
    zh_path: string
    en_path: string | null
    translated_path: string | null
    target_language: 'en' | 'zh' | null
    translation_path: string | null
    segments: number
  }>(await apiClient.post(
    `/projects/${projectId}/subtitles/zh`,
    undefined,
    { params: { include_translation: includeTranslation }, timeout: 0 },
  ))
}

export async function createEnSrt(projectId: string) {
  return unwrap<{ path: string; translation_path: string }>(
    await apiClient.post(`/projects/${projectId}/subtitles/en`, undefined, { timeout: 0 }),
  )
}
