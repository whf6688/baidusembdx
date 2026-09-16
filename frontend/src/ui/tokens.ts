import type { BrandVariants } from '@fluentui/react-components'

export const designTokens = {
  '--ads-canvas': '#F6F8FA',
  '--ads-surface': '#FFFFFF',
  '--ads-surface-subtle': '#F3F4F6',
  '--ads-surface-selected': '#DDF4FF',
  '--ads-text': '#1F2328',
  '--ads-text-secondary': '#59636E',
  '--ads-text-muted': '#818B98',
  '--ads-table-header': '#475569',
  '--ads-border': '#D0D7DE',
  '--ads-border-subtle': '#EAEFF3',
  '--ads-border-strong': '#8C959F',
  '--ads-primary': '#0969DA',
  '--ads-primary-hover': '#0550AE',
  '--ads-success-bg': '#DAFBE1',
  '--ads-success-fg': '#116329',
  '--ads-warning-bg': '#FFF8C5',
  '--ads-warning-fg': '#7D4E00',
  '--ads-danger-bg': '#FFEBE9',
  '--ads-danger-fg': '#A40E26',
  '--ads-financial-negative': '#B42318',
  '--ads-radius-control': '4px',
  '--ads-radius-surface': '6px',
  '--ads-control-height': '32px',
  '--ads-z-sticky': '10',
  '--ads-z-popover': '20',
  '--ads-z-dialog': '30',
} as const

export const commerceBlue: BrandVariants = {
  10: '#F6F8FA', 20: '#EEF6FF', 30: '#DDF4FF', 40: '#B6E3FF', 50: '#80CCFF',
  60: '#54AEFF', 70: '#218BFF', 80: '#0969DA', 90: '#0550AE', 100: '#033D8B',
  110: '#002F6C', 120: '#002155', 130: '#001A44', 140: '#001331', 150: '#000D22', 160: '#000719',
}

export function installDesignTokens(root: HTMLElement) {
  for (const [name, value] of Object.entries(designTokens)) root.style.setProperty(name, value)
}
