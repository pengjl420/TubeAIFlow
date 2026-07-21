import type { Directive } from 'vue'

type ClickOutsideElement = HTMLElement & {
  __clickOutsideHandler__?: (event: PointerEvent) => void
  __clickOutsideCallback__?: (event: PointerEvent) => void
}

export const clickOutside: Directive<ClickOutsideElement, (event: PointerEvent) => void> = {
  mounted(element, binding) {
    const handler = (event: PointerEvent) => {
      const target = event.target
      if (target instanceof Node && !element.contains(target)) element.__clickOutsideCallback__?.(event)
    }

    element.__clickOutsideCallback__ = binding.value
    element.__clickOutsideHandler__ = handler
    document.addEventListener('pointerdown', handler, true)
  },
  updated(element, binding) {
    element.__clickOutsideCallback__ = binding.value
  },
  beforeUnmount(element) {
    const handler = element.__clickOutsideHandler__
    if (handler) document.removeEventListener('pointerdown', handler, true)
    delete element.__clickOutsideHandler__
    delete element.__clickOutsideCallback__
  },
}
