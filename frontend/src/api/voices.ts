import { apiClient, unwrap } from './client'

export async function listVoices() {
  return unwrap(await apiClient.get('/voices'))
}
