import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CalendarLtr24Regular, ChevronLeft20Regular, ChevronRight20Regular } from '@fluentui/react-icons'

export type DateRange = { from: string; to: string }
export type QuickRangeKey = 'today' | 'yesterday' | '7d' | '30d'

type DateRangePickerProps = {
  valueFrom: string
  valueTo: string
  onChange: (range: DateRange) => void
  onApply?: (range: DateRange) => void
  max?: string
  disabled?: boolean
  label?: string
}

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

function parseDate(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return null
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  if (
    Number.isNaN(date.getTime()) ||
    date.getFullYear() !== Number(match[1]) ||
    date.getMonth() !== Number(match[2]) - 1 ||
    date.getDate() !== Number(match[3])
  ) return null
  return date
}

function dateValue(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function dateDisplay(value: string) {
  return value ? value.replace(/-/g, '/') : '—'
}

function monthStart(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function addMonths(date: Date, offset: number) {
  return new Date(date.getFullYear(), date.getMonth() + offset, 1)
}

function rangeFor(days: number, endOffset = 0): DateRange {
  const to = new Date()
  to.setDate(to.getDate() + endOffset)
  const from = new Date(to)
  from.setDate(from.getDate() - days + 1)
  return { from: dateValue(from), to: dateValue(to) }
}

export function dateRangeForPreset(key: QuickRangeKey): DateRange {
  const presets: Record<QuickRangeKey, DateRange> = {
    today: rangeFor(1),
    yesterday: rangeFor(1, -1),
    '7d': rangeFor(7, -1),
    '30d': rangeFor(30),
  }
  return presets[key]
}

export function getActiveQuickRange(from: string, to: string): QuickRangeKey | '' {
  return (Object.keys({ today: true, yesterday: true, '7d': true, '30d': true }) as QuickRangeKey[])
    .find(key => {
      const range = dateRangeForPreset(key)
      return range.from === from && range.to === to
    }) || ''
}

function MonthGrid({ month, from, to, max, onSelect }: { month: Date; from: string; to: string; max?: string; onSelect: (value: string) => void }) {
  const cells = useMemo(() => {
    const first = monthStart(month)
    const firstDay = (first.getDay() + 6) % 7
    const gridStart = new Date(first.getFullYear(), first.getMonth(), 1 - firstDay)
    return Array.from({ length: 42 }, (_, index) => {
      const date = new Date(gridStart)
      date.setDate(gridStart.getDate() + index)
      return date
    })
  }, [month])

  return <div className="date-calendar-month">
    <div className="date-calendar-month-title">{month.getFullYear()}年{month.getMonth() + 1}月</div>
    <div className="date-calendar-weekdays">{WEEKDAYS.map(day => <span key={day}>{day}</span>)}</div>
    <div className="date-calendar-days">{cells.map(date => {
      const value = dateValue(date)
      const outside = date.getMonth() !== month.getMonth()
      const selected = value === from || value === to
      const inRange = Boolean(from && to && value >= from && value <= to)
      const isDisabled = Boolean(max && value > max)
      return <button
        key={value}
        type="button"
        className={`${outside ? 'is-outside' : ''} ${inRange ? 'is-in-range' : ''} ${selected ? 'is-selected' : ''}`}
        aria-label={value}
        aria-pressed={selected}
        aria-current={value === dateValue(new Date()) ? 'date' : undefined}
        disabled={isDisabled}
        onClick={() => onSelect(value)}
      >{date.getDate()}</button>
    })}</div>
  </div>
}

export function DateRangePicker({ valueFrom, valueTo, onChange, onApply, max, disabled, label = '日期' }: DateRangePickerProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const [open, setOpen] = useState(false)
  const [draftFrom, setDraftFrom] = useState(valueFrom)
  const [draftTo, setDraftTo] = useState(valueTo)
  const [selectingEnd, setSelectingEnd] = useState(false)
  const [draftError, setDraftError] = useState('')
  const [popoverPosition, setPopoverPosition] = useState({ left: 16, top: 16, width: 620, maxHeight: 640 })
  const endDate = parseDate(valueTo) || new Date()
  const [leftMonth, setLeftMonth] = useState(() => addMonths(monthStart(endDate), -1))

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      const target = event.target as Node
      if (!rootRef.current?.contains(target) && !popoverRef.current?.contains(target)) {
        setDraftFrom(valueFrom)
        setDraftTo(valueTo)
        setSelectingEnd(false)
        setDraftError('')
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setDraftFrom(valueFrom)
        setDraftTo(valueTo)
        setSelectingEnd(false)
        setDraftError('')
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', escape)
    }
  }, [open, valueFrom, valueTo])

  useLayoutEffect(() => {
    if (!open) return
    const placePopover = () => {
      const trigger = triggerRef.current
      if (!trigger) return
      const margin = 16
      const gap = 6
      const viewportWidth = window.innerWidth
      const viewportHeight = window.innerHeight
      const width = Math.min(620, Math.max(288, viewportWidth - margin * 2))
      const triggerBox = trigger.getBoundingClientRect()
      const measuredHeight = Math.min(popoverRef.current?.scrollHeight || 440, viewportHeight - margin * 2)
      const left = Math.min(Math.max(margin, triggerBox.left), viewportWidth - margin - width)
      const roomBelow = viewportHeight - triggerBox.bottom - margin - gap
      const roomAbove = triggerBox.top - margin - gap
      const openAbove = roomBelow < measuredHeight && roomAbove > roomBelow
      const top = openAbove
        ? Math.max(margin, triggerBox.top - gap - measuredHeight)
        : Math.min(triggerBox.bottom + gap, viewportHeight - margin - measuredHeight)
      setPopoverPosition({ left, top: Math.max(margin, top), width, maxHeight: viewportHeight - margin * 2 })
    }
    placePopover()
    window.addEventListener('resize', placePopover)
    window.addEventListener('scroll', placePopover, true)
    return () => {
      window.removeEventListener('resize', placePopover)
      window.removeEventListener('scroll', placePopover, true)
    }
  }, [open, leftMonth])

  const openPicker = () => {
    const currentEnd = parseDate(valueTo) || new Date()
    setDraftFrom(valueFrom)
    setDraftTo(valueTo)
    setSelectingEnd(false)
    setDraftError('')
    setLeftMonth(addMonths(monthStart(currentEnd), -1))
    setOpen(value => !value)
  }

  const apply = (range: DateRange) => {
    onChange(range)
    onApply?.(range)
  }

  const selectDate = (value: string) => {
    if (!selectingEnd || !draftFrom || draftTo) {
      setDraftFrom(value)
      setDraftTo('')
      setSelectingEnd(true)
      return
    }
    if (value < draftFrom) {
      setDraftFrom(value)
      setDraftTo('')
      return
    }
    setDraftTo(value)
    setSelectingEnd(false)
  }

  const applyDraft = () => {
    if (!draftFrom || !draftTo) {
      setDraftError('请先选择开始日期和结束日期')
      return
    }
    apply({ from: draftFrom, to: draftTo })
    setDraftError('')
    setOpen(false)
    triggerRef.current?.focus()
  }

  const cancel = () => {
    setDraftFrom(valueFrom)
    setDraftTo(valueTo)
    setSelectingEnd(false)
    setDraftError('')
    setOpen(false)
    triggerRef.current?.focus()
  }

  return <div className="date-range-control" ref={rootRef}>
    <div className="date-range-anchor">
      <span className="date-range-label">{label}</span>
      <button ref={triggerRef} type="button" className="date-range-trigger" disabled={disabled} aria-label={`${label} ${dateDisplay(valueFrom)} ~ ${dateDisplay(valueTo)}`} aria-haspopup="dialog" aria-expanded={open} onClick={openPicker}>
        <span>{dateDisplay(valueFrom)} <b>~</b> {dateDisplay(valueTo)}</span>
        <CalendarLtr24Regular />
      </button>
      {open && createPortal(<div
        ref={popoverRef}
        className="date-range-popover"
        role="dialog"
        aria-labelledby={titleId}
        style={popoverPosition}
      >
        <div className="date-range-popover-head">
          <strong id={titleId}>选择日期范围</strong>
          <div className="date-range-selected-values"><span><small>开始日期</small>{dateDisplay(draftFrom)}</span><b>至</b><span><small>结束日期</small>{dateDisplay(draftTo)}</span></div>
          <small>{selectingEnd ? '请选择结束日期' : '请选择开始日期'}</small>
        </div>
        <div className="date-range-popover-body">
          <div className="date-calendar-nav">
            <button type="button" aria-label="上一个月" onClick={() => setLeftMonth(month => addMonths(month, -1))}><ChevronLeft20Regular /></button>
            <button type="button" aria-label="下一个月" onClick={() => setLeftMonth(month => addMonths(month, 1))}><ChevronRight20Regular /></button>
          </div>
          <div className="date-calendar-months">
            <MonthGrid month={leftMonth} from={draftFrom} to={draftTo} max={max} onSelect={selectDate} />
            <MonthGrid month={addMonths(leftMonth, 1)} from={draftFrom} to={draftTo} max={max} onSelect={selectDate} />
          </div>
          {draftError ? <p className="date-range-error" role="status">{draftError}</p> : null}
        </div>
        <div className="date-range-popover-actions"><button type="button" onClick={cancel}>取消</button><button type="button" className="is-primary" onClick={applyDraft}>应用</button></div>
      </div>, document.body)}
    </div>
  </div>
}
