import { apiClient, unwrap } from './client'
import type { Project, SemanticReviewMode, VideoGenerationMode } from '../types/project'

export interface CreateProjectInput {
  name: string
  voice_profile_id: string
  output_dir: string
  output_filename: string
  media_video_dir: string
  include_video: boolean
  video_mode: VideoGenerationMode
  semantic_review_mode: SemanticReviewMode
}

export async function listProjects(): Promise<Project[]> {
  return unwrap<Project[]>(await apiClient.get('/projects'))
}

export async function createProject(input: CreateProjectInput): Promise<Project> {
  const form = new FormData()
  form.append('name', input.name)
  form.append('voice_profile_id', input.voice_profile_id)
  form.append('output_dir', input.output_dir)
  form.append('output_filename', input.output_filename)
  form.append('media_video_dir', input.media_video_dir)
  form.append('include_video', String(input.include_video))
  form.append('video_mode', input.video_mode)
  form.append('semantic_review_mode', input.semantic_review_mode)
  return unwrap<Project>(await apiClient.post('/projects', form))
}

export async function getProject(id: string): Promise<Project> {
  return unwrap<Project>(await apiClient.get(`/projects/${id}`))
}

export async function deleteProject(id: string): Promise<{ project_id: string; recycled_paths: string[] }> {
  return unwrap(await apiClient.delete(`/projects/${id}`))
}

export interface ProjectOutputFile {
  name: string
  path: string
  relative_path: string
  size: number
  modified_at: number
}

export interface ProjectOutputs {
  output_dir: string
  work_dir?: string
  final_audio_path?: string
  final_srt_path?: string
  final_video_path?: string
  files: ProjectOutputFile[]
}

export async function getProjectOutputs(id: string): Promise<ProjectOutputs> {
  return unwrap<ProjectOutputs>(await apiClient.get(`/projects/${id}/outputs`))
}

export async function selectDirectory(initialPath: string, title: string): Promise<string | null> {
  try {
    const result = unwrap<{ path: string | null }>(await apiClient.post(
      '/projects/select-directory',
      { initial_path: initialPath || null, title },
      { timeout: 0 },
    ))
    return result.path
  } catch (error) {
    if (error instanceof Error && error.message === 'Method Not Allowed') {
      throw new Error('后端仍在运行旧版本，请重启 TubeAIFlow 后再选择文件夹')
    }
    throw error
  }
}

export async function saveScript(id: string, text: string): Promise<Project> {
  return unwrap<Project>(await apiClient.post(`/projects/${id}/script`, { text }))
}

export async function createSegments(id: string) {
  return unwrap(await apiClient.post(`/projects/${id}/segments`))
}

export async function saveOutputSettings(
  id: string,
  outputDir: string,
  outputFilename: string,
): Promise<Project> {
  return unwrap<Project>(await apiClient.post(`/projects/${id}/output-settings`, {
    output_dir: outputDir,
    output_filename: outputFilename,
  }))
}

export interface ProjectSettingsInput {
  name: string
  output_dir: string
  output_filename: string
  media_video_dir: string
  include_video: boolean
  video_mode: VideoGenerationMode
  semantic_review_mode: SemanticReviewMode
  voice_profile_id: string
}

export async function saveProjectSettings(id: string, settings: ProjectSettingsInput): Promise<Project> {
  return unwrap<Project>(await apiClient.put(`/projects/${id}/settings`, settings))
}
