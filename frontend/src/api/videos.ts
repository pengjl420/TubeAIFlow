import { apiClient, unwrap } from './client'
import type { Project } from '../types/project'

export async function saveVideoSettings(projectId: string, mediaVideoDir: string): Promise<Project> {
  return unwrap<Project>(await apiClient.post(`/projects/${projectId}/video/settings`, {
    media_video_dir: mediaVideoDir,
  }))
}

export async function composeProjectVideo(projectId: string): Promise<{ path: string }> {
  return unwrap<{ path: string }>(await apiClient.post(`/projects/${projectId}/video/compose`, undefined, { timeout: 0 }))
}
