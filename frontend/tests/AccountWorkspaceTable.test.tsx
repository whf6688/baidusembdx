import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccountWorkspaceTable } from '../src/features/accounts/AccountWorkspaceTable'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('AccountWorkspaceTable', () => {
  it('matches the ecommerce manager columns and uses the recharge account balance', () => {
    render(<AccountWorkspaceTable
      project={{ id: 'p1', name: '减肥搜索', code: 'search', enabled: true, account_count: 1, manager_count: 1 }}
      managers={[{ id: 'm1', project_id: 'p1', login_name: '测试管家', auth_status: 'authorized', is_active: true, account_count: 9, balance: '1888.50', balance_account_name: '初始账户01', rebate_rate: '51.00', balance_warning_threshold: '2000.00', balance_warning_active: true, recharge_account: '钱柜账户01' }]}
    />)
    expect(screen.getAllByRole('columnheader').map(cell => cell.textContent)).toEqual(['类型', '账户', '账户余额', '余额预警', '返点', '授权', '操作', '充值账户'])
    expect(screen.getByText('1,888.50')).toHaveAttribute('title', '充值账户：初始账户01')
    expect(screen.getByText('¥ 2,000.00')).toBeInTheDocument()
    expect(screen.getByText('51%')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: '修改' })).toHaveLength(2)
    expect(screen.getByText('钱柜账户01')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '同步账号主体' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新余额' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '删除管家' })).toBeInTheDocument()
  })

  it('confirms manager archival while explaining that history is retained', async () => {
    const onArchiveManager = vi.fn(async () => undefined)
    render(<AccountWorkspaceTable
      project={{ id: 'p1', name: '减肥搜索', code: 'search', enabled: true, account_count: 1, manager_count: 1 }}
      managers={[{ id: 'm1', project_id: 'p1', login_name: '测试管家', auth_status: 'authorized', is_active: true, account_count: 9 }]}
      onArchiveManager={onArchiveManager}
    />)
    fireEvent.click(screen.getByRole('button', { name: '删除管家' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('全部存档保留')
    fireEvent.click(screen.getByRole('button', { name: '确认删除并存档' }))
    await waitFor(() => expect(onArchiveManager).toHaveBeenCalledWith(expect.objectContaining({ id: 'm1' })))
  })

  it('uses spend-descending order and exposes required account metrics', async () => {
    const onConfirmCampaignState = vi.fn()
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const data = url.includes('/facets') ? { subjects: [], operators: [], account_types: ['搜索'], page_types: [], account_names: ['测试账户'], managers: [] } : url.includes('/account-selection') ? { account_ids: ['a1', 'a2'], total: 2 } : url.includes('/accounts/a1/ocpc-projects') ? {
        account_id: 'a1', account_name: '测试账户', cache_status: 'succeeded', cache_synced_at: '2026-09-13T03:00:00Z',
        rows: [{ id: 'o1', ocpc_project_id: 99001, ocpc_project_name: '测试 oCPC 项目', ocpc_bid: '128.00', bid_type: 1, remote_status: 1, scope: [{ levelId: 88001 }], last_seen_at: '2026-09-13T03:00:00Z' }],
      } : {
        date_from: '2026-09-13', date_to: '2026-09-13', page: 1, page_size: 20, total_pages: 1, total: 1,
        summary: { account_count: 1, impressions: 10000, clicks: 320, spend: '88.80', uv: 210, copies: 40, adds: 2, cpc: '0.28', uv_cost: '0.42', copy_cost: '2.22', add_cost: '44.40', cash_spend: '59.20', cash_add_cost: '29.60' }, lifecycle_counts: { '空账户': 0, '测试期': 1 }, watermark: '2026-09-13T02:00:00Z',
        rows: [{ id: 'a1', account_id: 123, account_name: '测试账户', subject: '测试主体', remote_status_code: 2, remote_status_text: '正常生效', lifecycle: '测试期', manager_name: '测试管家', operator_name: '王康', account_type: '搜索', page_type: '二跳', rebate_rate: '50', spend: '88.80', adds: 2, add_cost: '44.40', cash_add_cost: '29.60', impressions: 10000, clicks: 320, cpm: '8.88', ctr: '3.20', uv: 0, copies: 0, budget: '100.00', balance: '500.00', permission_status: '正常', is_active: true, data_watermark: '2026-09-13T02:00:00Z' }],
      }
      return new Response(JSON.stringify({ request_id: 'test', status: 'ok', data }), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<AccountWorkspaceTable
      mode="operations"
      project={{ id: 'p1', name: '减肥搜索', code: 'search', enabled: true, account_count: 1, manager_count: 1 }}
      managers={[{ id: 'm1', project_id: 'p1', login_name: '测试管家', auth_status: 'authorized', is_active: true, account_count: 1 }]}
      onConfirmCampaignState={onConfirmCampaignState}
    />)
    await waitFor(() => expect(screen.getByText('测试账户')).toBeInTheDocument())
    const overview = screen.getByRole('region', { name: '账户列表概览' })
    expect(within(overview).getByText('展现')).toBeInTheDocument()
    expect(within(overview).getByText('现金加粉成本')).toBeInTheDocument()
    expect(within(overview).getByText('¥ 59.20')).toBeInTheDocument()
    expect(within(overview).getByText('¥ 29.60')).toBeInTheDocument()
    expect(screen.getAllByRole('columnheader').map(cell => cell.textContent)).toEqual([
      '', '状态', '生命周期', '运营', '账户管家', '账户类型', '页面类型', '账户名称', '账户ID',
      '日预算', '展现', '点击', '消费↓', '加粉', 'CPM', 'CTR', '账户加粉成本', '现金加粉成本',
    ])
    const accountTable = screen.getByRole('table')
    expect(within(accountTable).getByText('¥ 44.40')).toBeInTheDocument()
    expect(within(accountTable).getByText('¥ 29.60')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('sort_by=spend') && String(input).includes('sort_order=desc'))).toBe(true)
    expect(screen.queryByText('账户余额')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: '选择全部筛选结果' }))
    expect(screen.getByRole('button', { name: '批量时段（2）' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '批量启动（2）' }))
    expect(onConfirmCampaignState).toHaveBeenLastCalledWith(['a1', 'a2'], false)
    fireEvent.click(screen.getByRole('button', { name: '批量暂停（2）' }))
    expect(onConfirmCampaignState).toHaveBeenLastCalledWith(['a1', 'a2'], true)
    expect(screen.queryByRole('button', { name: /批量启停/ })).not.toBeInTheDocument()
    expect(['状态', '生命周期', '运营', '账户管家', '账户类型', '页面类型', '账户名称'].map(label => screen.getByRole('button', { name: `筛选${label}` }))).toHaveLength(7)
    fireEvent.click(screen.getByRole('button', { name: '筛选生命周期' }))
    expect(screen.getByRole('group', { name: '生命周期筛选' })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: '全选生命周期' })).toBeChecked()
    fireEvent.click(screen.getByRole('checkbox', { name: '全选生命周期' }))
    fireEvent.change(screen.getByPlaceholderText('搜索生命周期'), { target: { value: '测试' } })
    fireEvent.click(screen.getByRole('checkbox', { name: '测试期' }))
    fireEvent.change(screen.getByPlaceholderText('搜索生命周期'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('checkbox', { name: '空账户' }))
    fireEvent.click(screen.getByRole('button', { name: '应用' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes('lifecycles=') && decodeURIComponent(String(input)).includes('测试期,空账户'))).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: '测试账户' }))
    await waitFor(() => expect(screen.getByText('测试 oCPC 项目')).toBeInTheDocument())
    expect(screen.getByText('目标转化成本')).toBeInTheDocument()
    expect(screen.getByText('绑定 1 个计划：88001')).toBeInTheDocument()
  })
})
