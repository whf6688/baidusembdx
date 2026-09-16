import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ExecutionRecordsPage } from '../src/App'
import type { TaskRow } from '../src/types'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('automatic strategy execution records', () => {
  it('uses the ecommerce audit-table structure without legacy cards or duplicate headings', async () => {
    const task: TaskRow = {
      id: '12345678-aaaa-bbbb-cccc-123456789012', task_type: 'budget_append_automation', status: 'succeeded', current_node: 'budget_append_complete', progress: 100,
      retry_count: 0, result_summary: '已完成预算追加', account_name: '测试账户', account_id: 87654321, manager_login_name: 'BDCC-测试管家', can_resume: false,
      created_at: '2026-09-16T08:00:00Z', updated_at: '2026-09-16T08:03:00Z',
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const data = String(input).endsWith('/ad-builds') ? [] : [task]
      return new Response(JSON.stringify({ request_id: 'test', status: 'ok', data }), { status: 200, headers: { 'content-type': 'application/json' } })
    }))
    render(<ExecutionRecordsPage project={{ id: 'p1', name: '减肥搜索', code: 'jfsem', enabled: true, manager_count: 1, account_count: 1 }} initialTasks={[task]} strategyScope="budget_append" />)
    await waitFor(() => expect(screen.getByText('测试账户')).toBeInTheDocument())
    expect(screen.queryByRole('heading', { name: '执行记录' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '执行记录汇总' })).not.toBeInTheDocument()
    const statusFilters = screen.getByRole('group', { name: '执行状态筛选' })
    expect(within(statusFilters).getAllByRole('button').map(button => button.textContent)).toEqual(['全部1', '进行中0', '等待0', '已完成1', '异常0'])
    expect(screen.getByRole('searchbox', { name: '搜索自动策略执行记录' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新' })).toBeInTheDocument()
    expect(screen.getAllByRole('columnheader').map(cell => cell.textContent)).toEqual(['执行时间', '任务ID', '执行动作', '账户名称', '账户ID', '账户管家', '当前步骤', '进度', '重试次数', '状态', '执行结果', '完成时间', '操作'])
    const row = screen.getByText('测试账户').closest('tr')
    expect(row).not.toBeNull()
    expect(within(row!).getAllByRole('cell').map(cell => cell.textContent)).toEqual([
      '09/16 16:00', '12345678', '预算追加', '测试账户', '87654321', 'BDCC-测试管家',
      '预算追加完成', '100%', '0', '已完成', '已完成预算追加', '09/16 16:03', '—',
    ])
    expect(screen.getByText('已完成预算追加')).toBeInTheDocument()
    expect(screen.getByLabelText('自动策略执行记录分页')).toBeInTheDocument()
  })
})
