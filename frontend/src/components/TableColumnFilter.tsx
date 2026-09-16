import { useState } from 'react'
import type { ReactNode } from 'react'
import { Button, Popover, PopoverSurface, PopoverTrigger } from '@fluentui/react-components'
import { DismissRegular, FilterRegular } from '@fluentui/react-icons'
import { SearchField } from './SearchField'

export type TableColumnFilterConfig = {
  label: string
  value: string
  options: string[][]
  onChange: (value: string) => void
  multiple?: boolean
}

const filterValues = (value: string) => value ? value.split(',').filter(Boolean) : []

export function TableColumnFilter({ filter, children }: { filter: TableColumnFilterConfig; children?: ReactNode }) {
  const [open, setOpen] = useState(false)
  return <span className="account-column-heading">
    {children || filter.label}
    <Popover open={open} onOpenChange={(_, data) => setOpen(data.open)} positioning={{ position: 'below', align: 'start', offset: 8 }} trapFocus>
      <PopoverTrigger disableButtonEnhancement>
        <button type="button" className={`account-column-filter-trigger${filter.value ? ' is-active' : ''}`} aria-label={`筛选${filter.label}`} aria-expanded={open}><FilterRegular /></button>
      </PopoverTrigger>
      <PopoverSurface className="account-column-filter-popover">
        <TableColumnFilterMenu filter={filter} onClose={() => setOpen(false)} />
      </PopoverSurface>
    </Popover>
  </span>
}

function TableColumnFilterMenu({ filter, onClose }: { filter: TableColumnFilterConfig; onClose: () => void }) {
  const allValues = filter.options.map(([value]) => value)
  const multiple = filter.multiple !== false
  const [keyword, setKeyword] = useState('')
  const [selectedValues, setSelectedValues] = useState<string[]>(() => filter.value ? filterValues(filter.value) : multiple ? allValues : [])
  const normalizedKeyword = keyword.trim().toLowerCase()
  const options = filter.options.filter(([, label]) => !normalizedKeyword || label.toLowerCase().includes(normalizedKeyword))
  const allSelected = multiple ? Boolean(allValues.length && allValues.every(value => selectedValues.includes(value))) : !selectedValues.length
  const partlySelected = multiple && Boolean(selectedValues.length && !allSelected)
  const toggleValue = (value: string, checked: boolean) => setSelectedValues(current => multiple ? (checked ? [...current, value] : current.filter(item => item !== value)) : checked ? [value] : [])
  const applySelection = () => { filter.onChange(multiple ? (allSelected ? '' : selectedValues.join(',')) : (selectedValues[0] || '')); onClose() }
  return <div className="account-column-filter-menu" role="group" aria-label={`${filter.label}筛选`}>
    <div className="account-column-filter-menu-head"><strong>{filter.label}筛选</strong><button type="button" aria-label={`关闭${filter.label}筛选`} onClick={onClose}><DismissRegular /></button></div>
    <div className="account-column-filter-search-row"><label className="account-column-filter-select-all" title={multiple ? '全选' : '全部'}><input type="checkbox" checked={allSelected} ref={node => { if (node) node.indeterminate = partlySelected }} aria-label={`${multiple ? '全选' : '全部'}${filter.label}`} onChange={event => setSelectedValues(multiple && event.target.checked ? allValues : [])} /></label><SearchField className="account-column-filter-search" value={keyword} placeholder={`搜索${filter.label}`} ariaLabel={`搜索${filter.label}`} onChange={setKeyword} onSearch={() => undefined} onClear={() => setKeyword('')} /></div>
    <div className="account-column-filter-options">{options.length ? options.map(([value, label]) => <label key={value}><input type="checkbox" checked={selectedValues.includes(value)} onChange={event => toggleValue(value, event.target.checked)} /><span>{label}</span></label>) : <span>没有匹配项</span>}</div>
    <div className="account-column-filter-actions"><Button size="small" appearance="secondary" onClick={() => setSelectedValues(multiple ? allValues : [])}>重置</Button><Button size="small" appearance="primary" disabled={multiple && !selectedValues.length} onClick={applySelection}>应用</Button></div>
  </div>
}
