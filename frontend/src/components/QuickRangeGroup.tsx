import type { DateRange } from './DateRangePicker'
import { dateRangeForPreset, getActiveQuickRange, type QuickRangeKey } from './DateRangePicker'

type QuickRangeGroupProps = {
  valueFrom: string
  valueTo: string
  onChange: (range: DateRange) => void
  disabled?: boolean
  max?: string
  options?: QuickRangeKey[]
}

const labels: Record<QuickRangeKey, string> = {
  today: '今日',
  yesterday: '昨日',
  '7d': '近7日',
  '30d': '近30日',
}

/** Stable quick date control; it owns presets only and does not render a calendar. */
export function QuickRangeGroup({ valueFrom, valueTo, onChange, disabled, max, options = ['today', 'yesterday', '7d', '30d'] }: QuickRangeGroupProps) {
  const active = getActiveQuickRange(valueFrom, valueTo)
  return <div className="date-range-presets" aria-label="快捷日期">
    {options.map(key => {
      const range = dateRangeForPreset(key)
      const beyondMax = Boolean(max && range.to > max)
      return <button key={key} type="button" className={active === key ? 'is-active' : ''} aria-pressed={active === key} disabled={disabled || beyondMax} onClick={() => onChange(range)}>{labels[key]}</button>
    })}
  </div>
}
