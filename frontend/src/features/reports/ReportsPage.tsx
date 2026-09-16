import { useEffect, useState } from "react";
import { Button } from "@fluentui/react-components";
import { apiDownload, apiGet } from "../../api";
import { DateFilterGroup } from "../../components/DateFilterGroup";
import { PageHeader } from "../../components/PageHeader";
import { PopupMessage } from "../../components/PopupMessage";
import { SearchField } from "../../components/SearchField";
import { TableColumnFilter } from "../../components/TableColumnFilter";
import type { TableColumnFilterConfig } from "../../components/TableColumnFilter";
import { ViewportStickyPagination } from "../../components/ViewportStickyPagination";
import type { DailyReport, Project } from "../../types";

const REPORT_PAGE_SIZE = 20;
type SortKey = "cost_status" | "account_name" | "account_id" | "operator_name" | "manager_name" | "account_type" | "page_type" | "balance" | "impressions" | "clicks" | "spend" | "uv" | "copies" | "adds" | "cpc" | "uv_cost" | "copy_cost" | "add_cost" | "cash_spend" | "cash_copy_cost" | "cash_add_cost";
type ReportFilterKey = "costStatuses" | "operatorName" | "managerIds" | "accountTypes" | "pageTypes" | "accountNames";
type Options = { search: string; costStatus: string; managerIds: string; accountTypes: string; pageTypes: string; operatorName: string; accountNames: string; sortBy: SortKey; sortOrder: "asc" | "desc"; pageSize?: number };

const reportColumns = (isCopy: boolean): Array<{ key: SortKey; label: string; align: "start" | "end"; className: string; filterKey?: ReportFilterKey; sortable?: boolean }> => [
  { key: "cost_status", label: "成本判断", align: "start", className: "report-col-cost-status", filterKey: "costStatuses" },
  { key: "operator_name", label: "运营", align: "start", className: "report-col-operator", filterKey: "operatorName" },
  { key: "manager_name", label: "账户管家", align: "start", className: "report-col-manager", filterKey: "managerIds" },
  { key: "account_type", label: "账户类型", align: "start", className: "report-col-type", filterKey: "accountTypes" },
  { key: "page_type", label: "页面类型", align: "start", className: "report-col-page-type", filterKey: "pageTypes" },
  { key: "account_name", label: "账户", align: "start", className: "report-col-name", filterKey: "accountNames" },
  { key: "account_id", label: "账户ID", align: "start", className: "report-col-id" },
  { key: "balance", label: "余额", align: "end", className: "report-col-balance", sortable: true },
  { key: "impressions", label: "展现", align: "end", className: "report-col-impressions", sortable: true },
  { key: "clicks", label: "点击", align: "end", className: "report-col-clicks", sortable: true },
  { key: "spend", label: "消费", align: "end", className: "report-col-spend", sortable: true },
  { key: "uv", label: "UV", align: "end", className: "report-col-uv", sortable: true },
  { key: isCopy ? "copies" : "adds", label: isCopy ? "复制" : "加粉", align: "end", className: isCopy ? "report-col-copies" : "report-col-adds", sortable: true },
  { key: "cpc", label: "CPC", align: "end", className: "report-col-cpc", sortable: true },
  { key: "uv_cost", label: "UV成本", align: "end", className: "report-col-uv-cost", sortable: true },
  { key: isCopy ? "copy_cost" : "add_cost", label: isCopy ? "复制成本" : "加粉成本", align: "end", className: isCopy ? "report-col-copy-cost" : "report-col-add-cost", sortable: true },
  { key: "cash_spend", label: "现金消费", align: "end", className: "report-col-cash-spend", sortable: true },
  { key: isCopy ? "cash_copy_cost" : "cash_add_cost", label: isCopy ? "现金复制成本" : "现金加粉成本", align: "end", className: "report-col-cash-add-cost", sortable: true },
];

const toolbarFilterValue = (value: string) => value && !value.includes(",") ? value : "";

function dateInput(daysAgo: number) {
  const value = new Date();
  value.setDate(value.getDate() - daysAgo);
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}
function count(value: unknown) { return Number(value || 0).toLocaleString("zh-CN"); }
function money(value: string | null | undefined) { return value == null ? "—" : `¥ ${value}`; }
function overviewMoney(value: string | null | undefined) { return value == null ? "—" : `¥${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`; }

export function ReportsPage({ project, canManage }: { project: Project; canManage: boolean }) {
  const [dateFrom, setDateFrom] = useState(dateInput(0));
  const [dateTo, setDateTo] = useState(dateInput(0));
  const [report, setReport] = useState<DailyReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [costStatus, setCostStatus] = useState("");
  const [managerIds, setManagerIds] = useState("");
  const [accountTypes, setAccountTypes] = useState("");
  const [pageTypes, setPageTypes] = useState("");
  const [operatorName, setOperatorName] = useState("");
  const [accountNames, setAccountNames] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("spend");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [pageSize, setPageSize] = useState(REPORT_PAGE_SIZE);

  const options = (patch: Partial<Options> = {}): Options => ({ search, costStatus, managerIds, accountTypes, pageTypes, operatorName, accountNames, sortBy, sortOrder, ...patch });
  const load = async (page = 1, range = { from: dateFrom, to: dateTo }, requested = options()) => {
    setBusy(true); setError(null);
    try {
      const params = new URLSearchParams({ date_from: range.from, date_to: range.to, page: String(page), page_size: String(requested.pageSize ?? pageSize), sort_by: requested.sortBy, sort_order: requested.sortOrder });
      if (requested.search) params.set("search", requested.search);
      if (requested.costStatus) params.set("cost_statuses", requested.costStatus);
      if (requested.managerIds) params.set("manager_ids", requested.managerIds);
      if (requested.accountTypes) params.set("account_types", requested.accountTypes);
      if (requested.pageTypes) params.set("page_types", requested.pageTypes);
      if (requested.operatorName) params.set("operator_names", requested.operatorName);
      if (requested.accountNames) params.set("account_names", requested.accountNames);
      setReport(await apiGet<DailyReport>(`/projects/${project.id}/reports/daily?${params}`));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "报表读取失败"); }
    finally { setBusy(false); }
  };

  useEffect(() => {
    setSearchInput(""); setSearch(""); setCostStatus(""); setManagerIds(""); setAccountTypes(""); setPageTypes(""); setOperatorName(""); setAccountNames("");
    void load(1, { from: dateFrom, to: dateTo }, options({ search: "", costStatus: "", managerIds: "", accountTypes: "", pageTypes: "", operatorName: "", accountNames: "" }));
  }, [project.id]);

  const update = (patch: Partial<Options>) => void load(1, { from: dateFrom, to: dateTo }, options(patch));
  const download = async () => {
    try {
      const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo, sort_by: sortBy, sort_order: sortOrder });
      if (search) params.set("search", search); if (costStatus) params.set("cost_statuses", costStatus); if (managerIds) params.set("manager_ids", managerIds); if (accountTypes) params.set("account_types", accountTypes); if (pageTypes) params.set("page_types", pageTypes); if (operatorName) params.set("operator_names", operatorName); if (accountNames) params.set("account_names", accountNames);
      await apiDownload(`/projects/${project.id}/reports/daily.xlsx?${params}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "导出失败"); }
  };
  const changeSort = (next: SortKey) => {
    const order: "asc" | "desc" = sortBy === next ? sortOrder === "desc" ? "asc" : "desc" : next === "account_id" ? "asc" : "desc";
    setSortBy(next); setSortOrder(order); update({ sortBy: next, sortOrder: order });
  };

  const summary = report?.summary;
  const isCopyJudgment = report?.cost_judgment.mode === "copy_cash";
  const columns = reportColumns(isCopyJudgment);
  const overview = [
    ["impressions", "展现", count(summary?.impressions)], ["clicks", "点击", count(summary?.clicks)], ["spend", "消费", overviewMoney(summary?.spend)],
    ["uv", "UV", count(summary?.uv)], [isCopyJudgment ? "copies" : "adds", isCopyJudgment ? "复制" : "加粉", count(isCopyJudgment ? summary?.copies : summary?.adds)],
    ["cpc", "CPC", overviewMoney(summary?.cpc)], ["uv_cost", "UV成本", overviewMoney(summary?.uv_cost)], [isCopyJudgment ? "copy_cost" : "add_cost", isCopyJudgment ? "复制成本" : "加粉成本", overviewMoney(isCopyJudgment ? summary?.copy_cost : summary?.add_cost)],
    ["cash_spend", "现金消费", overviewMoney(summary?.cash_spend)], [isCopyJudgment ? "cash_copy_cost" : "cash_add_cost", isCopyJudgment ? "现金复制成本" : "现金加粉成本", overviewMoney(isCopyJudgment ? summary?.cash_copy_cost : summary?.cash_add_cost)],
  ] as const;
  const applyFilter = (key: ReportFilterKey, value: string) => {
    if (key === "operatorName") setOperatorName(value);
    if (key === "managerIds") setManagerIds(value);
    if (key === "accountTypes") setAccountTypes(value);
    if (key === "pageTypes") setPageTypes(value);
    if (key === "accountNames") setAccountNames(value);
    update({ [key]: value });
  };
  const columnFilters: Record<ReportFilterKey, TableColumnFilterConfig> = {
    costStatuses: { label: "成本判断", value: costStatus, options: ["冷启动期", "空耗", "成本高", "成本上涨", "成本合格", "待判断"].map(item => [item, item]), onChange: value => { setCostStatus(value); update({ costStatus: value }); } },
    operatorName: { label: "运营", value: operatorName, options: [["__unassigned__", "未设置"], ...(report?.operator_names || []).map(item => [item, item])], onChange: value => applyFilter("operatorName", value) },
    managerIds: { label: "账户管家", value: managerIds, options: (report?.managers || []).map(item => [item.id, item.name]), onChange: value => applyFilter("managerIds", value) },
    accountTypes: { label: "账户类型", value: accountTypes, options: (report?.account_types || []).map(item => [item, item]), onChange: value => applyFilter("accountTypes", value) },
    pageTypes: { label: "页面类型", value: pageTypes, options: (report?.page_types || []).map(item => [item, item]), onChange: value => applyFilter("pageTypes", value) },
    accountNames: { label: "账户", value: accountNames, options: (report?.account_names || []).map(item => [item, item]), onChange: value => applyFilter("accountNames", value) },
  };

  return <>
    <PageHeader title="数据报表" description="账户维度投放数据与转化表现" />
    <section className="account-management-frame account-page-operations report-workspace">
      <div className="account-management-view-controls"><div className="account-management-toolbar">
        <div className="account-management-date"><DateFilterGroup valueFrom={dateFrom} valueTo={dateTo} disabled={busy} onChange={({ from, to }) => { setDateFrom(from); setDateTo(to); }} onApply={(range) => void load(1, range)} /></div>
        <div className="account-management-actions account-management-query-actions">
          <div className="account-toolbar-filters">
            <label className="account-toolbar-filter"><span>成本判断</span><select value={toolbarFilterValue(costStatus)} disabled={busy} onChange={e => { setCostStatus(e.target.value); update({ costStatus: e.target.value }); }}><option value="">全部</option>{["冷启动期", "空耗", "成本高", "成本上涨", "成本合格", "待判断"].map(item => <option key={item}>{item}</option>)}</select></label>
            <label className="account-toolbar-filter"><span>运营</span><select value={toolbarFilterValue(operatorName)} disabled={busy} onChange={e => applyFilter("operatorName", e.target.value)}><option value="">全部</option>{report?.operator_names.map(item => <option key={item} value={item}>{item}</option>)}{report?.has_unassigned_operator && <option value="__unassigned__">未设置</option>}</select></label>
            <label className="account-toolbar-filter"><span>页面类型</span><select value={toolbarFilterValue(pageTypes)} disabled={busy} onChange={e => applyFilter("pageTypes", e.target.value)}><option value="">全部</option>{report?.page_types.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
          </div>
          {canManage && <Button size="small" appearance="secondary" disabled={!report?.total} onClick={() => void download()}>下载报表</Button>}
          <div className="account-management-search"><SearchField value={searchInput} placeholder="账户名称 / 账户ID" onChange={setSearchInput} onSearch={() => { const value = searchInput.trim(); setSearch(value); update({ search: value }); }} onClear={() => { setSearchInput(""); setSearch(""); update({ search: "" }); }} disabled={busy} /></div>
          <Button className="toolbar-refresh-button" size="small" appearance="secondary" aria-label="刷新" title="刷新" disabled={busy} onClick={() => void load(1)}><span aria-hidden="true">↻</span></Button>
        </div>
      </div></div>
      {error && <PopupMessage intent="error">{error}</PopupMessage>}
      <section className="account-list-overview" aria-label="数据报表概览" aria-busy={busy}>{overview.map(([key, label, value]) => { const trend = report?.comparison?.trends[key]; const trendValue = trend?.percent == null ? "—" : `${trend.direction === "up" ? "▲" : trend.direction === "down" ? "▼" : "—"} ${trend.percent}%`; return <div key={key}><span>{label}</span><strong>{value}</strong><em className={`account-list-overview-trend ${trend?.direction || "muted"}`}><b>{trendValue}</b><small>环比上周期</small></em></div>; })}</section>
      <div className="account-management-table-wrap"><table className="account-management-table account-list-table report-account-table">
        <thead><tr>{columns.map(column => <th key={column.key} className={`${column.className} table-cell--${column.align}`}>{column.filterKey ? <TableColumnFilter filter={columnFilters[column.filterKey]} /> : column.sortable ? <button type="button" className={`data-sort${sortBy === column.key ? " is-active" : ""}`} onClick={() => changeSort(column.key)}>{column.label}{sortBy === column.key ? <i aria-hidden="true">{sortOrder === "asc" ? "↑" : "↓"}</i> : null}</button> : column.label}</th>)}</tr></thead>
        <tbody>{report?.rows.map(row => <tr key={`${row.date}-${row.account_id}`}>
          <td>{row.cost_status}</td><td>{row.operator_name || "未设置"}</td><td>{row.manager_name || "—"}</td><td>{row.account_type || "—"}</td><td>{row.page_type || "—"}</td>
          <td title={row.account_name}><a className="report-account-link" href={`https://qingge.baidu.com/ad/manageCenter/campaignList?userId=${encodeURIComponent(String(row.account_id))}&globalProduct=1`} target="_blank" rel="noopener noreferrer">{row.account_name}</a></td><td>{row.account_id}</td>
          <td className="number-cell">{money(row.balance)}</td><td className="number-cell">{count(row.impressions)}</td><td className="number-cell">{count(row.clicks)}</td><td className="number-cell">{money(row.spend)}</td><td className="number-cell">{count(row.uv)}</td><td className="number-cell">{count(isCopyJudgment ? row.copies : row.adds)}</td><td className="number-cell">{money(row.cpc)}</td><td className="number-cell">{money(row.uv_cost)}</td><td className="number-cell">{money(isCopyJudgment ? row.copy_cost : row.add_cost)}</td><td className="number-cell">{money(row.cash_spend)}</td><td className="number-cell">{money(isCopyJudgment ? row.cash_copy_cost : row.cash_add_cost)}</td>
        </tr>)}</tbody>
      </table></div>
      <ViewportStickyPagination page={report?.page || 1} totalPages={report?.total_pages || 1} total={report?.total || 0} pageSize={report?.page_size || pageSize} loading={busy} ariaLabel="账户日报分页" onPageChange={page => void load(page)} onPageSizeChange={size => { setPageSize(size); void load(1, { from: dateFrom, to: dateTo }, options({ pageSize: size })); }} />
    </section>
  </>;
}
