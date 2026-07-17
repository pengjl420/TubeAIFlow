import { apiClient, unwrap } from './client'
import type {
  SrtImportResult,
  LabSubtitleCue,
  StoryboardContent,
  StoryboardGenerateResult,
  SubtitleCue,
  VisualScene,
} from '../types/storyboard'

export async function parseStoryboardLabSrt(content: string): Promise<LabSubtitleCue[]> {
  const result = unwrap<{ cues: LabSubtitleCue[] }>(
    await apiClient.post('/storyboard-lab/parse', { content }),
  )
  return result.cues
}

export async function generateStoryboardLab(content: string): Promise<StoryboardGenerateResult & { cues: LabSubtitleCue[] }> {
  return unwrap(await apiClient.post(
    '/storyboard-lab/generate',
    { content },
    { timeout: 300_000 },
  ))
}

export async function importProjectSrt(projectId: string, content: string): Promise<SrtImportResult> {
  return unwrap(await apiClient.post(`/projects/${projectId}/subtitles/import`, { content }))
}

export async function listSubtitleCues(projectId: string): Promise<SubtitleCue[]> {
  return unwrap(await apiClient.get(`/projects/${projectId}/subtitles/cues`))
}

export async function generateStoryboard(projectId: string): Promise<StoryboardGenerateResult> {
  return unwrap(await apiClient.post(
    `/projects/${projectId}/storyboard/generate`,
    undefined,
    { timeout: 300_000 },
  ))
}

export async function getStoryboard(projectId: string): Promise<VisualScene[]> {
  const result = unwrap<{ scenes: VisualScene[] }>(
    await apiClient.get(`/projects/${projectId}/storyboard`),
  )
  return result.scenes
}

export async function updateStoryboardScene(
  projectId: string,
  sceneId: string,
  storyboard: StoryboardContent,
): Promise<VisualScene> {
  return unwrap(await apiClient.put(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}`,
    { storyboard },
  ))
}
