import { apiClient, unwrap } from './client'
import type { Segment } from '../types/segment'

export async function listSegments(projectId: string): Promise<Segment[]> {
  return unwrap<Segment[]>(await apiClient.get(`/projects/${projectId}/segments`))
}

export async function updateSegment(
  projectId: string,
  segmentId: string,
  payload: Partial<Pick<Segment, 'text_zh' | 'text_en'>>,
): Promise<Segment> {
  return unwrap<Segment>(await apiClient.put(`/projects/${projectId}/segments/${segmentId}`, payload))
}
