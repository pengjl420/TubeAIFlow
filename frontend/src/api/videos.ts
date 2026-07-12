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

export interface VideoProgress {
  status: 'running' | 'completed' | 'failed'
  stage: string
  percent: number
  total: number
  completed: number
  current_file?: string
  message?: string
  error?: string
}

export async function getVideoStatus(projectId: string): Promise<VideoProgress | null> {
  return unwrap<VideoProgress | null>(await apiClient.get(`/projects/${projectId}/video/status`))
}
