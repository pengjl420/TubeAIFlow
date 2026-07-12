import axios from 'axios'

export const API_BASE_URL = 'http://127.0.0.1:18080/api'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
})

apiClient.interceptors.response.use(undefined, (error) => {
  const message = error.response?.data?.detail?.error
    || error.response?.data?.error
    || error.message
    || '请求失败'
  return Promise.reject(new Error(message))
})

export function unwrap<T>(response: { data: { success: boolean; data?: T; error?: string } }): T {
  if (!response.data.success) {
    throw new Error(response.data.error || '请求失败')
  }
  return response.data.data as T
}
