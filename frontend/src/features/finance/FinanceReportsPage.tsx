import { useEffect, useMemo, useState } from "react";
import { Button, Input } from "@fluentui/react-components";
import { apiGet, apiPatch } from "../../api";
import { DateFilterGroup } from "../../components/DateFilterGroup";
import { PageHeader } from "../../components/PageHeader";
import { PopupMessage } from "../../components/PopupMessage";
import { SearchField } from "../../components/SearchField";
import { ViewportStickyPagination } from "../../components/ViewportStickyPagination";
import type { ProfitReport, Project, RechargeReconciliationReport } from "../../types";

type FinanceTab = "recharge" | "profit";
const PAGE_SIZE = 20;

function today() {
  const value = new Date();
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function money(value: string | null | undefined) {
  if (value == null || value === "") return "—";
  return `¥ ${Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function RechargeTab({ project }: { project: Project }) {
  const [dateFrom, setDateFrom] = useState(today());
  const [dateTo, setDateTo] = useState(today());
  const [movement, setMovement] = useState<"" | "recharge" | "refund">("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [data, setData] = useState<RechargeReconciliationReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (requestedPage = page, patch: { from?: string; to?: string; movement?: string; search?: string; pageSize?: number } = {}) => {
    setBusy(true); setError(null);
    const params = new URLSearchParams({
      date_from: patch.from ?? dateFrom,
      date_to: patch.to ?? dateTo,
      page: String(requestedPage),
      page_size: String(patch.pageSize ?? pageSize),
    });
    const requestedMovement = patch.movement ?? movement;
    const requestedSearch = patch.search ?? search;
    if (requestedMovement) params.set("movement_type", requestedMovement);
    if (requestedSearch) params.set("search", requestedSearch);
    try {
      setData(await apiGet<RechargeReconciliationReport>(`/projects/${project.id}/finance/recharge-reconciliation?${params}`));
      setPage(requestedPage);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "充值对账读取失败"); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(1); }, [project.id]);

  const selectMovement = (next: "" | "recharge" | "refund") => {
    setMovement(next); setPage(1); void load(1, { movement: next });
  };
  const submitSearch = () => {
    const next = searchInput.trim(); setSearch(next); setPage(1); void load(1, { search: next });
  };
  return <section className="account-management-frame finance-workspace">
    <div className="account-management-view-controls"><div className="account-management-toolbar finance-toolbar">
      <DateFilterGroup valueFrom={dateFrom} valueTo={dateTo} disabled={busy} onChange={({ from, to }) => { setDateFrom(from); setDateTo(to); }} onApply={({ from, to }) => { setPage(1); void load(1, { from, to }); }} />
      <div className="finance-toolbar-actions">
        <div className="finance-segmented" role="group" aria-label="充值类型筛选">
          {([["", "全部"], ["recharge", "充值"], ["refund", "退款"]] as const).map(([value, label]) => <button key={label} type="button" className={movement === value ? "active" : ""} onClick={() => selectMovement(value)}>{label}</button>)}
        </div>
        <SearchField ariaLabel="搜索充值对账" value={searchInput} placeholder="账户名称 / 账户ID / 管家" onChange={setSearchInput} onSearch={submitSearch} onClear={() => { setSearchInput(""); setSearch(""); void load(1, { search: "" }); }} disabled={busy} />
        <Button className="toolbar-refresh-button" size="small" appearance="secondary" aria-label="刷新" disabled={busy} onClick={() => void load(1)}>↻</Button>
      </div>
    </div></div>
    {error && <PopupMessage intent="error">{error}</PopupMessage>}
    <div className="account-management-table-wrap"><table className="account-management-table finance-table">
      <thead><tr><th>日期</th><th>账户名称</th><th>类型</th><th className="table-cell--end">账户币求和</th><th className="table-cell--end">返点</th><th className="table-cell--end">现金求和</th></tr></thead>
      <tbody>
        <tr className="finance-summary-row"><td>汇总</td><td>当前筛选共 {data?.total ?? 0} 条</td><td>—</td><td className="number-cell">{money(data?.summary.account_currency)}</td><td className="number-cell">—</td><td className="number-cell">{money(data?.summary.cash_amount)}</td></tr>
        {data?.rows.map(row => <tr key={`${row.date}-${row.account_id}-${row.movement_type}`}><td>{row.date}</td><td><strong>{row.account_name}</strong><small>{row.account_id}</small></td><td><span className={`finance-type finance-type--${row.movement_type}`}>{row.type}</span></td><td className="number-cell">{money(row.account_currency)}</td><td className="number-cell">{row.rebate_rate == null ? "—" : `${Number(row.rebate_rate)}%`}</td><td className="number-cell">{money(row.cash_amount)}</td></tr>)}
        {!busy && !data?.rows.length && <tr><td className="account-management-empty" colSpan={6}>当前日期和筛选条件没有充值或退款流水</td></tr>}
      </tbody>
    </table></div>
    <ViewportStickyPagination page={data?.page || page} totalPages={data?.total_pages || 1} total={data?.total || 0} pageSize={data?.page_size || pageSize} loading={busy} ariaLabel="充值对账分页" onPageChange={next => void load(next)} onPageSizeChange={size => { setPageSize(size); void load(1, { pageSize: size }); }} />
  </section>;
}

function ProfitTab({ project, canManage }: { project: Project; canManage: boolean }) {
  const [dateFrom, setDateFrom] = useState(today());
  const [dateTo, setDateTo] = useState(today());
  const [operatorName, setOperatorName] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [data, setData] = useState<ProfitReport | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = async (requestedPage = page, patch: { from?: string; to?: string; operator?: string; search?: string; pageSize?: number } = {}) => {
    setBusy(true); setError(null); setNotice(null);
    const params = new URLSearchParams({ date_from: patch.from ?? dateFrom, date_to: patch.to ?? dateTo, page: String(requestedPage), page_size: String(patch.pageSize ?? pageSize) });
    const requestedOperator = patch.operator ?? operatorName;
    const requestedSearch = patch.search ?? search;
    if (requestedOperator) params.set("operator_name", requestedOperator);
    if (requestedSearch) params.set("search", requestedSearch);
    try {
      const next = await apiGet<ProfitReport>(`/projects/${project.id}/finance/profit?${params}`);
      setData(next); setDrafts(Object.fromEntries(next.rows.map(row => [row.date, row.reported_spend ?? ""]))); setPage(requestedPage);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "利润报表读取失败"); }
    finally { setBusy(false); }
  };
  useEffect(() => { setEditing(false); void load(1); }, [project.id]);
  const selectOperator = (next: string) => { setOperatorName(next); setEditing(false); setPage(1); void load(1, { operator: next }); };
  const submitSearch = () => { const next = searchInput.trim(); setSearch(next); setEditing(false); void load(1, { search: next }); };
  const save = async () => {
    const rows = Object.entries(drafts).filter(([, value]) => value.trim() !== "").map(([report_date, value]) => ({ report_date, reported_spend: Number(value) }));
    if (rows.some(row => !Number.isFinite(row.reported_spend) || row.reported_spend < 0)) { setError("报消耗必须是大于等于 0 的有效金额"); return; }
    if (!rows.length) { setError("请至少填写一天的报消耗"); return; }
    setBusy(true); setError(null);
    try {
      await apiPatch(`/projects/${project.id}/finance/profit`, { operator_name: operatorName || null, rows });
      setEditing(false); setNotice("报消耗已保存，成本和利润已重新计算"); await load(page);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "利润报表保存失败"); }
    finally { setBusy(false); }
  };
  const isCopy = data?.metric_mode === "copy";
  const conversionLabel = isCopy ? "复制" : "加粉";
  const operators = useMemo(() => data?.operator_names || [], [data?.operator_names]);
  return <section className="account-management-frame finance-workspace">
    <div className="account-management-view-controls"><div className="account-management-toolbar finance-toolbar">
      <DateFilterGroup valueFrom={dateFrom} valueTo={dateTo} disabled={busy} onChange={({ from, to }) => { setDateFrom(from); setDateTo(to); }} onApply={({ from, to }) => { setEditing(false); setPage(1); void load(1, { from, to }); }} />
      <div className="finance-toolbar-actions">
        {canManage && (editing ? <div className="finance-edit-actions"><Button size="small" appearance="secondary" disabled={busy} onClick={() => { setEditing(false); setDrafts(Object.fromEntries((data?.rows || []).map(row => [row.date, row.reported_spend ?? ""]))); }}>取消</Button><Button size="small" appearance="primary" disabled={busy} onClick={() => void save()}>{busy ? "保存中…" : "保存"}</Button></div> : <Button size="small" appearance="secondary" disabled={busy || !data?.rows.length} onClick={() => setEditing(true)}>编辑</Button>)}
        <div className="finance-segmented finance-operator-segmented" role="group" aria-label="运营筛选"><button type="button" className={!operatorName ? "active" : ""} onClick={() => selectOperator("")}>全部</button>{operators.map(item => <button key={item} type="button" className={operatorName === item ? "active" : ""} onClick={() => selectOperator(item)}>{item}</button>)}</div>
        <SearchField ariaLabel="搜索利润报表" value={searchInput} placeholder="日期 / 项目名称" onChange={setSearchInput} onSearch={submitSearch} onClear={() => { setSearchInput(""); setSearch(""); void load(1, { search: "" }); }} disabled={busy} />
        <Button className="toolbar-refresh-button" size="small" appearance="secondary" aria-label="刷新" disabled={busy} onClick={() => void load(1)}>↻</Button>
      </div>
    </div></div>
    {error && <PopupMessage intent="error">{error}</PopupMessage>}{notice && <PopupMessage intent="success">{notice}</PopupMessage>}
    <div className="account-management-table-wrap"><table className="account-management-table finance-table profit-table">
      <thead><tr><th>日期</th><th>项目名称</th><th className="table-cell--end">报消耗</th><th className="table-cell--end">报{conversionLabel}</th><th className="table-cell--end">报{conversionLabel}成本</th><th className="table-cell--end">账户消耗</th><th className="table-cell--end">现金消耗</th><th className="table-cell--end">现金{conversionLabel}成本</th><th className="table-cell--end">利润</th></tr></thead>
      <tbody>
        <tr className="finance-summary-row"><td>汇总</td><td>{operatorName || "全部运营"}</td><td className="number-cell">{money(data?.summary.reported_spend)}</td><td className="number-cell">{Number(data?.summary.conversions || 0).toLocaleString("zh-CN")}</td><td className="number-cell">{money(data?.summary.reported_conversion_cost)}</td><td className="number-cell">{money(data?.summary.account_spend)}</td><td className="number-cell">{money(data?.summary.cash_spend)}</td><td className="number-cell">{money(data?.summary.cash_conversion_cost)}</td><td className="number-cell finance-profit-value">{money(data?.summary.profit)}</td></tr>
        {data?.rows.map(row => <tr key={row.date}><td>{row.date}</td><td>{row.project_name}</td><td className="number-cell">{editing ? <Input className="finance-money-input" type="number" min={0} step="0.01" value={drafts[row.date] ?? ""} onChange={(_, next) => setDrafts(current => ({ ...current, [row.date]: next.value }))} placeholder="填写报消耗" /> : money(row.reported_spend)}</td><td className="number-cell">{row.conversions.toLocaleString("zh-CN")}</td><td className="number-cell">{money(row.reported_conversion_cost)}</td><td className="number-cell">{money(row.account_spend)}</td><td className="number-cell">{money(row.cash_spend)}</td><td className="number-cell">{money(row.cash_conversion_cost)}</td><td className="number-cell finance-profit-value">{money(row.profit)}</td></tr>)}
        {!busy && !data?.rows.length && <tr><td className="account-management-empty" colSpan={9}>当前日期范围没有产生消耗的数据</td></tr>}
      </tbody>
    </table></div>
    <ViewportStickyPagination page={data?.page || page} totalPages={data?.total_pages || 1} total={data?.total || 0} pageSize={data?.page_size || pageSize} loading={busy} ariaLabel="利润报表分页" onPageChange={next => { setEditing(false); void load(next); }} onPageSizeChange={size => { setPageSize(size); setEditing(false); void load(1, { pageSize: size }); }} />
  </section>;
}

export function FinanceReportsPage({ project, canManage }: { project: Project; canManage: boolean }) {
  const [tab, setTab] = useState<FinanceTab>("recharge");
  return <>
    <PageHeader title="财务报表" description="充值退款对账与项目利润核算" />
    <div className="finance-tabs" role="tablist" aria-label="财务报表页签"><button type="button" role="tab" aria-selected={tab === "recharge"} className={tab === "recharge" ? "active" : ""} onClick={() => setTab("recharge")}>充值对账</button><button type="button" role="tab" aria-selected={tab === "profit"} className={tab === "profit" ? "active" : ""} onClick={() => setTab("profit")}>利润报表</button></div>
    {tab === "recharge" ? <RechargeTab project={project} /> : <ProfitTab project={project} canManage={canManage} />}
  </>;
}
