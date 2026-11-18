import { apiClient, unwrap } from './client'

export interface ComputeConnection {
  id: string
  name: string
  provider: string
  region: string
  zone: string
  project_id: string
  instance_id: string
  config_version: number
  management_mode: string
  created_at: string
}
export interface ConnectionInput {
  name: string
  region: string
  zone: string
  project_id: string
  public_key: string
  private_key: string
}
export interface ComputeInstance {
  instance_id: string
  name: string
  state: string
  region: string
  zone: string
  gpu_type: string
  gpu_count: number
  is_spot: boolean
}
export interface InstancePage { total: number; instances: ComputeInstance[] }
export interface ConnectionCheck {
  instance: ComputeInstance
  worker_ready: boolean
  management_mode: string
}
const base = '/compute/connections'
const path = (id: string) => `${base}/${encodeURIComponent(id)}`
// Platform queries may take the backend's full 30 second timeout.
const queryOptions = { timeout: 40000 }
export async function listComputeConnections(): Promise<ComputeConnection[]> {
  return unwrap(await apiClient.get(base))
}
export async function createComputeConnection(input: ConnectionInput): Promise<ComputeConnection> {
  return unwrap(await apiClient.post(base, input))
}
export async function listComputeInstances(id: string, offset = 0, limit = 20): Promise<InstancePage> {
  return unwrap(await apiClient.get(`${path(id)}/instances`, { ...queryOptions, params: { offset, limit } }))
}
export async function bindComputeInstance(id: string, instanceId: string): Promise<ComputeConnection> {
  return unwrap(await apiClient.put(`${path(id)}/instance`, { instance_id: instanceId }, queryOptions))
}
export async function checkComputeConnection(id: string): Promise<ConnectionCheck> {
  return unwrap(await apiClient.post(`${path(id)}/check`, undefined, queryOptions))
}

export async function powerComputeInstance(id: string, instanceId: string, action: 'start' | 'stop'): Promise<{ accepted: boolean; expected_state: string }> {
  return unwrap(await apiClient.post(`${path(id)}/${action}`, { instance_id: instanceId }, { timeout: 90000 }))
}
