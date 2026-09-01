import { apiClient, unwrap } from './client'
import type { Project } from '../types/project'

export interface CreateProjectInput {
  name: string
  outputDir: string
  voiceProfileId: string
  ttsEngine: string
}

export interface ProjectTask {
  id: string | null
  status: string
  stage: string | null
  running: boolean
  queued: boolean
  cancelled: boolean
  queue_position: number | null
  error_message?: string | null
}

export interface ProjectOutput {
  name: string
  path: string
  relative_path: string
  size: number
  modified_at: number
}

export interface ProjectOutputs {
  output_dir: string
  work_dir: string
  final_audio_exists: boolean
  final_srt_exists: boolean
  final_video_exists: boolean
  files: ProjectOutput[]
}

export async function listProjects(): Promise<Project[]> {
  return unwrap<Project[]>(await apiClient.get('/projects'))
}

export async function getProject(projectId: string): Promise<Project> {
  return unwrap<Project>(await apiClient.get(`/projects/${projectId}`))
}

export async function createProject(input: CreateProjectInput): Promise<Project> {
  const form = new FormData()
  form.append('name', input.name)
  form.append('output_dir', input.outputDir)
  form.append('voice_profile_id', input.voiceProfileId)
  form.append('tts_engine', input.ttsEngine)
  form.append('include_video', 'false')
  form.append('segmentation_mode', 'ai')
  return unwrap<Project>(await apiClient.post('/projects', form))
}

export async function saveProjectScript(projectId: string, text: string): Promise<Project> {
  return unwrap<Project>(await apiClient.post(`/projects/${projectId}/script`, { text }))
}

export async function getProjectScript(projectId: string): Promise<{ text: string; clean_text: string }> {
  return unwrap<{ text: string; clean_text: string }>(
    await apiClient.get(`/projects/${projectId}/script`),
  )
}

export async function startProjectWorkflow(projectId: string): Promise<ProjectTask> {
  return unwrap<ProjectTask>(
    await apiClient.post(`/projects/${projectId}/workflows/narration/start`),
  )
}

export async function getProjectTask(projectId: string): Promise<ProjectTask> {
  return unwrap<ProjectTask>(await apiClient.get(`/projects/${projectId}/tasks/status`))
}

export async function cancelProjectTask(projectId: string): Promise<void> {
  await apiClient.post(`/projects/${projectId}/tasks/cancel`)
}

export async function getProjectOutputs(projectId: string): Promise<ProjectOutputs> {
  return unwrap<ProjectOutputs>(await apiClient.get(`/projects/${projectId}/outputs`))
}

export function projectOutputUrl(projectId: string, path: string, download = false): string {
  const query = new URLSearchParams({ path, download: String(download) })
  return `${apiClient.defaults.baseURL}/projects/${projectId}/outputs/file?${query}`
}
