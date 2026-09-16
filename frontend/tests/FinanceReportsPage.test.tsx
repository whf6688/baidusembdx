import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FinanceReportsPage } from '../src/features/finance/FinanceReportsPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('FinanceReportsPage', () => {
  it('renders reconciliation summary and saves editable reported spend', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === 'PATCH') return new Response(JSON.stringify({ request_id: 'test', status: 'ok', data: { updated: 1 } }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (url.includes('/finance/profit')) return new Response(JSON.stringify({ request_id: 'test', status: 'ok', data: {
        rows: [{ date: '2026-09-16', project_name: '减肥搜索', operator_name: null, reported_spend: null, conversions: 2, reported_conversion_cost: null, account_spend: '100.00', cash_spend: '80.00', cash_conversion_cost: '40.00', profit: null }],
        summary: { reported_spend: null, conversions: 2, reported_conversion_cost: null, account_spend: '100.00', cash_spend: '80.00', cash_conversion_cost: '40.00', profit: null },
        metric_mode: 'add', operator_name: null, operator_names: ['王康', '王聪'], total: 1, page: 1, page_size: 20, total_pages: 1,
      } }), { status: 200, headers: { 'content-type': 'application/json' } })
      return new Response(JSON.stringify({ request_id: 'test', status: 'ok', data: {
        rows: [{ date: '2026-09-16', account_name: '充值户01', account_id: 123, manager_name: '管家甲', type: '充值', movement_type: 'recharge', account_currency: '1200.00', rebate_rate: '50.00', cash_amount: '800.00', reconciled: false, reconciliation_status: '未对账', watermark: '2026-09-16T08:00:00Z' }],
        summary: { account_currency: '1200.00', cash_amount: '800.00' }, total: 1, page: 1, page_size: 20, total_pages: 1, watermark: '2026-09-16T08:00:00Z',
      } }), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<FinanceReportsPage project={{ id: 'p1', name: '减肥搜索', code: 'jfsem', enabled: true, account_count: 1, manager_count: 1 }} canManage />)

    await waitFor(() => expect(screen.getByText('充值户01')).toBeInTheDocument())
    expect(within(screen.getByRole('table')).getAllByRole('columnheader').map(cell => cell.textContent)).toEqual(['', '日期', '账户名称', '账户ID', '类型', '账户币求和', '返点', '现金求和', '对账状态'])
    expect(screen.getAllByText('¥ 1,200.00')).toHaveLength(2)
    fireEvent.click(screen.getByRole('checkbox', { name: '选择 2026-09-16 充值户01 充值' }))
    fireEvent.click(screen.getByRole('button', { name: '确认对账' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH' && String(init.body).includes('"reconciled":true'))).toBe(true))

    fireEvent.click(screen.getByRole('tab', { name: '利润报表' }))
    await waitFor(() => expect(screen.getByText('减肥搜索')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: '编辑' }))
    fireEvent.change(screen.getByPlaceholderText('填写报消耗'), { target: { value: '150' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH' && String(init.body).includes('150'))).toBe(true))
  })
})
