import type { ReactNode } from 'react'

export type SidebarItem = {
  id: string
  label: string
  shortLabel: string
}

export type SidebarGroup = {
  group: string
  items: SidebarItem[]
}

type Props = {
  groups: SidebarGroup[]
  isProjectWorkspace: boolean
  onHome: () => void
  onOpenRuntimeStatus: () => void
  onSelect: (id: string) => void
  page: string
  runtimeNeedsAttention: boolean
  accountBalanceWarning: boolean
  username: string
  onLogout: () => void
}

/** The stable shell navigation shared by the project directory and every workspace. */
export function AppSidebar({ groups, isProjectWorkspace, onHome, onOpenRuntimeStatus, onSelect, page, runtimeNeedsAttention, accountBalanceWarning, username, onLogout }: Props) {
  return <aside className="sidebar">
    <button type="button" className="brand" onClick={onHome} aria-label="打开项目管理">
      <span className="brand-mark" aria-hidden="true">百</span>
      <span className="brand-copy"><strong>百度搜索信息流</strong><span>投放管理平台</span></span>
    </button>
    <nav aria-label="主导航">
      {groups.map(group => <div className="nav-group" key={group.group}><span className="nav-label">{group.group}</span>{group.items.map(item => {
        const active = isProjectWorkspace && page === item.id
        const balanceWarning = item.id === 'accounts' && accountBalanceWarning
        return <button key={item.id} type="button" title={item.label} className={`nav-item${active ? ' active' : ''}${balanceWarning ? ' has-balance-warning' : ''}`} onClick={() => onSelect(item.id)} aria-current={active ? 'page' : undefined}>{item.label}</button>
      })}</div>)}
    </nav>
    <div className="sidebar-foot">
      <button type="button" className={`runtime-status ${runtimeNeedsAttention ? 'needs-attention' : 'is-normal'}`} onClick={onOpenRuntimeStatus}>{runtimeNeedsAttention ? '需要处理' : '运行中'}</button>
      <div className="sidebar-session">
        <span title={username}>当前账号 · {username}</span>
        <button type="button" onClick={onLogout}><strong>退出账号</strong><small>切换登录</small></button>
      </div>
    </div>
  </aside>
}
