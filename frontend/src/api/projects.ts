import { apiClient, unwrap } from './client'
import type { Project } from '../types/project'

export async function listProjects(): Promise<Project[]> {
  return unwrap<Project[]>(await apiClient.get('/projects'))
}

export async function createProject(name: string, referenceAudio: File): Promise<Project> {
  const form = new FormData()
  form.append('name', name)
  form.append('reference_audio', referenceAudio)
  return unwrap<Project>(await apiClient.post('/projects', form))
}

export async function getProject(id: string): Promise<Project> {
  return unwrap<Project>(await apiClient.get(`/projects/${id}`))
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
  final_en_srt_path?: string
  final_video_path?: string
  files: ProjectOutputFile[]
}

export interface DirectoryEntry {
  name: string
  path: string
}

export interface DirectoryList {
  current: string
  parent?: string | null
  roots: string[]
  directories: DirectoryEntry[]
}

export async function getProjectOutputs(id: string): Promise<ProjectOutputs> {
  return unwrap<ProjectOutputs>(await apiClient.get(`/projects/${id}/outputs`))
}

export async function listDirectories(path?: string): Promise<DirectoryList> {
  return unwrap<DirectoryList>(await apiClient.post('/projects/directories', { path: path || null }))
}

export async function saveScript(id: string, text: string): Promise<Project> {
  return unwrap<Project>(await apiClient.post(`/projects/${id}/script`, { text }))
}

export async function createSegments(id: string) {
  return unwrap(await apiClient.post(`/projects/${id}/segments`))
}

export async function uploadReferenceAudio(id: string, file: File): Promise<Project> {
  const form = new FormData()
  form.append('file', file)
  return unwrap<Project>(await apiClient.post(`/projects/${id}/reference-audio`, form))
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
