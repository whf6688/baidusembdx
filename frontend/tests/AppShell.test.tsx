import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppSidebar } from '../src/components/AppShell'

afterEach(cleanup)

describe('AppSidebar', () => {
  it('marks only the account-management text when a manager balance is below its threshold', () => {
    render(<AppSidebar
      groups={[{ group: '项目与账户', items: [
        { id: 'accounts', label: '账户管理', shortLabel: '管' },
        { id: 'account-list', label: '账户列表', shortLabel: '列' },
      ] }]}
      isProjectWorkspace
      page="accounts"
      runtimeNeedsAttention={false}
      accountBalanceWarning
      onHome={vi.fn()}
      onOpenRuntimeStatus={vi.fn()}
      onSelect={vi.fn()}
      username="测试用户"
      onLogout={vi.fn()}
    />)

    const accounts = screen.getByRole('button', { name: '账户管理' })
    expect(accounts).toHaveClass('active', 'has-balance-warning')
    expect(screen.getByRole('button', { name: '账户列表' })).not.toHaveClass('has-balance-warning')
  })
})
