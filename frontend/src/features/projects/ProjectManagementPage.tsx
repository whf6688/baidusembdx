import { useCallback, useEffect, useState } from 'react'
import { Badge, Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, Field, Input } from '@fluentui/react-components'
import { DialogTitleWithSummary } from '../../components/DialogTitleWithSummary'
import { apiGet, apiPatch, apiPost } from '../../api'
import { PopupMessage } from '../../components/PopupMessage'
import { ViewportStickyPagination } from '../../components/ViewportStickyPagination'
import type { CodeSyncStatus, Project, RuntimeJobHealth, RuntimeJobKey, RuntimeJobsHealth } from '../../types'

type Props = {
  projects: Project[]
  onProjectChange: (project: Project) => void
  projectUrl: (projectCode: string, page: 'account-list') => string
  writesEnabled: boolean
  canManageCodeSync: boolean
}

const runtimeStatusColor = (status: RuntimeJobHealth['status']) =>
  status === 'normal' ? 'success' : status === 'error' ? 'danger' : status === 'running' ? 'warning' : 'subtle'

function RuntimeSafetyWidget({ writesEnabled }: { writesEnabled: boolean }) {
  const [health, setHealth] = useState<RuntimeJobsHealth | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<RuntimeJobKey | null>(null)
  const load = useCallback(async () => {
    try {
      setHealth(await apiGet<RuntimeJobsHealth>('/runtime-jobs'))
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法读取后台常驻任务状态')
    }
  }, [])
  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 10000)
    return () => window.clearInterval(timer)
  }, [load])
  const refresh = async (job: RuntimeJobHealth) => {
    setBusyKey(job.key)
    setError(null)
    try {
      await apiPost(`/runtime-jobs/${job.key}/refresh`, {})
      setHealth(current => current ? {
        ...current,
        overall_status: 'running',
        jobs: current.jobs.map(item => item.key === job.key ? { ...item, status: 'running', status_text: '已提交', detail: '等待后台任务开始运行' } : item),
      } : current)
      window.setTimeout(() => void load(), 1200)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `${job.label}刷新失败`)
    } finally {
      setBusyKey(null)
    }
  }
  const overallText = error ? '读取失败' : health?.overall_status === 'error' ? '有异常' : health?.overall_status === 'running' ? '运行中' : health?.overall_status === 'normal' ? '正常' : '待观察'
  const overallColor = error || health?.overall_status === 'error' ? 'danger' : health?.overall_status === 'normal' ? 'success' : 'warning'

  return <section id="runtime-health" className="home-dashboard-widget runtime-health-widget" aria-label="运行与安全状态">
    <header className="home-dashboard-widget-head runtime-health-head">
      <div><h2>运行与安全状态</h2><p>后台常驻任务按真实执行记录显示，可逐项手动刷新</p></div>
      <Badge appearance="tint" color={overallColor}>{overallText}</Badge>
    </header>
    <div className={`runtime-health-message ${writesEnabled ? 'is-normal' : 'is-protected'}`}>
      <span>{writesEnabled ? '百度写入已开启，目标账户校验、限频、审计与幂等保护持续生效' : '当前处于只读保护，刷新任务不会执行百度写操作'}</span>
    </div>
    <div className="runtime-job-column">
      <div className="runtime-job-list-title">后台常驻列表</div>
      <div className="runtime-job-list">
        {health?.jobs.map(job => <div className={`runtime-job-row is-${job.status}`} key={job.key}>
          <div className="runtime-job-main"><strong>{job.label}</strong><span title={job.detail}>{job.detail}</span></div>
          <div className="runtime-job-side">
            <Badge appearance="tint" color={runtimeStatusColor(job.status)}>{job.status_text}</Badge>
            <Button size="small" appearance="secondary" disabled={!job.can_refresh || busyKey === job.key} onClick={() => void refresh(job)}>{busyKey === job.key ? '提交中…' : '刷新'}</Button>
          </div>
        </div>)}
        {!health && !error && <div className="runtime-job-empty">正在读取运行状态…</div>}
      </div>
    </div>
    {error && <PopupMessage intent="error">{error}</PopupMessage>}
  </section>
}

const codeSyncLabels: Record<CodeSyncStatus['status'], string> = {
  idle: '等待', running: '同步中', success: '已同步', no_changes: '无变更', conflict: '有冲突', failed: '失败',
}

const formatCodeSyncTime = (value?: string | null) => {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date).replaceAll('/', '-')
}

function CodeSyncWidget({ canManage }: { canManage: boolean }) {
  const [status, setStatus] = useState<CodeSyncStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const load = useCallback(async () => {
    try {
      setStatus(await apiGet<CodeSyncStatus>('/system/code-sync/status'))
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '代码同步状态读取失败')
    }
  }, [])
  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 15_000)
    return () => window.clearInterval(timer)
  }, [load])
  const run = async () => {
    setStarting(true)
    setError(null)
    try {
      setStatus(await apiPost<CodeSyncStatus>('/system/code-sync/run', {}))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '启动代码同步失败')
    } finally {
      setStarting(false)
    }
  }
  const state: CodeSyncStatus['status'] = error ? 'failed' : (status?.status || 'idle')
  const badgeColor = state === 'success' || state === 'no_changes' ? 'success' : state === 'failed' || state === 'conflict' ? 'danger' : 'warning'
  const localState = status
    ? status.excluded_count
      ? `${status.syncable_count} 个可同步 · ${status.excluded_count} 个已跳过`
      : `${status.syncable_count} 个可同步 · ${status.ahead_count} 个待推送`
    : '—'
  return <section className={`home-dashboard-widget code-sync-widget code-sync-${state}`} aria-label="代码同步">
    <header className="home-dashboard-widget-head code-sync-widget-head">
      <div><h2>代码同步</h2><p>本机每天 02:00 自动提交并同步到 GitHub main。</p></div>
      <Badge appearance="tint" color={badgeColor}>{codeSyncLabels[state]}</Badge>
    </header>
    <div className="code-sync-facts">
      <div><span>分支 / 远端</span><strong>{`${status?.branch || status?.target_branch || 'main'} → ${status?.remote || 'origin'}/${status?.target_branch || 'main'}`}</strong></div>
      <div><span>下次运行</span><strong>{formatCodeSyncTime(status?.next_run_at)}</strong></div>
      <div><span>本地状态</span><strong>{localState}</strong></div>
      <div><span>最近提交</span><strong title={status?.last_commit_message || ''}>{status?.last_commit || '—'}</strong></div>
    </div>
    <div className="code-sync-message" role={state === 'failed' || state === 'conflict' ? 'alert' : 'status'}>
      {error || status?.summary || '等待读取搜索项目 Git 同步状态。'}
      {!error && status?.last_error ? ` 原因：${status.last_error}` : ''}
      {status?.conflict_files?.length ? ` 冲突文件：${status.conflict_files.join('、')}` : ''}
    </div>
    <footer className="code-sync-actions">
      <span>{status?.last_finished_at ? `最近运行：${formatCodeSyncTime(status.last_finished_at)}` : '尚未运行'}</span>
      <Button size="small" appearance="secondary" disabled={!canManage || starting || status?.running || status?.enabled === false} title={canManage ? undefined : '只有系统管理员可以执行代码同步'} onClick={() => void run()}>{starting || status?.running ? '同步中…' : '立即同步'}</Button>
    </footer>
  </section>
}

export function ProjectManagementPage({ projects, onProjectChange, projectUrl, writesEnabled, canManageCodeSync }: Props) {
  const [editingProject, setEditingProject] = useState<Project | null>(null)
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [busyProjectId, setBusyProjectId] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const enabledCount = projects.filter(project => project.enabled).length
  const totalPages = Math.max(1, Math.ceil(projects.length / pageSize))
  const safePage = Math.min(page, totalPages)
  const visibleProjects = projects.slice((safePage - 1) * pageSize, safePage * pageSize)

  useEffect(() => { if (page > totalPages) setPage(totalPages) }, [page, totalPages])

  const beginCreate = () => { setEditingProject(null); setName(''); setCode(''); setFormError(null); setEditorOpen(true) }
  const beginEdit = (project: Project) => { setEditingProject(project); setName(project.name); setCode(project.code); setFormError(null); setEditorOpen(true) }
  const submitProject = async () => {
    setFormError(null)
    setBusy(true)
    try {
      const result = editingProject
        ? await apiPatch<Project>(`/projects/${editingProject.id}`, { name: name.trim() })
        : await apiPost<Project>('/projects', { name: name.trim(), code: code.trim().toLowerCase() })
      onProjectChange(result)
      setEditorOpen(false)
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : '项目保存失败')
    } finally { setBusy(false) }
  }
  const toggleProject = async (project: Project) => {
    setFormError(null)
    setBusyProjectId(project.id)
    try {
      const result = await apiPatch<Project>(`/projects/${project.id}`, { enabled: !project.enabled })
      onProjectChange(result)
      if (editingProject?.id === result.id) setEditingProject(result)
    } catch (reason) {
      setFormError(reason instanceof Error ? reason.message : '项目状态更新失败')
    } finally { setBusyProjectId(null) }
  }

  return <>
    <section className="project-home">
      <section className="page-heading compact"><div><h1>首页</h1><p>管理项目并进入对应的投放工作台</p></div></section>
      {formError && <PopupMessage intent="error">{formError}</PopupMessage>}
      <div className="home-dashboard-grid">
        <section className="project-directory home-dashboard-widget" aria-label="项目管理">
          <header className="home-dashboard-widget-head"><div><h2>项目管理</h2><p>选择项目进入工作台；支持在新标签中分别操作不同项目</p></div><Button size="small" appearance="secondary" onClick={beginCreate}>新建项目</Button></header>
          <div className="project-widget-table" role="table" aria-label="项目列表">
            <div className="project-widget-table-head" role="row"><span role="columnheader">项目名称</span><span role="columnheader">项目编码</span><span role="columnheader">账户管家</span><span role="columnheader">推广账户</span><span role="columnheader">状态</span><span role="columnheader">操作</span></div>
            {visibleProjects.map(project => <div className="project-widget-table-row" role="row" key={project.id}>
              <div className="project-name-cell" role="cell">{project.enabled ? <a className="project-name-button" href={projectUrl(project.code, 'account-list')}><strong>{project.name}</strong></a> : <span className="project-name-button"><strong>{project.name}</strong></span>}</div>
              <span className="project-code-cell" role="cell">{project.code}</span>
              <span className="project-widget-number" role="cell">{project.manager_count}</span>
              <span className="project-widget-number" role="cell">{project.account_count}</span>
              <span className="project-widget-status" role="cell"><Badge appearance="tint" color={project.enabled ? 'success' : 'subtle'}>{project.enabled ? '启用' : '停用'}</Badge></span>
              <div className="project-row-actions" role="cell">{project.enabled ? <Button as="a" size="small" appearance="secondary" href={projectUrl(project.code, 'account-list')}>进入项目</Button> : <Button size="small" appearance="secondary" disabled>进入项目</Button>}{project.enabled ? <Button as="a" size="small" appearance="secondary" href={projectUrl(project.code, 'account-list')} target="_blank" rel="noopener">新标签打开</Button> : <Button size="small" appearance="secondary" disabled>新标签打开</Button>}<Button size="small" appearance="secondary" onClick={() => beginEdit(project)}>编辑</Button><Button size="small" appearance="secondary" disabled={busyProjectId === project.id || (project.enabled && enabledCount <= 1)} onClick={() => void toggleProject(project)}>{busyProjectId === project.id ? '处理中…' : project.enabled ? '停用' : '启用'}</Button></div>
            </div>)}
            {!projects.length && <div className="project-empty"><span>当前没有项目</span></div>}
          </div>
        </section>
        <RuntimeSafetyWidget writesEnabled={writesEnabled} />
        <CodeSyncWidget canManage={canManageCodeSync} />
      </div>
      <ViewportStickyPagination page={safePage} totalPages={totalPages} total={projects.length} pageSize={pageSize} ariaLabel="项目管理分页" onPageChange={setPage} onPageSizeChange={size => { setPageSize(size); setPage(1) }} />
    </section>
    <Dialog open={editorOpen} onOpenChange={(_, data) => setEditorOpen(data.open)}>
      <DialogSurface className="project-dialog">
        <DialogBody>
          <DialogTitleWithSummary summary="项目编码用于隔离业务数据；创建后不能修改">{editingProject ? '编辑项目' : '新建项目'}</DialogTitleWithSummary>
          <DialogContent className="project-dialog-content">
            <div className="project-dialog-form">
              <Field label="项目名称" required>
                <Input value={name} maxLength={100} onChange={(_, data) => setName(data.value)} placeholder="例如：减肥" />
              </Field>
              <Field label="项目编码" required hint="小写字母开头，仅支持小写字母、数字和短横线">
                <Input value={code} disabled={Boolean(editingProject)} maxLength={50} onChange={(_, data) => setCode(data.value)} placeholder="例如：weight-loss" />
              </Field>
              <div className="project-boundary-note">
                <div><strong>数据边界</strong><span>账户、物料、策略、任务和报表全部归属当前项目</span></div>
              </div>
            </div>
          </DialogContent>
          <DialogActions className="project-dialog-actions">
            <Button appearance="secondary" onClick={() => setEditorOpen(false)}>取消</Button>
            <Button appearance="primary" disabled={busy || !name.trim() || (!editingProject && !/^[a-z][a-z0-9-]+$/.test(code.trim()))} onClick={() => void submitProject()}>{busy ? '正在保存…' : '保存'}</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  </>
}
