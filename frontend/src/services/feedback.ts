import { reactive } from 'vue'

export type FeedbackTone = 'info' | 'success' | 'warning' | 'danger'

export interface ConfirmOptions {
  title: string
  description: string
  detail?: string
  eyebrow?: string
  confirmText?: string
  cancelText?: string
  tone?: Exclude<FeedbackTone, 'success'>
}

export interface ToastOptions {
  title: string
  description?: string
  tone?: FeedbackTone
  duration?: number
}

interface ConfirmRequest extends Required<Omit<ConfirmOptions, 'detail'>> {
  detail?: string
  resolve: (confirmed: boolean) => void
}

interface ToastMessage extends Required<Omit<ToastOptions, 'description'>> {
  id: number
  description?: string
}

interface FeedbackState {
  confirm: ConfirmRequest | null
  toasts: ToastMessage[]
}

export const feedbackState = reactive<FeedbackState>({
  confirm: null,
  toasts: [],
})

let toastId = 0
const toastTimers = new Map<number, ReturnType<typeof setTimeout>>()

export function confirmAction(options: ConfirmOptions) {
  if (feedbackState.confirm) feedbackState.confirm.resolve(false)

  return new Promise<boolean>((resolve) => {
    feedbackState.confirm = {
      title: options.title,
      description: options.description,
      detail: options.detail,
      eyebrow: options.eyebrow || '请确认操作',
      confirmText: options.confirmText || '确认',
      cancelText: options.cancelText || '取消',
      tone: options.tone || 'warning',
      resolve,
    }
  })
}

export function resolveConfirm(confirmed: boolean) {
  const request = feedbackState.confirm
  if (!request) return
  feedbackState.confirm = null
  request.resolve(confirmed)
}

export function dismissToast(id: number) {
  const timer = toastTimers.get(id)
  if (timer) clearTimeout(timer)
  toastTimers.delete(id)
  feedbackState.toasts = feedbackState.toasts.filter((toast) => toast.id !== id)
}

export function showToast(options: ToastOptions) {
  const id = ++toastId
  const toast: ToastMessage = {
    id,
    title: options.title,
    description: options.description,
    tone: options.tone || 'info',
    duration: options.duration ?? 3600,
  }
  feedbackState.toasts.push(toast)

  if (toast.duration > 0) {
    toastTimers.set(id, setTimeout(() => dismissToast(id), toast.duration))
  }
  return id
}
