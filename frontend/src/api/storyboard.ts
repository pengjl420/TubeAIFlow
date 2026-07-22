import { apiClient, unwrap } from './client'
import type {
  SrtImportResult,
  SubtitleCue,
  VisualScene,
} from '../types/storyboard'

export async function importProjectSrt(projectId: string, content: string): Promise<SrtImportResult> {
  return unwrap(await apiClient.post(`/projects/${projectId}/subtitles/import`, { content }))
}

export async function listSubtitleCues(projectId: string): Promise<SubtitleCue[]> {
  return unwrap(await apiClient.get(`/projects/${projectId}/subtitles/cues`))
}

export async function getStoryboard(projectId: string): Promise<VisualScene[]> {
  const result = unwrap<{ scenes: VisualScene[] }>(
    await apiClient.get(`/projects/${projectId}/storyboard`),
  )
  return result.scenes
}
