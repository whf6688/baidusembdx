import type { KeyboardEvent } from 'react'

/** Shared keyboard interaction for horizontal tab groups. */
export function moveHorizontalTab<T extends string>(
  event: KeyboardEvent<HTMLButtonElement>,
  ids: readonly T[],
  currentId: T,
  select: (id: T) => void,
) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key) || !ids.length) return
  event.preventDefault()
  const currentIndex = Math.max(0, ids.indexOf(currentId))
  const nextIndex = event.key === 'Home' ? 0
    : event.key === 'End' ? ids.length - 1
      : (currentIndex + (event.key === 'ArrowRight' ? 1 : -1) + ids.length) % ids.length
  select(ids[nextIndex])
  const tablist = event.currentTarget.closest('[role="tablist"]')
  const buttons = Array.from(tablist?.querySelectorAll<HTMLButtonElement>('[role="tab"]') || [])
  buttons[nextIndex]?.focus()
}
