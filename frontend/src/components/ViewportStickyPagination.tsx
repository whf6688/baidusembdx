import { useEffect, useId, useState } from 'react'
import { Button } from '@fluentui/react-components'

type ViewportStickyPaginationProps = {
  page: number
  totalPages: number
  total: number
  pageSize: number
  onPageChange: (page: number) => void
  onPageSizeChange?: (pageSize: number) => void
  loading?: boolean
  ariaLabel?: string
  contained?: boolean
}

/** Page-level pagination that stays visible below each primary data region. */
export function ViewportStickyPagination({ page, totalPages, total, pageSize, onPageChange, onPageSizeChange, loading = false, ariaLabel = '列表分页', contained = false }: ViewportStickyPaginationProps) {
  const safeTotalPages = Math.max(1, totalPages)
  const safePage = Math.min(Math.max(1, page), safeTotalPages)
  const [jumpValue, setJumpValue] = useState(String(safePage))
  const [jumpError, setJumpError] = useState('')
  const errorId = useId()

  useEffect(() => {
    setJumpValue(String(safePage))
    setJumpError('')
  }, [safePage])

  const go = (next: number) => {
    const target = Math.trunc(next)
    if (!Number.isFinite(target) || target < 1 || target > safeTotalPages) {
      setJumpError(`请输入 1 至 ${safeTotalPages} 之间的页码`)
      return
    }
    setJumpError('')
    if (target !== safePage) onPageChange(target)
  }
  const first = total ? (safePage - 1) * pageSize + 1 : 0
  const last = total ? Math.min(safePage * pageSize, total) : 0

  return <footer className={`viewport-sticky-pagination${contained ? ' is-contained' : ''}`} aria-label={ariaLabel} aria-busy={loading}>
    <span className="pagination-summary" aria-live="polite">显示 {first}–{last}，共 {total} 条</span>
    <nav className="pagination-actions" aria-label="分页操作">
      {onPageSizeChange ? <label className="pagination-size"><span>每页</span><select aria-label="每页条数" value={pageSize} disabled={loading} onChange={event => onPageSizeChange(Number(event.target.value))}><option value={10}>10</option><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option></select><span>条</span></label> : <span className="pagination-size">每页 {pageSize} 条</span>}
      <Button size="small" appearance="secondary" disabled={loading || safePage <= 1} onClick={() => go(safePage - 1)}>上一页</Button>
      <label className="pagination-jump"><input aria-label="跳转页码" aria-invalid={Boolean(jumpError)} aria-describedby={jumpError ? errorId : undefined} value={jumpValue} inputMode="numeric" disabled={loading} onChange={event => { setJumpValue(event.target.value.replace(/\D/g, '')); setJumpError('') }} onKeyDown={event => { if (event.key === 'Enter') go(Number(jumpValue)) }} /></label>
      <span className="pagination-page" aria-current="page">/ {safeTotalPages} 页</span>
      <Button size="small" appearance="secondary" disabled={loading} onClick={() => go(Number(jumpValue))}>跳转</Button>
      <Button size="small" appearance="secondary" disabled={loading || safePage >= safeTotalPages} onClick={() => go(safePage + 1)}>下一页</Button>
    </nav>
    {jumpError ? <span className="pagination-error" id={errorId} role="status">{jumpError}</span> : null}
  </footer>
}
