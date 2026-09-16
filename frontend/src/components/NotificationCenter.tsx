import { useEffect, useRef, useState } from 'react'
import { Badge, Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface } from '@fluentui/react-components'
import { DialogTitleWithSummary } from './DialogTitleWithSummary'
import { apiGet, apiPost } from '../api'
import type { NotificationFeed, NotificationItem } from '../types'
import { getUiTimeZone } from '../uiTimeZone'

type Props = { projectId: string | null; identityKey: string }

export function NotificationCenter({ projectId, identityKey }: Props) {
  const [feed, setFeed] = useState<NotificationFeed>({ unread_count: 0, items: [] })
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<NotificationItem | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const load = async (signal?: AbortSignal) => {
    if (!projectId) return
    try { setFeed(await apiGet<NotificationFeed>(`/projects/${projectId}/notifications?limit=30`, signal)); setLoadError(false) }
    catch (reason) { if (!(reason instanceof DOMException && reason.name === 'AbortError')) setLoadError(true) }
  }
  useEffect(() => {
    const controller = new AbortController()
    setFeed({ unread_count: 0, items: [] }); void load(controller.signal)
    const timer = window.setInterval(() => void load(), 60_000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [projectId, identityKey])
  useEffect(() => {
    if (!open) return
    const closeOnOutsideClick = (event: PointerEvent) => { if (!rootRef.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('pointerdown', closeOnOutsideClick)
    return () => document.removeEventListener('pointerdown', closeOnOutsideClick)
  }, [open])
  const openNotification = async (item: NotificationItem) => {
    setSelected(item); setOpen(false)
    if (!projectId || item.is_read) return
    setFeed(current => ({ unread_count: Math.max(0, current.unread_count - 1), items: current.items.map(row => row.id === item.id ? { ...row, is_read: true } : row) }))
    try { await apiPost(`/projects/${projectId}/notifications/${item.id}/read`, {}) } catch { void load() }
  }
  const markAllRead = async () => {
    if (!projectId || !feed.unread_count || busy) return
    setBusy(true)
    try { await apiPost(`/projects/${projectId}/notifications/read-all`, {}); setFeed(current => ({ unread_count: 0, items: current.items.map(item => ({ ...item, is_read: true })) })) }
    finally { setBusy(false) }
  }
  const detailRows = selected ? notificationDetailRows(selected) : []
  return <>
    <div className="notification-center" ref={rootRef}>
      <button type="button" className="notification-trigger" data-testid="notification-trigger" aria-label={`提醒${feed.unread_count ? `，${feed.unread_count} 条未读` : ''}`} aria-expanded={open} onClick={() => { setOpen(value => !value); if (!open) void load() }}><span className="notification-label">提醒</span>{feed.unread_count > 0 && <span>{feed.unread_count > 99 ? '99+' : feed.unread_count}</span>}</button>
      {open && <section className="notification-popover" aria-label="全局提醒"><header><div><strong>提醒</strong><small>{feed.unread_count ? `${feed.unread_count} 条未读` : '已全部查看'}</small></div><Button size="small" appearance="subtle" disabled={!feed.unread_count || busy} onClick={() => void markAllRead()}>{busy ? '处理中…' : '全部已读'}</Button></header><div className="notification-list">{loadError && <div className="notification-empty"><span>提醒读取失败；请稍后重试</span></div>}{!loadError && !feed.items.length && <div className="notification-empty"><span>暂时没有提醒</span></div>}{!loadError && feed.items.map(item => <button type="button" className={`notification-item ${item.is_read ? '' : 'unread'}`} key={item.id} onClick={() => void openNotification(item)}><span><strong>{item.title}</strong><small>{item.summary}</small><time>{formatDateTime(item.occurred_at)}</time></span></button>)}</div></section>}
    </div>
    <Dialog open={selected !== null} onOpenChange={(_, data) => { if (!data.open) setSelected(null) }}><DialogSurface className="notification-dialog"><DialogBody><DialogTitleWithSummary summary="查看本条提醒的详情与处理信息">{selected?.title || '提醒详情'}</DialogTitleWithSummary><DialogContent>{selected && <div className="notification-detail"><div className="notification-detail-meta"><Badge appearance="tint" color={notificationBadgeColor(selected.severity)}>{notificationCategoryText(selected.category)}</Badge><span>{formatDateTime(selected.occurred_at)}</span></div><p>{selected.body}</p>{detailRows.length > 0 && <dl>{detailRows.map(row => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl>}</div>}</DialogContent><DialogActions><Button appearance="primary" onClick={() => setSelected(null)}>知道了</Button></DialogActions></DialogBody></DialogSurface></Dialog>
  </>
}

function notificationBadgeColor(severity: string): 'success' | 'danger' | 'warning' | 'informative' { return severity === 'success' ? 'success' : severity === 'error' ? 'danger' : severity === 'warning' ? 'warning' : 'informative' }
function notificationCategoryText(category: string) { return ({ task_status: '任务状态', refund_due: '退款提醒', low_balance: '充值提醒' } as Record<string, string>)[category] || '系统提醒' }
function formatDateTime(value?: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: getUiTimeZone() }).format(new Date(value)) : '暂无' }
function notificationDetailRows(item: NotificationItem): Array<{ label: string; value: string }> {
  if (item.category !== 'low_balance') return []
  const payload = item.payload
  const cashAccount = typeof payload.cash_account === 'string' ? payload.cash_account : Array.isArray(payload.cash_accounts) ? payload.cash_accounts.join('、') : ''
  if (payload.rule === 'cash_group_balance_below_7d_average_daily_spend' || payload.rule === 'cash_group_balance_below_2_days_7d_average_spend') {
    const dateRange = payload.date_from && payload.date_to ? `${payload.date_from} 至 ${payload.date_to}` : '—'
    return [['钱柜账户', cashAccount || '未设置'], ['关联账户', payload.group_account_count == null ? '—' : `${payload.group_account_count} 个`], ['账户余额合计', payload.group_balance == null ? '—' : `¥${payload.group_balance}`], ['近7日总消耗', payload.spend_7d == null ? '—' : `¥${payload.spend_7d}`], ['平均日消耗', payload.average_daily_spend_7d == null ? '—' : `¥${payload.average_daily_spend_7d}/天`], ['预计可用', payload.balance_days == null ? '—' : `${payload.balance_days} 天`], ['统计周期', dateRange]].map(([label, value]) => ({ label, value }))
  }
  return [['钱柜账户', cashAccount || '未设置'], ['近 7 天消耗', payload.spend_7d == null ? '—' : `¥${payload.spend_7d}`], ['近 7 天加粉', payload.adds_7d == null ? '—' : String(payload.adds_7d)], ['近 7 天加粉成本', payload.add_cost_7d == null ? '—' : `¥${payload.add_cost_7d}`]].map(([label, value]) => ({ label, value }))
}
