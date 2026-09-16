import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ViewportStickyPagination } from '../src/components/ViewportStickyPagination'

describe('ViewportStickyPagination', () => {
  afterEach(cleanup)

  it('renders the standard page controls in the required order', () => {
    render(<ViewportStickyPagination page={1} totalPages={12} total={236} pageSize={20} onPageChange={() => undefined} onPageSizeChange={() => undefined} ariaLabel="测试分页" />)
    expect(screen.getByText('显示 1–20，共 236 条')).toBeInTheDocument()
    const controls = screen.getByRole('navigation', { name: '分页操作' })
    expect(controls.children).toHaveLength(6)
    expect(screen.getByRole('combobox', { name: '每页条数' })).toHaveValue('20')
    expect(screen.getByRole('textbox', { name: '跳转页码' })).toHaveValue('1')
    expect(screen.getByText('/ 12 页')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '跳转' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '下一页' })).toBeEnabled()
  })

  it('validates jump pages without silently clamping them', () => {
    const onPageChange = vi.fn()
    render(<ViewportStickyPagination page={2} totalPages={5} total={95} pageSize={20} onPageChange={onPageChange} ariaLabel="测试分页" />)
    const input = screen.getByRole('textbox', { name: '跳转页码' })
    fireEvent.change(input, { target: { value: '9' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(screen.getByRole('status')).toHaveTextContent('请输入 1 至 5 之间的页码')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(onPageChange).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: '4' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onPageChange).toHaveBeenCalledWith(4)
  })
})
