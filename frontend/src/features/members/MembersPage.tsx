import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, Skeleton, SkeletonItem } from "@fluentui/react-components";
import { apiGet, apiPatch, apiPost } from "../../api";
import { DialogTitleWithSummary } from "../../components/DialogTitleWithSummary";
import { PageHeader } from "../../components/PageHeader";
import { PopupMessage } from "../../components/PopupMessage";
import { SearchField } from "../../components/SearchField";
import { ViewportStickyPagination } from "../../components/ViewportStickyPagination";
import type { NavigationPermissions, PermissionLevel, PermissionModule, Project, ProjectAccess, ProjectMember, ProjectMemberPage } from "../../types";
import { getUiTimeZone } from "../../uiTimeZone";

const permissionRows: Array<{ key: PermissionModule; label: string; description: string }> = [
  { key: "account_management", label: "账户管理", description: "管家授权、同步、账户配置与归档" },
  { key: "account_list", label: "账户列表", description: "账户指标、时段、预算、启停与淘汰" },
  { key: "auto_launch", label: "自动上线", description: "自动搭建、物料、创意与执行记录" },
  { key: "reports", label: "数据报表", description: "报表查询；管理权限可下载导出" },
  { key: "finance_reports", label: "财务报表", description: "充值对账查询；管理权限可填写利润报表" },
  { key: "member_management", label: "成员管理", description: "管理权限可配置项目成员；系统管理员账号仅本人可修改" },
  { key: "strategies", label: "自动策略", description: "规则、运行设置、试运行与发布" },
];

const defaultPermissions: NavigationPermissions = {
  account_management: "hidden", account_list: "view", auto_launch: "hidden",
  reports: "view", member_management: "hidden", strategies: "hidden",
  finance_reports: "hidden",
};

type MemberDraft = {
  username: string; password: string; display_name: string; operator_name: string; supervisor_id: string;
  data_scope: "self" | "team" | "project"; permissions: NavigationPermissions;
  is_active: boolean; version: number;
};

function newDraft(): MemberDraft {
  return { username: "", password: "", display_name: "", operator_name: "", supervisor_id: "", data_scope: "self", permissions: { ...defaultPermissions }, is_active: true, version: 1 };
}

function draftFromMember(member: ProjectMember): MemberDraft {
  return { username: member.username, password: "", display_name: member.display_name, operator_name: member.operator_name || "", supervisor_id: member.supervisor_id || "", data_scope: member.data_scope, permissions: { ...member.permissions }, is_active: member.is_active, version: member.version };
}

function formatDateTime(value?: string | null) {
  return value ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: getUiTimeZone() }).format(new Date(value)) : "固定配置";
}

function scopeLabel(scope: ProjectMember["data_scope"]) {
  return scope === "project" ? "项目全部账户" : scope === "team" ? "本人及直属成员" : "仅本人运营账户";
}

function permissionSummary(member: ProjectMember) {
  if (member.is_system_owner) return "全部权限";
  return permissionRows.filter(({ key }) => member.permissions[key] !== "hidden").map(({ key, label }) => `${label}·${member.permissions[key] === "manage" ? "管理" : "查看"}`).join("、") || "未分配功能";
}

export function MembersPage({ project, localIdentity, isLocalEnvironment, onSwitchLocalIdentity, isSystemOwner }: {
  project: Project;
  localIdentity: "local-admin" | "wang_kang" | "wang_cong";
  isLocalEnvironment: boolean;
  onSwitchLocalIdentity: (username: "local-admin" | "wang_kang" | "wang_cong") => void;
  isSystemOwner: boolean;
}) {
  const [data, setData] = useState<ProjectMemberPage | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [scope, setScope] = useState("");
  const [supervisor, setSupervisor] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [editing, setEditing] = useState<ProjectMember | "new" | null>(null);
  const [draft, setDraft] = useState<MemberDraft>(newDraft);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [canManageMembers, setCanManageMembers] = useState(isSystemOwner);
  const [confirming, setConfirming] = useState(false);
  const [feedback, setFeedback] = useState<{ intent: "success" | "error"; text: string } | null>(null);

  const query = useMemo(() => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), status });
    if (search.trim()) params.set("search", search.trim());
    if (scope) params.set("data_scope", scope);
    if (supervisor) params.set("supervisor_id", supervisor);
    return params.toString();
  }, [page, pageSize, search, status, scope, supervisor]);

  const load = () => {
    setLoading(true);
    Promise.all([
      apiGet<ProjectMemberPage>(`/projects/${project.id}/members?${query}`),
      apiGet<ProjectAccess>(`/projects/${project.id}/access/me`),
    ])
      .then(([memberPage, access]) => {
        setData(memberPage);
        setCanManageMembers(access.is_system_owner);
      })
      .catch((reason) => setFeedback({ intent: "error", text: reason instanceof Error ? reason.message : "读取成员失败" }))
      .finally(() => setLoading(false));
  };
  useEffect(load, [project.id, query]);
  useEffect(() => setPage(1), [project.id, search, status, scope, supervisor]);

  const openCreate = () => { setDraft(newDraft()); setEditing("new"); setFeedback(null); };
  const openEdit = (member: ProjectMember) => { setDraft(draftFromMember(member)); setEditing(member); setFeedback(null); };
  const setPermission = (key: PermissionModule, level: PermissionLevel) => setDraft((current) => ({ ...current, permissions: { ...current.permissions, [key]: level } }));
  const save = async () => {
    const editingOwner = editing !== null && editing !== "new" && editing.is_system_owner;
    if (!draft.username.trim() || (!editingOwner && (!draft.display_name.trim() || !draft.operator_name.trim()))) {
      setFeedback({ intent: "error", text: "请填写登录账号、成员姓名和运营归属" }); return;
    }
    if (editing === "new" && draft.password.length < 8) {
      setFeedback({ intent: "error", text: "新成员必须设置至少 8 位的初始密码" }); return;
    }
    if (editing !== "new" && draft.password && draft.password.length < 8) {
      setFeedback({ intent: "error", text: "新密码至少需要 8 位" }); return;
    }
    if (editingOwner && editing.username === draft.username && !draft.password) {
      setFeedback({ intent: "error", text: "登录账号和密码都没有修改" }); return;
    }
    setBusy(true);
    try {
      if (editingOwner) {
        await apiPatch(`/projects/${project.id}/members/system-owner/credentials`, {
          username: draft.username,
          password: draft.password || null,
        });
        window.location.reload();
        return;
      }
      const body = { ...draft, password: draft.password || null, supervisor_id: draft.data_scope === "self" && draft.supervisor_id ? draft.supervisor_id : null };
      if (editing === "new") await apiPost(`/projects/${project.id}/members`, body);
      else if (editing) await apiPatch(`/projects/${project.id}/members/${editing.id}`, body);
      setEditing(null); setConfirming(false);
      setFeedback({ intent: "success", text: editing === "new" ? "成员已添加" : "成员权限已更新，下一次请求立即生效" });
      load();
    } catch (reason) {
      setFeedback({ intent: "error", text: reason instanceof Error ? reason.message : "成员设置保存失败" });
    } finally { setBusy(false); }
  };

  const editingOwner = editing !== null && editing !== "new" && editing.is_system_owner;
  const changes = editing && editing !== "new" && !editing.is_system_owner ? permissionRows.filter(({ key }) => editing.permissions[key] !== draft.permissions[key]).map(({ key, label }) => `${label}：${editing.permissions[key]} → ${draft.permissions[key]}`) : [];
  if (editing && editing !== "new" && editing.username !== draft.username) changes.push(`登录账号：${editing.username} → ${draft.username}`);
  if (editing && editing !== "new" && draft.password) changes.push("登录密码：将重置为新密码");
  if (editing && editing !== "new" && editing.data_scope !== draft.data_scope) changes.push(`数据范围：${scopeLabel(editing.data_scope)} → ${scopeLabel(draft.data_scope)}`);
  if (editing && editing !== "new" && editing.is_active !== draft.is_active) changes.push(draft.is_active ? "成员重新启用" : "成员停用并撤销项目访问");

  return <>
    <PageHeader title="成员管理" description="成员身份与登录凭据分开管理；修改账号密码不会改变运营归属和账户分配" />
    {feedback && <PopupMessage intent={feedback.intent}>{feedback.text}</PopupMessage>}
    <section className="account-management-frame member-management-frame">
      <div className="account-list-overview member-overview">
        <div><span>成员总数</span><strong>{data?.summary.total ?? "—"}</strong></div><div><span>启用成员</span><strong>{data?.summary.enabled ?? "—"}</strong></div><div><span>主管人数</span><strong>{data?.summary.supervisors ?? "—"}</strong></div><div><span>已停用</span><strong>{data?.summary.disabled ?? "—"}</strong></div>
      </div>
      <div className="account-management-view-controls member-controls"><div className="account-management-toolbar">
        <SearchField ariaLabel="搜索成员" placeholder="搜索姓名、登录账号或运营归属" value={search} onChange={setSearch} />
        <label>状态<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">全部状态</option><option value="enabled">已启用</option><option value="disabled">已停用</option></select></label>
        <label>主管<select value={supervisor} onChange={(event) => setSupervisor(event.target.value)}><option value="">全部主管</option>{data?.supervisors.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>数据范围<select value={scope} onChange={(event) => setScope(event.target.value)}><option value="">全部范围</option><option value="self">仅本人</option><option value="team">本人及直属成员</option><option value="project">项目全部</option></select></label>
        {isLocalEnvironment && <label>本地身份<select value={localIdentity} onChange={(event) => onSwitchLocalIdentity(event.target.value as "local-admin" | "wang_kang" | "wang_cong")}><option value="local-admin">系统管理员</option><option value="wang_kang">王康</option><option value="wang_cong">王聪</option></select></label>}
        <div className="member-session-actions">
          {!canManageMembers && <span className="member-readonly-notice">当前账号仅查看；请使用系统管理员账号编辑</span>}
          {canManageMembers && <Button appearance="primary" onClick={openCreate}>添加成员</Button>}
        </div>
      </div></div>
      <div className="account-management-table-wrap">{loading && !data ? <Skeleton className="loading"><SkeletonItem className="table-skeleton" /></Skeleton> : <table className="account-management-table member-management-table"><thead><tr><th>成员</th><th>登录账号</th><th>运营归属</th><th>直属主管</th><th>数据范围</th><th>导航权限</th><th>状态</th><th>最近修改</th><th>操作</th></tr></thead><tbody>
        {data?.rows.map((member) => <tr key={member.id}><td><strong>{member.display_name}</strong>{member.is_system_owner && <small className="member-owner-mark">系统管理员</small>}</td><td>{member.username}</td><td>{member.operator_name || "全部项目"}</td><td>{member.supervisor_name || "—"}</td><td>{scopeLabel(member.data_scope)}</td><td className="member-permission-summary" title={permissionSummary(member)}>{permissionSummary(member)}</td><td><Badge appearance="tint" color={member.is_active ? "success" : "subtle"}>{member.is_active ? "已启用" : "已停用"}</Badge></td><td>{formatDateTime(member.updated_at)}</td><td>{canManageMembers ? <Button size="small" appearance="secondary" onClick={() => openEdit(member)}>{member.is_system_owner ? "编辑账号" : "编辑"}</Button> : <span className="fixed-access">仅查看</span>}</td></tr>)}
        {!loading && !data?.rows.length && <tr><td className="account-management-empty" colSpan={9}>没有符合条件的成员</td></tr>}
      </tbody></table>}</div>
      <ViewportStickyPagination page={data?.page || page} totalPages={data?.total_pages || 1} total={data?.total || 0} pageSize={pageSize} loading={loading} ariaLabel="成员管理分页" onPageChange={setPage} onPageSizeChange={(size) => { setPageSize(size); setPage(1); }} />
    </section>

    <Dialog open={Boolean(editing) && !confirming} onOpenChange={(_, next) => { if (!busy && !next.open) setEditing(null); }}><DialogSurface className="member-dialog"><DialogBody>
      <DialogTitleWithSummary summary={editingOwner ? "只修改登录凭据；系统管理员身份和全部权限保持不变" : "普通成员都是运营；权限按当前项目独立生效"}>{editing === "new" ? "添加成员" : editingOwner ? "编辑系统管理员账号" : "编辑成员"}</DialogTitleWithSummary>
      <DialogContent><div className="member-form">{editingOwner ? <div className="member-form-grid member-owner-form">
        <label><span>登录账号</span><input value={draft.username} onChange={(event) => setDraft({ ...draft, username: event.target.value })} /></label>
        <label><span>新密码</span><input type="password" autoComplete="new-password" value={draft.password} onChange={(event) => setDraft({ ...draft, password: event.target.value })} placeholder="留空表示不修改" /></label>
        <div className="member-owner-fixed-note"><strong>固定内容</strong><span>身份：系统管理员</span><span>数据范围：项目全部账户</span><span>导航权限：全部管理</span></div>
      </div> : <><div className="member-form-grid">
        <label><span>成员姓名</span><input value={draft.display_name} onChange={(event) => setDraft({ ...draft, display_name: event.target.value })} /></label>
        <label><span>登录账号</span><input value={draft.username} onChange={(event) => setDraft({ ...draft, username: event.target.value })} placeholder="须与网页登录账号一致" /></label>
        <label><span>{editing === "new" ? "初始密码" : "新密码"}</span><input type="password" autoComplete="new-password" value={draft.password} onChange={(event) => setDraft({ ...draft, password: event.target.value })} placeholder={editing === "new" ? "至少 8 位" : "留空表示不修改"} /></label>
        <label><span>运营归属</span><input value={draft.operator_name} onChange={(event) => setDraft({ ...draft, operator_name: event.target.value })} /></label>
        <label><span>数据范围</span><select value={draft.data_scope} onChange={(event) => setDraft({ ...draft, data_scope: event.target.value as MemberDraft["data_scope"], supervisor_id: event.target.value === "self" ? draft.supervisor_id : "" })}><option value="self">仅本人运营账户</option><option value="team">本人及直属成员</option><option value="project">项目全部账户</option></select></label>
        <label><span>直属主管</span><select disabled={draft.data_scope !== "self"} value={draft.supervisor_id} onChange={(event) => setDraft({ ...draft, supervisor_id: event.target.value })}><option value="">不设置主管</option>{data?.supervisors.filter((item) => item.id !== (editing !== "new" ? editing?.id : "")).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        {editing !== "new" && <label><span>成员状态</span><select value={draft.is_active ? "enabled" : "disabled"} onChange={(event) => setDraft({ ...draft, is_active: event.target.value === "enabled" })}><option value="enabled">启用</option><option value="disabled">停用</option></select></label>}
      </div><div className="permission-matrix"><div className="permission-matrix-head"><span>导航模块</span><span>隐藏</span><span>查看</span><span>管理</span></div>{permissionRows.map((row) => <div className="permission-matrix-row" key={row.key}><span><strong>{row.label}</strong><small>{row.description}</small></span>{(["hidden", "view", "manage"] as PermissionLevel[]).map((level) => <label key={level}><input type="radio" name={row.key} checked={draft.permissions[row.key] === level} onChange={() => setPermission(row.key, level)} /><span>{level === "hidden" ? "隐藏" : level === "view" ? "查看" : "管理"}</span></label>)}</div>)}</div></>}</div></DialogContent>
      <DialogActions><Button appearance="secondary" disabled={busy} onClick={() => setEditing(null)}>取消</Button><Button appearance="primary" disabled={busy} onClick={() => setConfirming(true)}>检查并保存</Button></DialogActions>
    </DialogBody></DialogSurface></Dialog>
    <Dialog open={confirming} onOpenChange={(_, next) => { if (!busy) setConfirming(next.open); }}><DialogSurface className="member-confirm-dialog"><DialogBody>
      <DialogTitleWithSummary summary={editingOwner ? "保存后需要使用新凭据重新登录" : "保存后下一次请求立即生效"}>{editingOwner ? "确认修改登录账号" : "确认权限变化"}</DialogTitleWithSummary><DialogContent><div className="member-change-summary">{editing === "new" ? <p>将新增成员“{draft.display_name || draft.username}”。</p> : changes.length ? <ul>{changes.map((item) => <li key={item}>{item}</li>)}</ul> : <p>{editingOwner ? "没有填写新的修改内容。" : "没有权限或范围变化，将保存当前成员资料。"}</p>}{editingOwner && <p className="member-danger-note">系统管理员身份和权限不会改变。保存后当前登录会退出，请使用更新后的账号和密码重新登录。</p>}{!editingOwner && !draft.is_active && <p className="member-danger-note">停用后该成员将无法进入当前项目，未开始任务会被权限校验阻断。</p>}</div></DialogContent>
      <DialogActions><Button appearance="secondary" disabled={busy} onClick={() => setConfirming(false)}>返回修改</Button><Button appearance="primary" disabled={busy} onClick={() => void save()}>{busy ? "保存中…" : "确定"}</Button></DialogActions>
    </DialogBody></DialogSurface></Dialog>
  </>;
}
