<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { dismissToast, feedbackState, resolveConfirm } from '../../services/feedback'

const confirmButton = ref<HTMLButtonElement | null>(null)
let previousFocus: HTMLElement | null = null

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && feedbackState.confirm) resolveConfirm(false)
}

watch(
  () => feedbackState.confirm,
  async (request) => {
    if (request) {
      previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
      document.body.classList.add('has-app-dialog')
      await nextTick()
      confirmButton.value?.focus()
    } else {
      document.body.classList.remove('has-app-dialog')
      previousFocus?.focus()
      previousFocus = null
    }
  },
)

window.addEventListener('keydown', handleKeydown)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  document.body.classList.remove('has-app-dialog')
})
</script>

<template>
  <Teleport to="body">
    <div class="app-toast-region" aria-live="polite" aria-atomic="true">
      <TransitionGroup name="app-toast">
        <article
          v-for="toast in feedbackState.toasts"
          :key="toast.id"
          class="app-toast"
          :class="`is-${toast.tone}`"
          role="status"
        >
          <span class="app-toast-icon" aria-hidden="true">
            <svg v-if="toast.tone === 'success'" viewBox="0 0 24 24"><path d="m5 12.5 4.2 4.2L19 7" /></svg>
            <svg v-else-if="toast.tone === 'danger'" viewBox="0 0 24 24"><path d="M12 8v5m0 3.4v.1M12 3.5 21 20H3L12 3.5Z" /></svg>
            <svg v-else-if="toast.tone === 'warning'" viewBox="0 0 24 24"><path d="M12 8v5m0 3.4v.1M12 3.5 21 20H3L12 3.5Z" /></svg>
            <svg v-else viewBox="0 0 24 24"><path d="M12 10.5V17m0-10.2v.1M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>
          </span>
          <div class="app-toast-copy">
            <strong>{{ toast.title }}</strong>
            <p v-if="toast.description">{{ toast.description }}</p>
          </div>
          <button class="app-toast-close" type="button" aria-label="关闭提示" @click="dismissToast(toast.id)">×</button>
        </article>
      </TransitionGroup>
    </div>

    <Transition name="app-dialog">
      <div v-if="feedbackState.confirm" class="app-dialog-backdrop" @mousedown.self="resolveConfirm(false)">
        <section
          class="app-dialog-card"
          :class="`is-${feedbackState.confirm.tone}`"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="app-dialog-title"
          aria-describedby="app-dialog-description"
        >
          <button class="app-dialog-close" type="button" aria-label="关闭弹窗" @click="resolveConfirm(false)">×</button>
          <div class="app-dialog-heading">
            <span class="app-dialog-icon" aria-hidden="true">
              <svg v-if="feedbackState.confirm.tone === 'info'" viewBox="0 0 24 24"><path d="M12 10.5V17m0-10.2v.1M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>
              <svg v-else viewBox="0 0 24 24"><path d="M12 8v5m0 3.4v.1M12 3.5 21 20H3L12 3.5Z" /></svg>
            </span>
            <div>
              <span class="app-dialog-eyebrow">{{ feedbackState.confirm.eyebrow }}</span>
              <h2 id="app-dialog-title">{{ feedbackState.confirm.title }}</h2>
            </div>
          </div>
          <p id="app-dialog-description" class="app-dialog-description">{{ feedbackState.confirm.description }}</p>
          <div v-if="feedbackState.confirm.detail" class="app-dialog-detail">
            <span aria-hidden="true">i</span>
            <p>{{ feedbackState.confirm.detail }}</p>
          </div>
          <div class="app-dialog-actions">
            <button class="secondary-button" type="button" @click="resolveConfirm(false)">
              {{ feedbackState.confirm.cancelText }}
            </button>
            <button
              ref="confirmButton"
              class="app-dialog-confirm"
              :class="`is-${feedbackState.confirm.tone}`"
              type="button"
              @click="resolveConfirm(true)"
            >
              {{ feedbackState.confirm.confirmText }}
            </button>
          </div>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>
