import { DateRangePicker, type DateRange, type QuickRangeKey } from './DateRangePicker'
import { QuickRangeGroup } from './QuickRangeGroup'

type DateFilterGroupProps = {
  valueFrom: string
  valueTo: string
  onChange: (range: DateRange) => void
  onApply?: (range: DateRange) => void
  max?: string
  disabled?: boolean
  label?: string
  quickRanges?: QuickRangeKey[]
}

/** Standard ViewControls date composition: quick choices plus a confirmed range picker. */
export function DateFilterGroup({ valueFrom, valueTo, onChange, onApply, max, disabled, label, quickRanges }: DateFilterGroupProps) {
  const apply = (range: DateRange) => {
    onChange(range)
    onApply?.(range)
  }
  return <div className="date-filter-group">
    <QuickRangeGroup valueFrom={valueFrom} valueTo={valueTo} onChange={apply} max={max} disabled={disabled} options={quickRanges} />
    <DateRangePicker valueFrom={valueFrom} valueTo={valueTo} onChange={onChange} onApply={onApply} max={max} disabled={disabled} label={label} />
  </div>
}
