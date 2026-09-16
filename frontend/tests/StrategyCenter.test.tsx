import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StrategyCenter } from '../src/features/strategies/StrategyCenter'

const version = { id: 'v1', version: 1, status: 'published', base_version_id: null, draft_revision: 1, config: { target_budget: '50.00', schedule_times: ['00:00'] }, config_hash: 'hash', created_by: 'system', published_by: 'system', created_at: '2026-09-13T00:00:00Z', published_at: '2026-09-13T00:00:00Z' }
const roundAmounts = Array.from({ length: 10 }, (_, index) => ({ round: index + 1, amount: `${(index + 1) * 10}.00` }))
const policies = [
  { key: 'budget_reset', revision: 1, active: version, draft: null },
  { key: 'budget_append', revision: 1, active: { ...version, id: 'v2', config: { round_amounts: roundAmounts, add_cost_limit: '100.00', utilization_limit: '0.8', schedule_times: ['01:30'] } }, draft: null },
  { key: 'elimination', revision: 1, active: { ...version, id: 'v3', config: { spend_without_add_limit: '100.00', add_cost_limit: '120.00', schedule_times: ['23:20'] } }, draft: null },
  { key: 'account_status', revision: 1, active: { ...version, id: 'v-account-status', config: { rules_version: 'account-status-v1' } }, draft: null },
  { key: 'cost_judgment', revision: 1, active: { ...version, id: 'v-cost-judgment', config: { mode: 'add_cash', add_cash: { cold_start_spend_limit: '100.00', cost_limit: '120.00' }, copy_cash: { cold_start_spend_limit: '90.00', cost_limit: '88.00' } } }, draft: { ...version, id: 'v-cost-judgment-draft', status: 'draft', config: { mode: 'copy_cash', add_cash: { cold_start_spend_limit: '100.00', cost_limit: '120.00' }, copy_cash: { cold_start_spend_limit: '90.00', cost_limit: '88.00' } } } },
  { key: 'realtime_closure', revision: 1, active: { ...version, id: 'v-realtime-closure', config: { refresh_interval_minutes: 15, failure_protection_enabled: true } }, draft: null },
  { key: 'keyword_tiers', revision: 1, active: { ...version, id: 'v4', config: { a_add_cost_max: '110', b_next_add_cost_max: '100', c_add_growth_factor: '1.2', c_projected_cost_max: '120', empty_spend_min: '70', d_spend_min: '10' } }, draft: null },
]
const buildSettings = {
  items: [{ campaign_name: 'A成本', keyword_count: 2217, repeat_count: 5, is_configured: true }],
  plan_count: 1,
  has_draft: false,
  has_published: true,
  updated_by: 'system',
  updated_at: '2026-09-16T00:00:00Z',
}

afterEach(() => {
  cleanup()
  window.history.replaceState({}, '', '/')
  vi.unstubAllGlobals()
})

describe('StrategyCenter', () => {
  it('groups the supported automation actions and omits keyword tiers', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const data = url.endsWith('/ad-build-plan-settings') ? buildSettings : url.endsWith('/versions') ? [version] : policies
      return new Response(JSON.stringify({ request_id: 'test', status: 'ok', data }), { status: 200, headers: { 'content-type': 'application/json' } })
    }))
    render(<StrategyCenter project={{ id: 'p1', name: '减肥搜索', code: 'search', enabled: true, account_count: 1 }} />)
    await waitFor(() => expect(screen.getByRole('region', { name: '搭建设置工作区' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: '预算追加' }))
    await waitFor(() => expect(screen.getByDisplayValue('50.00')).toBeInTheDocument())
    expect(screen.getByText('实时调整')).toBeInTheDocument()
    expect(screen.getByText('周期调整')).toBeInTheDocument()
    expect(screen.getByText('全局判定')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '预算追加' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '预算重置' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '账户淘汰' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '实时闭环' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '关键词分级' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '实时闭环' }))
    const loopWorkspace = screen.getByRole('region', { name: '实时闭环工作区' })
    expect(loopWorkspace).toHaveClass('is-loop-workspace')
    expect(within(loopWorkspace).getByRole('tab', { name: '规则设置' })).toHaveAttribute('aria-selected', 'true')
    expect(within(loopWorkspace).queryByRole('tab', { name: '闭环总览' })).not.toBeInTheDocument()
    expect(within(loopWorkspace).getByRole('combobox', { name: '执行模式' })).toHaveValue('自动判定')
    expect(within(loopWorkspace).getByRole('combobox', { name: '执行周期' })).toHaveValue('实时闭环')
    fireEvent.click(screen.getByRole('button', { name: '预算追加' }))
    const roundHeading = screen.getByRole('heading', { name: '追加轮次' })
    const triggerHeading = screen.getByRole('heading', { name: '触发条件' })
    expect(roundHeading).toBeInTheDocument()
    expect(triggerHeading).toBeInTheDocument()
    expect(roundHeading.parentElement).toHaveClass('strategy-inline-heading')
    expect(triggerHeading.parentElement).toHaveClass('strategy-inline-heading')
    expect(screen.getByLabelText('复制现金成本合格线')).toHaveTextContent('88.00元')
    expect(screen.getByText('跟随已保存的成本判断草稿')).toBeInTheDocument()
    expect(screen.getByLabelText('预算利用率')).toHaveValue(80)
    expect(screen.getByLabelText('第 1 轮追加金额')).toHaveValue(10)
    expect(screen.getByLabelText('第 10 轮及以上追加金额')).toHaveValue(100)
    const roundAmountsTable = screen.getByRole('table', { name: '追加轮次金额' })
    expect(within(roundAmountsTable).getAllByText('账户币')).toHaveLength(10)
    expect(within(roundAmountsTable).queryByText('元')).not.toBeInTheDocument()
    expect(screen.queryByText(/售价阶段/)).not.toBeInTheDocument()
    expect(screen.queryByText(/倍数/)).not.toBeInTheDocument()
    expect(screen.queryByText('规则参数')).not.toBeInTheDocument()
    expect(screen.queryByText('编辑只会保存为草稿，必须经过试运行后才能发布')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '恢复当前内容' })).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: '执行周期' })).toHaveValue('每小时评估')
    expect(screen.queryByText('执行时间', { exact: true })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '增加时间' })).not.toBeInTheDocument()
    expect(screen.queryByText('时间按北京时间执行；默认设置与重构前完全一致')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '校验参数' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '保存草稿' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '试运行' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '发布', exact: true })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '发布规则' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '预算重置' }))
    expect(screen.getByRole('tab', { name: '执行失败记录' })).toBeInTheDocument()
    const resetWorkspace = screen.getByRole('region', { name: '预算重置工作区' })
    const reset = within(resetWorkspace)
    expect(reset.getByRole('heading', { name: '触发条件' })).toBeInTheDocument()
    expect(reset.getByText(/计划全停、预算不足或上线/)).toBeInTheDocument()
    expect(reset.queryByText('冷启动期')).not.toBeInTheDocument()
    expect(reset.queryByText(/预算快照/)).not.toBeInTheDocument()
    expect(reset.getByLabelText('预算重置执行时间')).toHaveValue('00:00')
    expect(reset.getByLabelText('初始预算')).toHaveValue(50)
    expect(reset.getByLabelText('预算重置最小差额')).toHaveValue(0.01)
    expect(reset.getByLabelText('预算重置失败重试次数')).toHaveValue(3)
    expect(reset.getByLabelText('预算重置重试间隔')).toHaveValue(60)
  })

  it('prepares an edited rule for publishing from the top release button', async () => {
    const nextPolicy = {
      ...policies[1],
      revision: 2,
      draft: {
        ...policies[1].active,
        id: 'draft-v3',
        version: 3,
        status: 'draft',
        config: {
          ...policies[1].active.config,
          utilization_limit: '0.85',
          round_amounts: roundAmounts.map((item, index) => index === 0 ? { ...item, amount: '11.00' } : item),
        },
      },
    }
    const strategyFetch = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      let data: unknown = policies
      if (url.endsWith('/ad-build-plan-settings')) data = buildSettings
      if (url.endsWith('/versions')) data = [version]
      if (url.endsWith('/draft')) data = nextPolicy
      if (url.endsWith('/dry-run')) {
        data = {
          id: 'evaluation-1',
          config_hash: 'draft-hash',
          created_at: '2026-09-16T00:00:00Z',
          result: { candidate_count: 2, action: '按轮次追加金额' },
        }
      }
      return new Response(JSON.stringify({ request_id: 'test', status: 'ok', data }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', strategyFetch)

    render(<StrategyCenter project={{ id: 'p1', name: '减肥搜索', code: 'search', enabled: true, account_count: 1 }} />)
    await waitFor(() => expect(screen.getByRole('region', { name: '搭建设置工作区' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: '预算追加' }))
    await waitFor(() => expect(screen.getByLabelText('第 1 轮追加金额')).toHaveValue(10))
    fireEvent.click(screen.getByRole('button', { name: '编辑规则' }))
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存规则' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('第 1 轮追加金额'), { target: { value: '11.00' } })
    fireEvent.change(screen.getByLabelText('预算利用率'), { target: { value: '85' } })
    const save = screen.getByRole('button', { name: '保存规则' })
    await waitFor(() => expect(save).toBeEnabled())
    const release = screen.getByRole('button', { name: '发布规则' })
    expect(release).toBeDisabled()
    fireEvent.click(save)

    await waitFor(() => expect(screen.getByRole('button', { name: '编辑规则' })).toBeInTheDocument())
    expect(screen.getByText(/规则已保存为草稿/)).toBeInTheDocument()
    await waitFor(() => expect(release).toBeEnabled())
    fireEvent.click(release)

    await waitFor(() => expect(screen.getByRole('dialog', { name: /确认发布预算追加/ })).toBeInTheDocument())
    const draftCall = strategyFetch.mock.calls.find(([input]) => String(input).endsWith('/draft'))
    expect(draftCall).toBeDefined()
    expect(JSON.parse(String(draftCall?.[1]?.body)).config.utilization_limit).toBe('0.85')
    expect(strategyFetch.mock.calls.some(([input]) => String(input).endsWith('/dry-run'))).toBe(true)
  })

  it('opens the first action initially and restores the last action and pane after refresh', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const data = url.endsWith('/ad-build-plan-settings') ? buildSettings : policies
      return new Response(JSON.stringify({ request_id: 'test', status: 'ok', data }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }))

    const project = { id: 'persist-project', name: '减肥搜索', code: 'search', enabled: true, account_count: 1 }
    const records = () => <div>已恢复执行记录</div>
    render(<StrategyCenter project={project} renderRecords={records} />)
    await waitFor(() => expect(screen.getByRole('region', { name: '搭建设置工作区' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: '搭建设置' })).toHaveAttribute('aria-current', 'page')

    fireEvent.click(screen.getByRole('button', { name: '预算重置' }))
    fireEvent.click(await screen.findByRole('tab', { name: '执行失败记录' }))
    await waitFor(() => expect(screen.getByText('已恢复执行记录')).toBeInTheDocument())

    cleanup()
    render(<StrategyCenter project={project} renderRecords={records} />)
    await waitFor(() => expect(screen.getByRole('region', { name: '预算重置工作区' })).toBeInTheDocument())
    expect(screen.getByRole('tab', { name: '执行失败记录' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('已恢复执行记录')).toBeInTheDocument()
  })

  it('supports read-save, edit-save, and re-read-save for build settings', async () => {
    let repeatCount = 5
    let hasDraft = false
    const buildSettings = () => ({
      items: [{ campaign_name: 'A成本', keyword_count: 2217, repeat_count: repeatCount, is_configured: hasDraft }],
      plan_count: 1,
      has_draft: hasDraft,
      has_published: true,
      updated_by: hasDraft ? 'operator' : null,
      updated_at: hasDraft ? '2026-09-16T00:00:00Z' : null,
    })
    const strategyFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      let data: unknown = policies
      if (url.endsWith('/versions')) data = [version]
      if (url.endsWith('/ad-build-plan-settings/material-plans')) {
        data = buildSettings()
      } else if (url.endsWith('/ad-build-plan-settings')) {
        if (init?.method === 'PUT') {
          const body = JSON.parse(String(init.body)) as { plans: Array<{ repeat_count: number }> }
          repeatCount = body.plans[0].repeat_count
          hasDraft = true
        }
        data = buildSettings()
      }
      return new Response(JSON.stringify({ request_id: 'test', status: 'ok', data }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', strategyFetch)

    render(<StrategyCenter project={{ id: 'p1', name: '减肥搜索', code: 'search', enabled: true, account_count: 1 }} />)
    await waitFor(() => expect(screen.getByRole('button', { name: '搭建设置' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: '搭建设置' }))

    const repeatInput = await screen.findByLabelText('A成本单元重复次数')
    expect(repeatInput).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '编辑规则' }))
    fireEvent.change(screen.getByLabelText('A成本单元重复次数'), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: '保存规则' }))
    await waitFor(() => expect(screen.getByLabelText('A成本单元重复次数')).toHaveValue(4))
    expect(screen.getByLabelText('A成本单元重复次数')).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '编辑规则' }))
    fireEvent.click(screen.getByRole('button', { name: '读取物料中心计划' }))
    await waitFor(() => expect(screen.getByLabelText('A成本单元重复次数')).toBeEnabled())
    fireEvent.change(screen.getByLabelText('A成本单元重复次数'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: '保存规则' }))

    await waitFor(() => expect(screen.getByLabelText('A成本单元重复次数')).toHaveValue(3))
    expect(screen.getByLabelText('A成本单元重复次数')).toBeDisabled()
    expect(screen.getByRole('button', { name: '编辑规则' })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: '编辑规则' }))
    fireEvent.click(screen.getByRole('button', { name: '读取物料中心计划' }))
    await waitFor(() => expect(screen.getByLabelText('A成本单元重复次数')).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '保存规则' }))

    await waitFor(() => {
      const saveCalls = strategyFetch.mock.calls.filter(([input, init]) =>
        String(input).endsWith('/ad-build-plan-settings') && init?.method === 'PUT')
      expect(saveCalls).toHaveLength(3)
    })
    expect(screen.getByLabelText('A成本单元重复次数')).toHaveValue(3)
  })
})
