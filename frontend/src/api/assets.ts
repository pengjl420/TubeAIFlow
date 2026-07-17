import { API_BASE_URL, apiClient, unwrap } from './client'
import type {
  AssetImportResult,
  MediaAsset,
  SceneCandidate,
  SceneSearchResult,
} from '../types/media'

export async function listAssets(): Promise<MediaAsset[]> {
  const result = unwrap<{ assets: MediaAsset[] }>(await apiClient.get('/assets'))
  return result.assets
}

export async function importAssets(directory: string): Promise<AssetImportResult> {
  return unwrap(await apiClient.post('/assets/import', { directory }, { timeout: 300_000 }))
}

export async function ingestAsset(mediaId: string): Promise<{ asset: MediaAsset; errors: Array<{ shot_id: string; error: string }> }> {
  return unwrap(await apiClient.post(`/assets/${encodeURIComponent(mediaId)}/ingest`, undefined, { timeout: 300_000 }))
}

export async function listSceneCandidates(projectId: string, sceneId: string): Promise<SceneCandidate[]> {
  const result = unwrap<{ candidates: SceneCandidate[] }>(await apiClient.get(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/candidates`,
  ))
  return result.candidates
}

export async function searchSceneCandidates(projectId: string, sceneId: string): Promise<SceneSearchResult> {
  return unwrap(await apiClient.post(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/search`,
  ))
}

export async function assignSceneCandidate(
  projectId: string,
  sceneId: string,
  candidateId: string,
): Promise<{ id: string; candidate_id: string; media_shot_id: string }> {
  return unwrap(await apiClient.post(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/assign`,
    { candidate_id: candidateId },
  ))
}

export function assetPreviewUrl(path: string | null): string {
  if (!path) return ''
  const origin = API_BASE_URL.replace(/\/api\/?$/, '')
  return path.startsWith('http') ? path : `${origin}${path}`
}
