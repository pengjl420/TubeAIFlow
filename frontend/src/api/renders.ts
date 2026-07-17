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
  status: 'running' | 'completed' | 'failed' | 'cancelled'
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

export interface QaIssue {
  type: string
  severity: 'error' | 'warning'
  scene_id?: string | null
  subtitle_id?: string | null
  message: string
  suggestion?: string | null
}

export interface QaReport {
  passed: boolean
  summary: {
    scene_count: number
    assignment_count: number
    subtitle_count: number
    error_count: number
    warning_count: number
    audio_duration_seconds?: number | null
    video_duration_seconds?: number | null
  }
  issues: QaIssue[]
}

export interface IntelligentRenderStatus {
  scene_count: number
  assignment_count: number
  rendered_scene_count: number
  final_video_path: string
  final_video_exists: boolean
  qa_report?: QaReport | null
  work_dir: string
}

export async function getIntelligentRenderStatus(projectId: string) {
  return unwrap<IntelligentRenderStatus>(
    await apiClient.get(`/projects/${projectId}/render/status`),
  )
}
