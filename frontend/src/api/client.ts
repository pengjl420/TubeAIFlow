import axios from 'axios'

const launchPort = import.meta.env.VITE_API_PORT
const DEFAULT_API_BASE_URL = `http://127.0.0.1:${launchPort || '18080'}/api`
// A launcher-selected fallback port must override an address saved by an
// earlier run that used the preferred port.
export const API_BASE_URL = launchPort
  ? DEFAULT_API_BASE_URL
  : localStorage.getItem('tube_api_base_url') || DEFAULT_API_BASE_URL

interface ApiEnvelope<T> {
  success: boolean
  data?: T
  error?: string
  code?: string
}

export interface EngineHealth {
  status: string
  product: string
  engine_version: string
  mode: string
}

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
})

export function rememberApiAddress(host: string, port: number): void {
  const browserHost = host === '127.0.0.1' || host === 'localhost' ? host : window.location.hostname
  localStorage.setItem('tube_api_base_url', `http://${browserHost}:${port}/api`)
}

apiClient.interceptors.response.use(undefined, (error) => {
  const message = error.response?.data?.detail?.error
    || error.response?.data?.error
    || error.message
    || '请求失败'
  return Promise.reject(new Error(message))
})

export function unwrap<T>(response: { data: ApiEnvelope<T> }): T {
  if (!response.data.success) {
    throw new Error(response.data.error || '请求失败')
  }
  if (response.data.data === undefined) {
    throw new Error('服务器返回了空数据')
  }
  return response.data.data
}

export async function getEngineHealth(): Promise<EngineHealth> {
  return unwrap<EngineHealth>(await apiClient.get('/health', { timeout: 5000 }))
}
