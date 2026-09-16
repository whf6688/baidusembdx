export type UiTimeZone = 'Asia/Shanghai' | 'UTC'

// Keep display preferences inside the current browser tab. The persisted source of
// truth is the project preference API, so two project tabs never overwrite each
// other's display timezone through shared localStorage.
let activeTimeZone: UiTimeZone = 'Asia/Shanghai'

export function getUiTimeZone(): UiTimeZone {
  return activeTimeZone
}

export function setUiTimeZone(value: string): void {
  activeTimeZone = value === 'UTC' ? 'UTC' : 'Asia/Shanghai'
}
