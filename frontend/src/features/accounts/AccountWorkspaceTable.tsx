import { Fragment, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  Input,
  Skeleton,
  SkeletonItem,
} from '@fluentui/react-components'
import { apiGet, apiPost } from '../../api'
import { PopupMessage } from '../../components/PopupMessage'
import { DialogTitleWithSummary } from '../../components/DialogTitleWithSummary'
import { DateFilterGroup } from '../../components/DateFilterGroup'
import { SearchField } from '../../components/SearchField'
import { TableColumnFilter } from '../../components/TableColumnFilter'
import type { TableColumnFilterConfig } from '../../components/TableColumnFilter'
import { ViewportStickyPagination } from '../../components/ViewportStickyPagination'
import { moveHorizontalTab } from '../../components/tabNavigation'
import { getUiTimeZone } from '../../uiTimeZone'
import type { AccountOcpcProjectList, AccountManagement, AccountManagementRow, AccountManager, AccountWorkspace, AccountWorkspaceFacets, AccountWorkspaceRow, Project } from '../../types'

type Props = {
  mode?: 'management' | 'operations'; project: Project; managers?: AccountManager[]
  onAddManager?: () => void; onOpenCustomIdSettings?: () => void; onOpenCustomIdList?: () => void
  onOpenCampaignSchedule?: (ids: string[]) => void; onConfirmCampaignState?: (ids: string[], paused: boolean) => void
  onOpenBatchSettings?: (ids: string[]) => void
  onAuthorizeManager?: (manager: AccountManager) => void; onAuthorizeAccount?: (account: AccountManagementRow) => void
  onSyncManagerAccounts?: (manager: AccountManager) => void; onRefreshManagerBalance?: (manager: AccountManager) => void
  onSetManagerActive?: (manager: AccountManager, isActive: boolean) => Promise<boolean>
  onUpdateManagerSettings?: (manager: AccountManager, changes: { rebate_rate?: number; balance_warning_threshold?: number | null }) => Promise<boolean>
  onArchiveManager?: (manager: AccountManager) => Promise<void>
  oauthBusyId?: string | null; syncBusyId?: string | null; balanceBusyId?: string | null; statusBusyId?: string | null; settingsBusyId?: string | null; archiveBusyId?: string | null
  canManage?: boolean
}

const dateValue = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
const money = (value?: string | null) => value == null ? '—' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const overviewMoney = (value?: string | null) => value == null ? '—' : `¥ ${money(value)}`
const count = (value?: number | null) => Number(value || 0).toLocaleString('zh-CN')
const authorized = (value?: string | null) => ['authorized', 'granted'].includes(value || '')
const formatDateTime = (value?: string | null) => value ? new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: getUiTimeZone() }).format(new Date(value)) : '—'
const ocpcStatusText = (value?: number | null) => value == null ? '未同步' : ({ 0: '未生效', 1: '投放中', 2: '投放中（学习中）', 3: '投放中（学习失败）', 4: '投放中（学习结束）' } as Record<number, string>)[value] || `状态 ${value}`
const ocpcBidTypeText = (value?: number | null) => value === 1 ? '目标转化成本' : value === 2 ? '增强模式' : '—'
const ocpcScopeText = (scope: Array<Record<string, unknown>> = []) => {
  const ids = scope.map(item => item.levelId).filter(value => value != null).map(String)
  return ids.length ? `绑定 ${ids.length} 个计划：${ids.join('、')}` : '未绑定计划'
}
const filterValues = (value: string) => value ? value.split(',').filter(Boolean) : []
const toolbarFilterValue = (value: string) => filterValues(value).length === 1 ? filterValues(value)[0] : ''

export function AccountWorkspaceTable(props: Props) {
  const { mode = 'management', project, managers = [], canManage = true } = props
  const today = dateValue(new Date())
  const [dateFrom, setDateFrom] = useState(today), [dateTo, setDateTo] = useState(today)
  const [activeTab, setActiveTab] = useState('managers'), [managerFilter, setManagerFilter] = useState('')
  const [accountStatus, setAccountStatus] = useState(() => mode === 'operations' ? 'current' : '')
  const [costStatus, setCostStatus] = useState(''), [operator, setOperator] = useState('')
  const [accountType, setAccountType] = useState(''), [pageType, setPageType] = useState('')
  const [accountNames, setAccountNames] = useState('')
  const [remoteStatus, setRemoteStatus] = useState(''), [authorizationStatus, setAuthorizationStatus] = useState('')
  const [page, setPage] = useState(1), [pageSize, setPageSize] = useState(20)
  const [managerPage, setManagerPage] = useState(1), [managerPageSize, setManagerPageSize] = useState(20)
  const [searchInput, setSearchInput] = useState(''), [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState(() => mode === 'operations' ? 'default' : 'account_id'), [sortOrder, setSortOrder] = useState<'asc' | 'desc'>(() => mode === 'operations' ? 'desc' : 'asc')
  const [workspace, setWorkspace] = useState<AccountWorkspace | null>(null)
  const [management, setManagement] = useState<AccountManagement | null>(null)
  const [facets, setFacets] = useState<AccountWorkspaceFacets | null>(null)
  const [loading, setLoading] = useState(true), [error, setError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0), [selected, setSelected] = useState<Set<string>>(new Set())
  const [selectionOrder, setSelectionOrder] = useState<string[]>([]), [lastSelected, setLastSelected] = useState<string | null>(null)
  const [archiveTarget, setArchiveTarget] = useState<AccountManager | null>(null)
  const [pauseTarget, setPauseTarget] = useState<AccountManager | null>(null)
  const [managerEditTarget, setManagerEditTarget] = useState<AccountManager | null>(null)
  const [managerEditKind, setManagerEditKind] = useState<'balance_warning_threshold' | 'rebate_rate'>('balance_warning_threshold')
  const [managerEditValue, setManagerEditValue] = useState('')
  const [managerEditError, setManagerEditError] = useState<string | null>(null)
  const [expandedAccountId, setExpandedAccountId] = useState<string | null>(null)
  const [ocpcDetails, setOcpcDetails] = useState<Record<string, AccountOcpcProjectList>>({})
  const [ocpcLoadingId, setOcpcLoadingId] = useState<string | null>(null)
  const [ocpcErrors, setOcpcErrors] = useState<Record<string, string>>({})
  const [retirementTarget, setRetirementTarget] = useState<AccountWorkspaceRow | null>(null)
  const [retirementBusy, setRetirementBusy] = useState(false)
  const [retirementError, setRetirementError] = useState<string | null>(null)
  const [retirementNotice, setRetirementNotice] = useState<{ accountId: string; text: string } | null>(null)
  const [retirementTask, setRetirementTask] = useState<{ taskId: string; accountId: string; accountName: string } | null>(null)
  const managerId = mode === 'management' ? (activeTab === 'managers' ? '' : activeTab) : managerFilter
  const showingManagers = mode === 'management' && activeTab === 'managers'
  const managerTabIds = ['managers', ...managers.map(item => item.id)]

  useEffect(() => {
    if (mode === 'management' && activeTab !== 'managers' && !managers.some(item => item.id === activeTab)) setActiveTab('managers')
  }, [activeTab, managers, mode])
  useEffect(() => { setRetirementTask(null) }, [project.id])
  const query = useMemo(() => {
    const q = new URLSearchParams({ page: String(page), page_size: String(pageSize), sort_by: sortBy, sort_order: sortOrder })
    const effectiveSearch = mode === 'management' && accountNames ? accountNames : search
    if (effectiveSearch) q.set('search', effectiveSearch)
    if (mode === 'operations') {
      q.set('date_from', dateFrom); q.set('date_to', dateTo)
      if (managerId) q.set('manager_ids', managerId); if (operator) q.set('operator_names', operator)
      if (accountType) q.set('account_types', accountType); if (pageType) q.set('page_types', pageType)
      if (accountStatus) q.set('account_statuses', accountStatus); if (costStatus) q.set('cost_statuses', costStatus); if (accountNames) q.set('account_names', accountNames)
    } else {
      if (managerId) q.set('manager_id', managerId); if (operator) q.set('operator_name', operator)
      if (accountType) q.set('account_type', accountType); if (pageType) q.set('page_type', pageType)
      if (remoteStatus) q.set('remote_status', remoteStatus); if (authorizationStatus) q.set('authorization_status', authorizationStatus)
    }
    return q.toString()
  }, [page, pageSize, sortBy, sortOrder, managerId, operator, accountType, pageType, accountNames, search, mode, dateFrom, dateTo, accountStatus, costStatus, remoteStatus, authorizationStatus])
  const selectionQuery = useMemo(() => {
    const q = new URLSearchParams()
    const effectiveSearch = mode === 'management' && accountNames ? accountNames : search
    if (effectiveSearch) q.set('search', effectiveSearch)
    if (mode === 'operations') {
      if (managerId) q.set('manager_ids', managerId); if (operator) q.set('operator_names', operator)
      if (accountType) q.set('account_types', accountType); if (pageType) q.set('page_types', pageType)
      if (accountStatus) q.set('account_statuses', accountStatus); if (costStatus) q.set('cost_statuses', costStatus); if (accountNames) q.set('account_names', accountNames)
    } else {
      if (managerId) q.set('manager_id', managerId); if (operator) q.set('operator_name', operator)
      if (accountType) q.set('account_type', accountType); if (pageType) q.set('page_type', pageType)
      if (remoteStatus) q.set('remote_status', remoteStatus); if (authorizationStatus) q.set('authorization_status', authorizationStatus)
    }
    return q.toString()
  }, [managerId, operator, accountType, pageType, accountNames, search, mode, accountStatus, costStatus, remoteStatus, authorizationStatus])
  useEffect(() => {
    if (showingManagers) { setLoading(false); return }
    const controller = new AbortController(); setLoading(true)
    const resource = mode === 'management' ? 'account-management' : 'account-workspace'
    Promise.all([
      apiGet<AccountManagement | AccountWorkspace>(`/projects/${project.id}/${resource}?${query}`, controller.signal),
      facets ? Promise.resolve(facets) : apiGet<AccountWorkspaceFacets>(`/projects/${project.id}/account-workspace/facets`, controller.signal),
      apiGet<{ account_ids: string[] }>(`/projects/${project.id}/account-selection${selectionQuery ? `?${selectionQuery}` : ''}`, controller.signal),
    ]).then(([result, values, order]) => {
      mode === 'management' ? setManagement(result as AccountManagement) : setWorkspace(result as AccountWorkspace)
      setFacets(values); setSelectionOrder(order.account_ids); setError(null)
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '账户数据读取失败') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [project.id, query, refreshKey, mode, showingManagers])
  useEffect(() => { setPage(1); setSelected(new Set()); setLastSelected(null); setExpandedAccountId(null); setRetirementNotice(null) }, [project.id, activeTab, managerFilter, accountStatus, costStatus, search, operator, accountType, pageType, accountNames, remoteStatus, authorizationStatus, dateFrom, dateTo, mode])
  useEffect(() => {
    if (!retirementTask) return
    const timer = window.setInterval(() => {
      apiGet<{ status: string; last_error?: string | null }>(`/projects/${project.id}/tasks/${retirementTask.taskId}`)
        .then(task => {
          if (task.status === 'succeeded') {
            window.clearInterval(timer)
            setRetirementNotice({ accountId: retirementTask.accountId, text: `${retirementTask.accountName} 已完成淘汰，账户状态已更新为“已淘汰”` })
            setOcpcDetails(current => { const next = { ...current }; delete next[retirementTask.accountId]; return next })
            setRetirementTask(null)
            setRefreshKey(value => value + 1)
          } else if (task.status === 'failed' || task.status === 'blocked') {
            window.clearInterval(timer)
            setRetirementNotice({ accountId: retirementTask.accountId, text: task.last_error || `${retirementTask.accountName} 淘汰失败` })
            setRetirementTask(null)
          }
        })
        .catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [project.id, retirementTask])

  const rows = mode === 'management' ? management?.rows || [] : workspace?.rows || []
  const total = mode === 'management' ? management?.total || 0 : workspace?.total || 0
  const totalPages = mode === 'management' ? management?.total_pages || 1 : workspace?.total_pages || 1
  const pageIds = rows.map(row => row.id)
  const selectableIds = mode === 'operations' ? selectionOrder : pageIds
  const allPageSelected = Boolean(selectableIds.length && selectableIds.every(id => selected.has(id)))
  const togglePage = (checked: boolean) => setSelected(current => { const next = new Set(current); selectableIds.forEach(id => checked ? next.add(id) : next.delete(id)); return next })
  const toggleOne = (id: string, checked: boolean, shiftKey: boolean) => {
    setSelected(current => {
      const next = new Set(current), start = lastSelected ? selectionOrder.indexOf(lastSelected) : -1, end = selectionOrder.indexOf(id)
      const range = shiftKey && start >= 0 && end >= 0 ? selectionOrder.slice(Math.min(start, end), Math.max(start, end) + 1) : [id]
      range.forEach(value => checked ? next.add(value) : next.delete(value)); return next
    }); setLastSelected(id)
  }
  const changeSort = (key: string) => { if (sortBy === key) setSortOrder(v => v === 'asc' ? 'desc' : 'asc'); else { setSortBy(key); setSortOrder(key === 'account_id' ? 'asc' : 'desc') }; setPage(1) }
  const sortButton = (key: string, label: string) => <button type="button" className={sortBy === key ? 'data-sort is-active' : 'data-sort'} onClick={() => changeSort(key)}>{label}{sortBy === key ? <i>{sortOrder === 'asc' ? '↑' : '↓'}</i> : null}</button>
  const toggleAccountOcpcProjects = async (row: AccountWorkspaceRow) => {
    if (expandedAccountId === row.id) { setExpandedAccountId(null); return }
    setExpandedAccountId(row.id)
    if (ocpcDetails[row.id] || ocpcLoadingId === row.id) return
    setOcpcLoadingId(row.id)
    setOcpcErrors(current => { const next = { ...current }; delete next[row.id]; return next })
    try {
      const detail = await apiGet<AccountOcpcProjectList>(`/projects/${project.id}/accounts/${row.id}/ocpc-projects`)
      setOcpcDetails(current => ({ ...current, [row.id]: detail }))
    } catch (reason) {
      setOcpcErrors(current => ({ ...current, [row.id]: reason instanceof Error ? reason.message : 'oCPC 项目缓存读取失败' }))
    } finally {
      setOcpcLoadingId(current => current === row.id ? null : current)
    }
  }
  const filteredManagers = managers.filter(item => !search || [item.login_name, item.display_name].some(value => String(value || '').toLowerCase().includes(search.toLowerCase())))
  const managerTotalPages = Math.max(1, Math.ceil(filteredManagers.length / managerPageSize))
  const safeManagerPage = Math.min(managerPage, managerTotalPages)
  const pagedManagers = filteredManagers.slice((safeManagerPage - 1) * managerPageSize, safeManagerPage * managerPageSize)
  const isCopyJudgment = workspace?.cost_judgment?.mode === 'copy_cash'
  const overviewItems = workspace ? [
    ['impressions', '展现', count(workspace.summary.impressions)],
    ['clicks', '点击', count(workspace.summary.clicks)],
    ['spend', '消费', overviewMoney(workspace.summary.spend)],
    ['uv', 'UV', count(workspace.summary.uv)],
    [isCopyJudgment ? 'copies' : 'adds', isCopyJudgment ? '复制' : '加粉', count(isCopyJudgment ? workspace.summary.copies : workspace.summary.adds)],
    ['cpc', 'CPC', overviewMoney(workspace.summary.cpc)],
    ['uv_cost', 'UV成本', overviewMoney(workspace.summary.uv_cost)],
    [isCopyJudgment ? 'copy_cost' : 'add_cost', isCopyJudgment ? '账户复制成本' : '账户加粉成本', overviewMoney(isCopyJudgment ? workspace.summary.copy_cost : workspace.summary.add_cost)],
    ['cash_spend', '现金消费', overviewMoney(workspace.summary.cash_spend)],
    [isCopyJudgment ? 'cash_copy_cost' : 'cash_add_cost', isCopyJudgment ? '现金复制成本' : '现金加粉成本', overviewMoney(isCopyJudgment ? workspace.summary.cash_copy_cost : workspace.summary.cash_add_cost)],
  ] as const : []

  useEffect(() => { setManagerPage(1) }, [search, managers.length])

  const openManagerSetting = (manager: AccountManager, kind: 'balance_warning_threshold' | 'rebate_rate') => {
    setManagerEditTarget(manager)
    setManagerEditKind(kind)
    setManagerEditValue(String(manager[kind] ?? ''))
    setManagerEditError(null)
  }
  const saveManagerSetting = async () => {
    if (!managerEditTarget) return
    const trimmed = managerEditValue.trim()
    if (managerEditKind === 'rebate_rate' && !trimmed) {
      setManagerEditError('请输入 0–100 之间的返点')
      return
    }
    const value = trimmed ? Number(trimmed) : null
    const max = managerEditKind === 'rebate_rate' ? 100 : 999999999999
    if (value != null && (!Number.isFinite(value) || value < 0 || value > max)) {
      setManagerEditError(managerEditKind === 'rebate_rate' ? '返点需为 0–100 之间的数字' : '余额预警需为大于等于 0 的数字')
      return
    }
    const changes = managerEditKind === 'rebate_rate'
      ? { rebate_rate: value as number }
      : { balance_warning_threshold: value }
    if (await props.onUpdateManagerSettings?.(managerEditTarget, changes)) setManagerEditTarget(null)
  }

  const operationColumnFilters: OperationColumnFilters = {
    accountStatus: { label: '账户状态', value: accountStatus, options: [['current', '在用账户'], ...['未通过审核', '被禁用', '计划全停', '预算不足', '上线', '已淘汰', '待上线', '空账户'].map(item => [item, item])], onChange: setAccountStatus },
    costStatus: { label: '成本判断', value: costStatus, options: ['冷启动期', '空耗', '成本高', '成本上涨', '成本合格', '待判断'].map(item => [item, item]), onChange: setCostStatus },
    operator: { label: '运营', value: operator, options: (facets?.operators || []).map(item => [item, item]), onChange: setOperator },
    manager: { label: '账户管家', value: managerFilter, options: managers.map(item => [item.id, item.display_name || item.login_name]), onChange: setManagerFilter },
    accountType: { label: '账户类型', value: accountType, options: (facets?.account_types || []).map(item => [item, item]), onChange: setAccountType },
    pageType: { label: '页面类型', value: pageType, options: (facets?.page_types || []).map(item => [item, item]), onChange: setPageType },
    accountName: { label: '账户名称', value: accountNames, options: (facets?.account_names || []).map(item => [item, item]), onChange: setAccountNames },
  }
  const managementColumnFilters: ManagementColumnFilters = {
    accountName: { label: '账户', value: accountNames, options: (facets?.account_names || []).map(item => [item, item]), onChange: setAccountNames, multiple: false },
    operator: { label: '运营', value: operator, options: [['__unassigned__', '未设置'], ...(facets?.operators || []).map(item => [item, item])], onChange: setOperator, multiple: false },
    accountType: { label: '账户类型', value: accountType, options: (facets?.account_types || []).map(item => [item, item]), onChange: setAccountType, multiple: false },
    pageType: { label: '页面类型', value: pageType, options: (facets?.page_types || []).map(item => [item, item]), onChange: setPageType, multiple: false },
    remoteStatus: { label: '账户状态', value: remoteStatus, options: [['missing', '未同步'], ['1', '有效'], ['2', '正常生效'], ['3', '余额为零'], ['11', '预算不足'], ['6', '审核中'], ['4', '未通过审核'], ['7', '被禁用']], onChange: setRemoteStatus, multiple: false },
    authorization: { label: '授权', value: authorizationStatus, options: [['granted', '已授权'], ['unchecked', '待授权'], ['oauth_started', '授权中'], ['revoked', '已撤销']], onChange: setAuthorizationStatus, multiple: false },
  }

  return <section className={`account-management-frame account-page-${mode}${showingManagers ? ' is-manager-directory' : ''}${canManage ? '' : ' is-read-only'}`}>
    <div className={`account-management-view-controls ${mode === 'management' ? 'has-manager-tabs' : ''}`}>
      {mode === 'management' ? <div className="manager-account-tabs" role="tablist" aria-label="账户管家"><button type="button" role="tab" aria-selected={activeTab === 'managers'} className={activeTab === 'managers' ? 'active' : ''} onClick={() => setActiveTab('managers')} onKeyDown={event => moveHorizontalTab(event, managerTabIds, activeTab, setActiveTab)}><span>账户管家</span><em>{managers.length}</em></button>{managers.map(item => <button type="button" role="tab" aria-selected={activeTab === item.id} key={item.id} className={activeTab === item.id ? 'active' : ''} onClick={() => setActiveTab(item.id)} onKeyDown={event => moveHorizontalTab(event, managerTabIds, activeTab, setActiveTab)}><span>{item.display_name || item.login_name}</span><em>{item.account_count}</em></button>)}</div> : null}
      <div className="account-management-toolbar">
        {mode === 'operations' ? <div className="account-management-date"><DateFilterGroup valueFrom={dateFrom} valueTo={dateTo} onChange={r => { setDateFrom(r.from); setDateTo(r.to) }} /></div> : null}
        <div className="account-management-actions account-management-query-actions">
          {mode === 'operations' ? <div className="account-toolbar-filters">
            <label className="account-toolbar-filter"><span>账户状态</span><select value={toolbarFilterValue(accountStatus)} onChange={e => setAccountStatus(e.target.value)}><option value="">全部账户</option><option value="current">在用账户</option>{['未通过审核', '被禁用', '计划全停', '预算不足', '上线', '已淘汰', '待上线', '空账户'].map(item => <option key={item}>{item}</option>)}</select></label>
            <label className="account-toolbar-filter"><span>运营</span><select value={toolbarFilterValue(operator)} onChange={e => setOperator(e.target.value)}><option value="">全部</option>{facets?.operators.map(item => <option key={item}>{item}</option>)}</select></label>
            <label className="account-toolbar-filter"><span>页面类型</span><select value={toolbarFilterValue(pageType)} onChange={e => setPageType(e.target.value)}><option value="">全部</option>{facets?.page_types.map(item => <option key={item}>{item}</option>)}</select></label>
          </div> : null}
          {mode === 'operations' && canManage ? <><Button size="small" appearance="secondary" disabled={!selected.size} onClick={() => props.onOpenCampaignSchedule?.([...selected])}>批量时段{selected.size ? `（${selected.size}）` : ''}</Button><Button size="small" appearance="secondary" disabled={!selected.size} onClick={() => props.onConfirmCampaignState?.([...selected], false)}>批量启动{selected.size ? `（${selected.size}）` : ''}</Button><Button size="small" appearance="secondary" disabled={!selected.size} onClick={() => props.onConfirmCampaignState?.([...selected], true)}>批量暂停{selected.size ? `（${selected.size}）` : ''}</Button></> : null}
          {showingManagers && canManage ? <Button className="add-manager-button" size="small" appearance="primary" onClick={props.onAddManager}>添加账户管家</Button> : null}
          {canManage && !showingManagers && mode === 'management' ? <>{selected.size ? <span className="selected-account-count">已选择 {selected.size} 个</span> : null}<Button size="small" appearance="secondary" disabled={!selected.size} onClick={() => props.onOpenBatchSettings?.([...selected])}>批量设置</Button><Button size="small" appearance="secondary" onClick={props.onOpenCustomIdSettings}>设置自定义ID</Button><Button size="small" appearance="secondary" onClick={props.onOpenCustomIdList}>自定义ID列表</Button></> : null}
          <div className="account-management-search"><SearchField value={searchInput} placeholder="账户名称 / 账户ID" onChange={setSearchInput} onSearch={() => { if (mode === 'management') setAccountNames(''); setSearch(searchInput.trim()) }} onClear={() => { setSearchInput(''); setSearch('') }} /></div>
          <Button className="toolbar-refresh-button" size="small" appearance="secondary" aria-label="刷新" title="刷新" onClick={() => setRefreshKey(v => v + 1)}><span aria-hidden="true">↻</span></Button>
        </div>
      </div>
    </div>
    {error ? <PopupMessage intent="error">{error}</PopupMessage> : null}
    {mode === 'operations' && workspace ? <section className="account-list-overview" aria-label="账户列表概览" aria-busy={loading}>
      {overviewItems.map(([key, label, value]) => {
        const trend = workspace.comparison?.trends[key]
        const trendValue = trend?.percent == null ? '—' : `${trend.direction === 'up' ? '▲' : trend.direction === 'down' ? '▼' : '—'} ${trend.percent}%`
        return <div key={key}><span>{label}</span><strong>{value}</strong><em className={`account-list-overview-trend ${trend?.direction || 'muted'}`}><b>{trendValue}</b><small>环比上周期</small></em></div>
      })}
    </section> : null}
    {showingManagers ? <ManagerTable managers={pagedManagers} props={props} setArchiveTarget={setArchiveTarget} setPauseTarget={setPauseTarget} onEditSetting={openManagerSetting} /> : loading && !rows.length ? <Skeleton className="workspace-loading"><SkeletonItem /><SkeletonItem /><SkeletonItem /></Skeleton> : <div className="account-management-table-wrap"><table className={`account-management-table account-list-table${mode === 'operations' ? ' account-list-table--operations' : ''}`}>{mode === 'management' ? <ManagementRows rows={rows as AccountManagementRow[]} selected={selected} toggleOne={toggleOne} allPageSelected={allPageSelected} togglePage={togglePage} sortButton={sortButton} columnFilters={managementColumnFilters} props={props} /> : <OperationRows rows={rows as AccountWorkspaceRow[]} costMode={workspace?.cost_judgment?.mode || 'add_cash'} selected={selected} toggleOne={toggleOne} allPageSelected={allPageSelected} togglePage={togglePage} sortButton={sortButton} columnFilters={operationColumnFilters} expandedAccountId={expandedAccountId} ocpcDetails={ocpcDetails} ocpcLoadingId={ocpcLoadingId} ocpcErrors={ocpcErrors} onToggleOcpcProjects={toggleAccountOcpcProjects} onRetireAccount={row => { setRetirementError(null); setRetirementTarget(row) }} retirementNotice={retirementNotice} canManage={canManage} />}</table></div>}
    {showingManagers ? <ViewportStickyPagination page={safeManagerPage} totalPages={managerTotalPages} total={filteredManagers.length} pageSize={managerPageSize} loading={loading} ariaLabel="账户管家分页" onPageChange={setManagerPage} onPageSizeChange={size => { setManagerPageSize(size); setManagerPage(1) }} /> : <ViewportStickyPagination page={page} totalPages={totalPages} total={total} pageSize={pageSize} loading={loading} ariaLabel="账户列表分页" onPageChange={setPage} onPageSizeChange={size => { setPageSize(size); setPage(1) }} />}
    <Dialog open={archiveTarget !== null} onOpenChange={(_, data) => { if (!data.open && !props.archiveBusyId) setArchiveTarget(null) }}>
      <DialogSurface className="account-confirm-dialog"><DialogBody><DialogTitleWithSummary summary="删除后保留全部历史数据，不会修改百度端账户">删除账户管家</DialogTitleWithSummary><DialogContent><p>确定删除“{archiveTarget?.display_name || archiveTarget?.login_name}”吗；下辖账户及全部历史数据全部存档保留，不会修改百度端账户</p></DialogContent><DialogActions><Button appearance="secondary" disabled={Boolean(props.archiveBusyId)} onClick={() => setArchiveTarget(null)}>取消</Button><Button appearance="primary" disabled={Boolean(props.archiveBusyId)} onClick={async () => { if (!archiveTarget) return; await props.onArchiveManager?.(archiveTarget); setArchiveTarget(null) }}>{props.archiveBusyId ? '正在删除…' : '确认删除并存档'}</Button></DialogActions></DialogBody></DialogSurface>
    </Dialog>
    <Dialog open={pauseTarget !== null} onOpenChange={(_, data) => { if (!data.open && !props.statusBusyId) setPauseTarget(null) }}>
      <DialogSurface className="account-confirm-dialog"><DialogBody><DialogTitleWithSummary summary="暂停使用，不删除账户、授权和历史数据">停用管家</DialogTitleWithSummary><DialogContent><p>确定停用“{pauseTarget?.display_name || pauseTarget?.login_name}”吗？停用后不再同步或执行该管家下辖账户的任务，需要时可重新启用。</p></DialogContent><DialogActions><Button appearance="secondary" disabled={Boolean(props.statusBusyId)} onClick={() => setPauseTarget(null)}>取消</Button><Button appearance="primary" disabled={Boolean(props.statusBusyId)} onClick={async () => { if (!pauseTarget) return; if (await props.onSetManagerActive?.(pauseTarget, false)) setPauseTarget(null) }}>{props.statusBusyId ? '正在停用…' : '确认停用'}</Button></DialogActions></DialogBody></DialogSurface>
    </Dialog>
    <Dialog open={managerEditTarget !== null} onOpenChange={(_, data) => { if (!data.open && !props.settingsBusyId) setManagerEditTarget(null) }}>
      <DialogSurface className="account-confirm-dialog manager-setting-dialog"><DialogBody><DialogTitleWithSummary summary={managerEditKind === 'rebate_rate' ? '修改后统一应用到该管家的下辖账户' : '余额低于此值时，账户管理导航文字标红；留空可关闭预警'}>{managerEditKind === 'rebate_rate' ? '修改返点' : '修改余额预警'}</DialogTitleWithSummary><DialogContent><div className="manager-setting-form"><label htmlFor="manager-setting-value">{managerEditKind === 'rebate_rate' ? '返点' : '余额预警'}</label><Input id="manager-setting-value" type="number" min={0} max={managerEditKind === 'rebate_rate' ? 100 : 999999999999} step="0.01" value={managerEditValue} contentBefore={managerEditKind === 'rebate_rate' ? undefined : <span>¥</span>} contentAfter={managerEditKind === 'rebate_rate' ? <span>%</span> : undefined} onChange={(_, data) => { setManagerEditValue(data.value); setManagerEditError(null) }} autoFocus /></div>{managerEditError ? <PopupMessage intent="error">{managerEditError}</PopupMessage> : null}</DialogContent><DialogActions><Button appearance="secondary" disabled={Boolean(props.settingsBusyId)} onClick={() => setManagerEditTarget(null)}>取消</Button><Button appearance="primary" disabled={Boolean(props.settingsBusyId)} onClick={() => void saveManagerSetting()}>{props.settingsBusyId ? '保存中…' : '保存'}</Button></DialogActions></DialogBody></DialogSurface>
    </Dialog>
    <Dialog open={retirementTarget !== null} onOpenChange={(_, data) => { if (!data.open && !retirementBusy) setRetirementTarget(null) }}>
      <DialogSurface className="account-confirm-dialog account-retirement-dialog"><DialogBody><DialogTitleWithSummary summary="删除项目和计划，成功回读后标记为已淘汰">确认淘汰账户</DialogTitleWithSummary><DialogContent><div className="account-retirement-summary"><span aria-hidden="true">!</span><div><small>即将淘汰账户</small><strong>{retirementTarget?.account_name || '—'}</strong><em>{retirementTarget?.account_id || '—'}</em></div></div><ul className="account-retirement-scope"><li>删除 oCPC 项目</li><li>删除账户下已有计划；没有计划时自动跳过</li><li>计划删除会同步删除其下单元、关键词和创意</li><li>不会清空或释放账户；成功回读后标记为“已淘汰”</li></ul>{retirementError ? <PopupMessage intent="error">{retirementError}</PopupMessage> : null}</DialogContent><DialogActions><Button appearance="secondary" disabled={retirementBusy} onClick={() => setRetirementTarget(null)}>取消</Button><Button className="account-retirement-confirm" appearance="primary" disabled={retirementBusy} onClick={async () => { if (!retirementTarget) return; setRetirementBusy(true); setRetirementError(null); try { const target = retirementTarget; const preview = await apiPost<{ operation_id: string; campaign_count: number; ocpc_project_count: number }>(`/projects/${project.id}/accounts/${target.id}/retirement`, {}); const confirmed = await apiPost<{ task_id: string }>(`/operations/${preview.operation_id}/confirm`, {}); setRetirementNotice({ accountId: target.id, text: `正在淘汰：${target.account_name}（${preview.ocpc_project_count} 个 oCPC 项目、${preview.campaign_count} 个计划）` }); setRetirementTask({ taskId: confirmed.task_id, accountId: target.id, accountName: target.account_name }); setRetirementTarget(null) } catch (reason) { setRetirementError(reason instanceof Error ? reason.message : '淘汰任务提交失败') } finally { setRetirementBusy(false) } }}>{retirementBusy ? '正在提交…' : '确认淘汰'}</Button></DialogActions></DialogBody></DialogSurface>
    </Dialog>
  </section>
}

function ManagerTable({ managers, props, setArchiveTarget, setPauseTarget, onEditSetting }: { managers: AccountManager[]; props: Props; setArchiveTarget: (m: AccountManager) => void; setPauseTarget: (m: AccountManager) => void; onEditSetting: (m: AccountManager, kind: 'balance_warning_threshold' | 'rebate_rate') => void }) {
  return <div className="account-management-table-wrap"><table className="account-management-table manager-management-table"><thead><tr><th className="table-cell--center">类型</th><th className="table-cell--center">账户</th><th className="table-cell--center table-cell--number">账户余额</th><th className="table-cell--center table-cell--number">余额预警</th><th className="table-cell--center table-cell--number">返点</th><th className="table-cell--center">授权</th><th className="table-cell--center">操作</th><th className="table-cell--center">充值账户</th></tr></thead><tbody>{managers.length ? managers.map(m => <tr key={m.id} className={m.is_active ? undefined : 'is-manager-paused'}><td className="table-cell--center">账户管家</td><td className="table-cell--center">{m.display_name || m.login_name}</td><td className="table-cell--center table-cell--number" title={m.balance_account_name ? `充值账户：${m.balance_account_name}` : '尚未读取充值账户余额'}>{money(m.balance)}</td><td className="table-cell--center table-cell--number"><div className={`manager-setting-cell${m.balance_warning_active ? ' is-warning' : ''}`}><span>{m.balance_warning_threshold == null ? '未设置' : `¥ ${money(m.balance_warning_threshold)}`}</span><Button size="small" appearance="subtle" disabled={Boolean(props.settingsBusyId)} onClick={() => onEditSetting(m, 'balance_warning_threshold')}>修改</Button></div></td><td className="table-cell--center table-cell--number"><div className="manager-setting-cell"><span>{m.rebate_rate == null ? '—' : `${Number(m.rebate_rate)}%`}</span><Button size="small" appearance="subtle" disabled={Boolean(props.settingsBusyId)} onClick={() => onEditSetting(m, 'rebate_rate')}>修改</Button></div></td><td className="table-cell--center">{m.is_active ? (authorized(m.auth_status) ? '已授权' : '待授权') : '已停用'}</td><td className="table-cell--center"><div className="manager-row-actions">{m.is_active ? <><Button size="small" appearance="secondary" disabled={props.oauthBusyId === m.id} onClick={() => props.onAuthorizeManager?.(m)}>API授权</Button>{authorized(m.auth_status) ? <><Button size="small" appearance="secondary" disabled={props.balanceBusyId === m.id} onClick={() => props.onRefreshManagerBalance?.(m)}>刷新余额</Button><Button size="small" appearance="secondary" disabled={props.syncBusyId === m.id} onClick={() => props.onSyncManagerAccounts?.(m)}>{props.syncBusyId === m.id ? '同步中…' : '同步下辖账户'}</Button></> : null}<Button size="small" appearance="secondary" disabled={props.statusBusyId === m.id} onClick={() => setPauseTarget(m)}>停用管家</Button></> : <Button size="small" appearance="secondary" disabled={props.statusBusyId === m.id} onClick={() => void props.onSetManagerActive?.(m, true)}>{props.statusBusyId === m.id ? '启用中…' : '启用管家'}</Button>}<Button size="small" appearance="secondary" disabled={props.archiveBusyId === m.id || props.statusBusyId === m.id} onClick={() => setArchiveTarget(m)}>删除管家</Button></div></td><td className="table-cell--center">{m.recharge_account || '—'}</td></tr>) : <tr><td className="account-management-empty" colSpan={8}>当前项目尚未绑定账户管家</td></tr>}</tbody></table></div>
}
type RowShared = { selected: Set<string>; toggleOne: (id: string, checked: boolean, shift: boolean) => void; allPageSelected: boolean; togglePage: (checked: boolean) => void; sortButton: (key: string, label: string) => ReactNode }
function ManagementRows({ rows, props, columnFilters, ...shared }: RowShared & { rows: AccountManagementRow[]; props: Props; columnFilters: ManagementColumnFilters }) {
  const filterHeader = (key: keyof ManagementColumnFilters, className: string, content?: ReactNode) => <th className={className}><TableColumnFilter filter={columnFilters[key]}>{content}</TableColumnFilter></th>
  return <><thead><tr><th className="table-cell--center"><input type="checkbox" checked={shared.allPageSelected} onChange={e => shared.togglePage(e.target.checked)} aria-label="选择当前页" /></th>{filterHeader('accountName', 'table-cell--start', shared.sortButton('account_name', '账户'))}<th className="table-cell--start table-cell--id">{shared.sortButton('account_id', '账户ID')}</th>{filterHeader('operator', 'table-cell--start')}{filterHeader('accountType', 'table-cell--center')}{filterHeader('pageType', 'table-cell--center')}<th className="table-cell--end table-cell--number">账户余额</th><th className="table-cell--end table-cell--number">返点</th>{filterHeader('remoteStatus', 'table-cell--center')}{filterHeader('authorization', 'table-cell--center')}<th className="table-cell--center">操作</th></tr></thead><tbody>{rows.length ? rows.map(row => <tr key={row.id}><td className="table-cell--center"><input type="checkbox" checked={shared.selected.has(row.id)} onClick={e => shared.toggleOne(row.id, !shared.selected.has(row.id), e.shiftKey)} onChange={() => undefined} /></td><td className="table-cell--start">{row.account_name}</td><td className="table-cell--start table-cell--id">{row.account_id}</td><td className="table-cell--start">{row.operator_name || '未设置'}</td><td className="table-cell--center">{row.account_type}</td><td className="table-cell--center">{row.page_type || '—'}</td><td className="table-cell--end table-cell--number" title={row.balance_source_account_name ? `读取自充值账户：${row.balance_source_account_name}` : '尚未读取充值账户余额'}>{money(row.balance)}</td><td className="table-cell--end table-cell--number">{row.rebate_rate == null ? '—' : `${Number(row.rebate_rate)}%`}</td><td className="table-cell--center">{row.remote_status_text}</td><td className="table-cell--center">{authorized(row.authorization_status) ? '已授权' : '待授权'}</td><td className="table-cell--center"><Button size="small" appearance="secondary" disabled={props.oauthBusyId === row.id} onClick={() => props.onAuthorizeAccount?.(row)}>{props.oauthBusyId === row.id ? '跳转中…' : '单账户授权'}</Button></td></tr>) : <tr><td className="account-management-empty" colSpan={11}>当前筛选条件没有账户</td></tr>}</tbody></>
}
type OperationRowsProps = RowShared & {
  rows: AccountWorkspaceRow[]
  costMode: 'add_cash' | 'copy_cash'
  expandedAccountId: string | null
  ocpcDetails: Record<string, AccountOcpcProjectList>
  ocpcLoadingId: string | null
  ocpcErrors: Record<string, string>
  onToggleOcpcProjects: (row: AccountWorkspaceRow) => void
  onRetireAccount: (row: AccountWorkspaceRow) => void
  retirementNotice: { accountId: string; text: string } | null
  canManage: boolean
  columnFilters: OperationColumnFilters
}
type ColumnFilter = TableColumnFilterConfig
type OperationColumnFilters = Record<'accountStatus' | 'costStatus' | 'operator' | 'manager' | 'accountType' | 'pageType' | 'accountName', ColumnFilter>
type ManagementColumnFilters = Record<'accountName' | 'operator' | 'accountType' | 'pageType' | 'remoteStatus' | 'authorization', ColumnFilter>

function OperationRows({ rows, costMode, expandedAccountId, ocpcDetails, ocpcLoadingId, ocpcErrors, onToggleOcpcProjects, onRetireAccount, retirementNotice, canManage, columnFilters, ...shared }: OperationRowsProps) {
  const isCopyJudgment = costMode === 'copy_cash'
  const filterHeader = (key: keyof OperationColumnFilters) => <th className="table-cell--start"><TableColumnFilter filter={columnFilters[key]} /></th>
  return <>
    <colgroup><col className="account-col-select" /><col className="account-col-status" /><col className="account-col-lifecycle" /><col className="account-col-operator" /><col className="account-col-manager" /><col className="account-col-type" /><col className="account-col-page-type" /><col className="account-col-name" /><col className="account-col-id" /><col className="account-col-budget" /><col className="account-col-impressions" /><col className="account-col-clicks" /><col className="account-col-spend" /><col className="account-col-adds" /><col className="account-col-cpm" /><col className="account-col-ctr" /><col className="account-col-add-cost" /><col className="account-col-cash-add-cost" /></colgroup>
    <thead><tr>
      <th className="select-column table-cell--center"><input type="checkbox" disabled={!canManage} checked={shared.allPageSelected} onChange={e => shared.togglePage(e.target.checked)} aria-label="选择全部筛选结果" /></th>
      {filterHeader('accountStatus')}
      {filterHeader('costStatus')}
      {filterHeader('operator')}
      {filterHeader('manager')}
      {filterHeader('accountType')}
      {filterHeader('pageType')}
      {filterHeader('accountName')}
      <th className="table-cell--start table-cell--id">账户ID</th>
      <th className="table-cell--end table-cell--number">{shared.sortButton('budget', '日预算')}</th>
      <th className="table-cell--end table-cell--number">{shared.sortButton('impressions', '展现')}</th>
      <th className="table-cell--end table-cell--number">{shared.sortButton('clicks', '点击')}</th>
      <th className="table-cell--end table-cell--number">{shared.sortButton('spend', '消费')}</th>
      <th className="table-cell--end table-cell--number">{shared.sortButton(isCopyJudgment ? 'copies' : 'adds', isCopyJudgment ? '复制' : '加粉')}</th>
      <th className="table-cell--end table-cell--number">{shared.sortButton('cpm', 'CPM')}</th>
      <th className="table-cell--end table-cell--number">{shared.sortButton('ctr', 'CTR')}</th>
      <th className="table-cell--end table-cell--number">{shared.sortButton(isCopyJudgment ? 'copy_cost' : 'add_cost', isCopyJudgment ? '账户复制成本' : '账户加粉成本')}</th>
      <th className="table-cell--end table-cell--number">{shared.sortButton(isCopyJudgment ? 'cash_copy_cost' : 'cash_add_cost', isCopyJudgment ? '现金复制成本' : '现金加粉成本')}</th>
    </tr></thead>
    <tbody>{rows.length ? rows.map(row => {
      const expanded = expandedAccountId === row.id
      const detail = ocpcDetails[row.id]
      const canRetire = row.account_status !== '空账户' && row.account_status !== '已淘汰'
      const retirementButtonTitle = !canRetire ? (row.account_status === '空账户' ? '空账户不能淘汰' : '该账户已淘汰') : '删除 oCPC 项目和计划；不会清空或释放账户'
      return <Fragment key={row.id}>
        <tr className={expanded ? 'is-expanded' : ''}>
          <td className="table-cell--center"><input type="checkbox" checked={shared.selected.has(row.id)} onClick={e => shared.toggleOne(row.id, !shared.selected.has(row.id), e.shiftKey)} onChange={() => undefined} aria-label={`选择账户 ${row.account_name}`} /></td>
          <td className="table-cell--start"><span className="account-status-state">{row.account_status}</span></td>
          <td className="table-cell--start"><span className="account-lifecycle-state">{row.cost_status}</span></td>
          <td className="table-cell--start">{row.operator_name || '未设置'}</td>
          <td className="table-cell--start" title={row.manager_name || undefined}>{row.manager_name || '—'}</td>
          <td className="table-cell--start">{row.account_type}</td>
          <td className="table-cell--start">{row.page_type || '—'}</td>
          <td className="table-cell--start"><button type="button" className="account-name-expand" aria-expanded={expanded} onClick={() => void onToggleOcpcProjects(row)}>{row.account_name}</button></td>
          <td className="table-cell--start table-cell--id">{row.account_id}</td>
          <td className="table-cell--end table-cell--number">{money(row.budget)}</td>
          <td className="table-cell--end table-cell--number">{count(row.impressions)}</td>
          <td className="table-cell--end table-cell--number">{count(row.clicks)}</td>
          <td className="table-cell--end table-cell--number">{overviewMoney(row.spend)}</td>
          <td className="table-cell--end table-cell--number">{count(isCopyJudgment ? row.copies : row.adds)}</td>
          <td className="table-cell--end table-cell--number">{row.cpm == null ? '—' : overviewMoney(row.cpm)}</td>
          <td className="table-cell--end table-cell--number">{row.ctr == null ? '—' : `${Number(row.ctr).toFixed(2)}%`}</td>
          <td className="table-cell--end table-cell--number">{(isCopyJudgment ? row.copy_cost : row.add_cost) == null ? '—' : overviewMoney(isCopyJudgment ? row.copy_cost : row.add_cost)}</td>
          <td className="table-cell--end table-cell--number" title={row.rebate_rate == null ? `未设置返点，无法计算现金${isCopyJudgment ? '复制' : '加粉'}成本` : `按 ${Number(row.rebate_rate)}% 返点计算`}>{(isCopyJudgment ? row.cash_copy_cost : row.cash_add_cost) == null ? '—' : overviewMoney(isCopyJudgment ? row.cash_copy_cost : row.cash_add_cost)}</td>
        </tr>
        {expanded ? <tr className="account-campaign-expanded-row"><td colSpan={18}>
          <div className="account-campaign-panel">
            <div className="account-campaign-panel-head"><div><strong>oCPC 项目</strong><span>{row.account_name}</span></div><div className="account-project-quick-row"><Button className="account-project-budget-button" size="small" appearance="secondary" disabled title="账户日预算修改功能即将接入搜索账户写入任务">修改日预算</Button><Button className="account-retirement-action" size="small" appearance="secondary" title={retirementButtonTitle} disabled={!canRetire} onClick={() => onRetireAccount(row)}>{row.account_status === '已淘汰' ? '已淘汰' : '淘汰账户'}</Button><span className="account-quick-divider">一键调价</span>{[-20, -15, -10, -5, 5, 10, 15, 20].map(rate => <Button key={`relative-${rate}`} className="account-project-quick-button account-project-relative-button" size="small" appearance="secondary" disabled title="等待搜索项目出价任务接入">{rate < 0 ? `降低${Math.abs(rate)}%` : `提高${rate}%`}</Button>)}</div></div>
            {retirementNotice?.accountId === row.id ? <div className="account-campaign-notice">{retirementNotice.text}</div> : null}
            {ocpcLoadingId === row.id ? <div className="account-campaign-message">正在读取 oCPC 项目缓存…</div> : ocpcErrors[row.id] ? <div className="account-campaign-message is-error">{ocpcErrors[row.id]}</div> : detail?.rows.length ? <div className="account-campaign-table-wrap"><table className="account-campaign-table"><thead><tr><th className="table-cell--start">项目名称</th><th className="table-cell--start table-cell--id">项目ID</th><th className="table-cell--end table-cell--number">目标转化出价</th><th className="table-cell--center">出价模式</th><th className="table-cell--center">项目状态</th><th className="table-cell--start">绑定计划</th><th className="table-cell--center table-cell--date">缓存时间</th></tr></thead><tbody>{detail.rows.map(ocpc => <tr key={ocpc.id}><td className="table-cell--start" title={ocpc.ocpc_project_name || undefined}>{ocpc.ocpc_project_name || '未命名项目'}</td><td className="table-cell--start table-cell--id">{ocpc.ocpc_project_id}</td><td className="table-cell--end table-cell--number">{ocpc.ocpc_bid == null ? '—' : `¥ ${money(ocpc.ocpc_bid)}`}</td><td className="table-cell--center">{ocpcBidTypeText(ocpc.bid_type)}</td><td className="table-cell--center">{ocpcStatusText(ocpc.remote_status)}</td><td className="table-cell--start" title={ocpcScopeText(ocpc.scope)}>{ocpcScopeText(ocpc.scope)}</td><td className="table-cell--center table-cell--date">{formatDateTime(ocpc.last_seen_at)}</td></tr>)}</tbody></table></div> : <div className="account-campaign-message">当前账户没有可显示的本地 oCPC 项目缓存；执行“同步计划缓存”后会同时更新这里</div>}
          </div>
        </td></tr> : null}
      </Fragment>
    }) : <tr><td className="account-management-empty" colSpan={18}>当前筛选条件没有账户</td></tr>}</tbody>
  </>
}
