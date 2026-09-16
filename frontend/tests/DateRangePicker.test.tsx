import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DateFilterGroup } from '../src/components/DateFilterGroup'
import { DateRangePicker } from '../src/components/DateRangePicker'

describe('DateRangePicker', () => {
  afterEach(cleanup)
  it('offers the commerce date shortcuts without a total option', () => {
    const onChange = vi.fn()
    render(<DateFilterGroup valueFrom="2026-09-12" valueTo="2026-09-12" onChange={onChange} />)
    expect(screen.getByRole('button', { name: '今日' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '昨日' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '近7日' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '总计' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '今日' }))
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('opens a two-month date range dialog', () => {
    render(<DateFilterGroup valueFrom="2026-09-01" valueTo="2026-09-12" onChange={() => undefined} />)
    fireEvent.click(screen.getByRole('button', { name: /2026\/09\/01/ }))
    expect(screen.getByRole('dialog', { name: '选择日期范围' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '上一个月' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '下一个月' })).toBeInTheDocument()
  })

  it('only applies a manually selected range after confirmation', () => {
    const onChange = vi.fn()
    render(<DateRangePicker valueFrom="" valueTo="" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /— ~ —/ }))
    const dialog = screen.getByRole('dialog', { name: '选择日期范围' })
    expect(dialog).toHaveTextContent('开始日期')
    expect(dialog).toHaveTextContent('结束日期')
    fireEvent.click(screen.getByRole('button', { name: '应用' }))
    expect(screen.getByText('请先选择开始日期和结束日期')).toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.queryByRole('dialog', { name: '选择日期范围' })).not.toBeInTheDocument()
  })

  it('keeps manual dates as a draft until application', () => {
    const onChange = vi.fn()
    render(<DateRangePicker valueFrom="2026-09-01" valueTo="2026-09-02" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /2026\/09\/01/ }))
    fireEvent.click(screen.getByRole('button', { name: '2026-08-28' }))
    fireEvent.click(screen.getByRole('button', { name: '2026-08-30' }))
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '应用' }))
    expect(onChange).toHaveBeenCalledWith({ from: '2026-08-28', to: '2026-08-30' })
  })

  it('cancels a draft with Escape and returns focus to the trigger', () => {
    const onChange = vi.fn()
    render(<DateRangePicker valueFrom="2026-09-01" valueTo="2026-09-02" onChange={onChange} label="统计日期" />)
    const trigger = screen.getByRole('button', { name: /统计日期 2026\/09\/01/ })
    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole('button', { name: '2026-08-28' }))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: '选择日期范围' })).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
    expect(trigger).toHaveFocus()
  })

  it('disables dates after the configured maximum', () => {
    render(<DateRangePicker valueFrom="2026-09-01" valueTo="2026-09-02" max="2026-09-02" onChange={() => undefined} />)
    fireEvent.click(screen.getByRole('button', { name: /2026\/09\/01/ }))
    for (const date of screen.getAllByRole('button', { name: '2026-09-03' })) expect(date).toBeDisabled()
  })
})
