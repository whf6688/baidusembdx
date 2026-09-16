import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReportsPage } from '../src/features/reports/ReportsPage'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('ReportsPage', () => {
  it('uses account-list header filters, metric sorting and toolbar dimensions', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      request_id: 'test', status: 'ok', data: {
        date_from: '2026-09-16', date_to: '2026-09-16', total: 1, page: 1, page_size: 20, total_pages: 1,
        search: '', page_type: '', page_types: ['二跳'], manager_id: '', managers: [{ id: 'm1', name: '管家甲' }, { id: 'm2', name: '管家乙' }],
        account_type: '', account_types: ['二跳账户'], operator_name: '', operator_names: ['王康'], has_unassigned_operator: true,
        account_names: ['测试账户'], lifecycles: [], sort_by: 'spend', sort_order: 'desc',
        summary: { spend: '88.80', cash_spend: '59.20', impressions: 1000, clicks: 30, uv: 20, copies: 4, adds: 2, cpc: '2.96', uv_cost: '4.44', copy_cost: '22.20', add_cost: '44.40', cash_add_cost: '29.60' },
        rows: [{ date: '2026-09-16', account_id: 12345678, account_name: '测试账户', operator_name: '王康', manager_id: 'm1', manager_name: '管家甲', account_type: '二跳账户', page_type: '二跳', balance: '500.00', impressions: 1000, clicks: 30, spend: '88.80', cash_spend: '59.20', uv: 20, copies: 4, adds: 2, cpc: '2.96', uv_cost: '4.44', copy_cost: '22.20', add_cost: '44.40', cash_add_cost: '29.60' }],
      },
    }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    render(<ReportsPage project={{ id: 'p1', name: '减肥搜索', code: 'jfsem', enabled: true, account_count: 1, manager_count: 2 }} canManage />)

    await waitFor(() => expect(screen.getByText('测试账户')).toBeInTheDocument())
    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('columnheader').map(cell => cell.textContent)).toEqual([
      '成本判断', '运营', '账户管家', '账户类型', '页面类型', '账户', '账户ID', '余额', '展现', '点击', '消费↓', 'UV', '加粉', 'CPC', 'UV成本', '加粉成本', '现金消费', '现金加粉成本',
    ])
    expect(['成本判断', '运营', '账户管家', '账户类型', '页面类型', '账户'].map(label => within(table).getByRole('button', { name: `筛选${label}` }))).toHaveLength(6)
    expect(within(table).queryByRole('button', { name: '账户ID' })).not.toBeInTheDocument()
    expect(within(table).queryByRole('button', { name: '运营' })).not.toBeInTheDocument()
    expect(screen.getAllByText('成本判断').some(node => node.closest('label'))).toBe(true)
    expect(screen.getAllByText('运营').some(node => node.closest('label'))).toBe(true)
    expect(screen.getAllByText('页面类型').some(node => node.closest('label'))).toBe(true)

    fireEvent.change(screen.getAllByText('成本判断').find(node => node.closest('label'))!.closest('label')!.querySelector('select')!, { target: { value: '冷启动期' } })
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => decodeURIComponent(String(input)).includes('cost_statuses=冷启动期'))).toBe(true))
    fireEvent.click(within(table).getByRole('button', { name: '展现' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes('sort_by=impressions'))).toBe(true))
    fireEvent.click(within(table).getByRole('button', { name: '筛选账户管家' }))
    fireEvent.click(screen.getByRole('checkbox', { name: '全选账户管家' }))
    fireEvent.click(screen.getByRole('checkbox', { name: '管家甲' }))
    fireEvent.click(screen.getByRole('button', { name: '应用' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes('manager_ids=m1'))).toBe(true))
  })
})
