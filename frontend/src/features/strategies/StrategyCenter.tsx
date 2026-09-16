import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  Field,
  Input,
  Skeleton,
  SkeletonItem,
} from "@fluentui/react-components";
import { apiGet, apiPost, apiPut } from "../../api";
import { PopupMessage } from "../../components/PopupMessage";
import { DialogTitleWithSummary } from "../../components/DialogTitleWithSummary";
import { moveHorizontalTab } from "../../components/tabNavigation";
import { getUiTimeZone } from "../../uiTimeZone";
import type {
  AdBuildPlanSettings,
  Project,
  StrategyConfigValue,
  StrategyEvaluation,
  StrategyPolicy,
  StrategyRoundAmount,
  StrategyVersion,
} from "../../types";

type StrategyKey = "budget_reset" | "budget_append" | "elimination";
export type GlobalJudgmentAction = "account-status" | "cost-judgment" | "loop-check";
export type StrategyAction = StrategyKey | GlobalJudgmentAction | "build-settings";
export type GlobalRuleContext = {
  config: StrategyVersion["config"];
  editing: boolean;
  busy: boolean;
  update: (key: string, value: StrategyConfigValue) => void;
};
type StrategyPane = "rules" | "records";
type ExecutionMode = "off" | "suggest" | "confirm" | "auto";
type ExecutionCycle = "global" | "closed_loop" | "daily" | "periodic";

const executionModeOptions: Array<{ value: ExecutionMode; label: string }> = [
  { value: "off", label: "关闭" },
  { value: "suggest", label: "仅建议" },
  { value: "confirm", label: "人工确认" },
  { value: "auto", label: "自动执行" },
];
const executionCycleOptions: Array<{ value: ExecutionCycle; label: string }> = [
  { value: "global", label: "全局执行" },
  { value: "closed_loop", label: "闭环周期" },
  { value: "daily", label: "每日执行" },
  { value: "periodic", label: "周期执行" },
];

const strategyActions: StrategyAction[] = [
  "build-settings",
  "budget_append",
  "budget_reset",
  "elimination",
  "account-status",
  "cost-judgment",
  "loop-check",
];

function readStrategyView(): { action: StrategyAction; pane: StrategyPane } {
  try {
    const query = new URLSearchParams(window.location.search);
    const requestedAction = query.get("strategy_action");
    const requestedPane = query.get("strategy_pane");
    const action = strategyActions.includes(requestedAction as StrategyAction)
      ? requestedAction as StrategyAction
      : "build-settings";
    const supportsRecords = action === "budget_append" || action === "budget_reset" || action === "elimination";
    return {
      action,
      pane: requestedPane === "records" && supportsRecords ? "records" : "rules",
    };
  } catch {
    return { action: "build-settings", pane: "rules" };
  }
}

function saveStrategyView(action: StrategyAction, pane: StrategyPane) {
  try {
    const url = new URL(window.location.href);
    url.searchParams.set("strategy_action", action);
    url.searchParams.set("strategy_pane", pane);
    window.history.replaceState(
      window.history.state,
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  } catch {
    // The page still works when browser storage is unavailable.
  }
}

const strategyMeta: Record<
  StrategyKey,
  { name: string; description: string; effect: string }
> = {
  budget_reset: {
    name: "预算重置",
    description: "触发条件满足后，将账户日预算固定为填写金额",
    effect: "固定冷启动期账户日预算",
  },
  budget_append: {
    name: "预算追加",
    description: "成本和预算利用率同时达标后立即执行追加",
    effect: "按边际效果追加预算",
  },
  elimination: {
    name: "账户淘汰",
    description: "达到淘汰阈值后直接暂停账户全部计划，等待人工最终确认",
    effect: "暂停账户全部计划",
  },
};

const globalJudgmentMeta: Record<
  GlobalJudgmentAction,
  { name: string; description: string; cycle: string; strategyKey: "account_status" | "cost_judgment" | "realtime_closure" }
> = {
  "account-status": {
    name: "账户状态",
    description: "根据账户、计划、历史数据与自动上线分配统一判定账户状态。",
    cycle: "数据刷新后",
    strategyKey: "account_status",
  },
  "cost-judgment": {
    name: "成本判断",
    description: "分别维护加粉现金成本与复制现金成本的判定标准。",
    cycle: "数据刷新后",
    strategyKey: "cost_judgment",
  },
  "loop-check": {
    name: "实时闭环",
    description: "项目刷新、运行保护和闭环状态统一管理。",
    cycle: "实时闭环",
    strategyKey: "realtime_closure",
  },
};

const fieldMeta: Record<
  string,
  { label: string; suffix?: string; step?: string; description?: string }
> = {
  target_budget: { label: "固定日预算", suffix: "元", step: "0.01" },
  add_cost_limit: { label: "加粉成本上限", suffix: "元", step: "0.01" },
  utilization_limit: { label: "预算利用率", suffix: "%", step: "0.1" },
  spend_without_add_limit: {
    label: "无加粉消费阈值",
    suffix: "元",
    step: "0.01",
  },
};

function cloneConfig(config: StrategyVersion["config"]) {
  return JSON.parse(JSON.stringify(config)) as StrategyVersion["config"];
}

function utilizationPercent(value: StrategyConfigValue | undefined) {
  const ratio = Number(value);
  return Number.isFinite(ratio) ? String(ratio * 100) : "";
}

function utilizationRatio(value: string) {
  if (!value.trim()) return "";
  const percent = Number(value);
  return Number.isFinite(percent) ? String(percent / 100) : value;
}

function cloneBuildPlanSettings(settings: AdBuildPlanSettings) {
  return JSON.parse(JSON.stringify(settings)) as AdBuildPlanSettings;
}

function formatVersionCode(version?: StrategyVersion | null) {
  if (!version) return "—";
  const value = version.published_at || version.created_at;
  if (!value) return `V${version.version}`;
  const parts = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: getUiTimeZone(),
  }).formatToParts(new Date(value));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";
  return `V${version.version}.${part("year")}${part("month")}${part("day")}${part("hour")}${part("minute")}`;
}

export function StrategyCenter({
  project,
  renderRecords,
  renderGlobal,
  requestedAction,
  embedded = false,
}: {
  project: Project;
  renderRecords?: (action: StrategyAction) => ReactNode;
  renderGlobal?: (action: GlobalJudgmentAction, context: GlobalRuleContext) => ReactNode;
  requestedAction?: StrategyAction;
  embedded?: boolean;
}) {
  const [initialView] = useState(readStrategyView);
  const [policies, setPolicies] = useState<StrategyPolicy[]>([]);
  const [selectedKey, setSelectedKey] = useState<StrategyKey>(() =>
    initialView.action === "budget_append" ||
    initialView.action === "budget_reset" ||
    initialView.action === "elimination"
      ? initialView.action
      : "budget_append",
  );
  const [draft, setDraft] = useState<StrategyVersion["config"]>({});
  const [evaluation, setEvaluation] = useState<StrategyEvaluation | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{
    intent: "success" | "error" | "info";
    text: string;
  } | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [buildPublishOpen, setBuildPublishOpen] = useState(false);
  const [globalAction, setGlobalAction] = useState<GlobalJudgmentAction | null>(() =>
    initialView.action === "account-status" ||
    initialView.action === "cost-judgment" ||
    initialView.action === "loop-check"
      ? initialView.action
      : null,
  );
  const [buildSettingsSelected, setBuildSettingsSelected] = useState(
    initialView.action === "build-settings",
  );
  const [buildPlanSettings, setBuildPlanSettings] =
    useState<AdBuildPlanSettings | null>(null);
  const [savedBuildPlanSettings, setSavedBuildPlanSettings] =
    useState<AdBuildPlanSettings | null>(null);
  const [pane, setPane] = useState<StrategyPane>(initialView.pane);
  const [editing, setEditing] = useState(false);
  const globalSelected = globalAction !== null;
  const action: StrategyAction = buildSettingsSelected
    ? "build-settings"
    : globalAction
      ? globalAction
      : selectedKey;
  const actionName = buildSettingsSelected
    ? "搭建设置"
    : globalAction
      ? globalJudgmentMeta[globalAction].name
      : strategyMeta[selectedKey].name;
  const selectedPolicyKey = globalAction
    ? globalJudgmentMeta[globalAction].strategyKey
    : selectedKey;
  const selectAction = (next: StrategyAction) => {
    const nextGlobal = next === "account-status" || next === "cost-judgment" || next === "loop-check"
      ? next
      : null;
    const nextPolicyKey = nextGlobal
      ? globalJudgmentMeta[nextGlobal].strategyKey
      : next === "build-settings"
        ? null
        : next as StrategyKey;
    const nextPolicy = nextPolicyKey
      ? policies.find((item) => item.key === nextPolicyKey)
      : null;
    const nextEffective = nextPolicy?.draft || nextPolicy?.active;
    setGlobalAction(nextGlobal);
    setBuildSettingsSelected(next === "build-settings");
    if (!nextGlobal && next !== "build-settings") setSelectedKey(next as StrategyKey);
    setPane("rules");
    setEditing(false);
    setMessage(null);
    if (nextEffective) setDraft(cloneConfig(nextEffective.config));
  };

  const policy = policies.find((item) => item.key === selectedPolicyKey);
  const effective = policy?.draft || policy?.active;
  const dirty = useMemo(
    () =>
      Boolean(
        effective && JSON.stringify(draft) !== JSON.stringify(effective.config),
      ),
    [draft, effective],
  );

  const load = async () => {
    setLoading(true);
    try {
      const rows = await apiGet<StrategyPolicy[]>(
        `/projects/${project.id}/strategies`,
      );
      setPolicies(rows);
      setMessage(null);
    } catch (reason) {
      setMessage({
        intent: "error",
        text: reason instanceof Error ? reason.message : "策略读取失败",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [project.id]);
  useEffect(() => {
    saveStrategyView(action, pane);
  }, [action, pane]);
  useEffect(() => {
    if (
      requestedAction !== "account-status" &&
      requestedAction !== "cost-judgment" &&
      requestedAction !== "loop-check"
    ) return;
    setGlobalAction(requestedAction);
    setPane("rules");
    setEditing(false);
    setMessage(null);
  }, [project.id, requestedAction]);
  useEffect(() => {
    if (!effective) return;
    setDraft(cloneConfig(effective.config));
    setEvaluation(null);
  }, [project.id, selectedPolicyKey, effective?.id]);

  const update = (key: string, value: StrategyConfigValue) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setEvaluation(null);
    setMessage(null);
  };
  const saveRule = async () => {
    if (!policy || (!dirty && !globalSelected)) return;
    setBusy("save-rule");
    try {
      const next = await apiPut<StrategyPolicy>(
        `/projects/${project.id}/strategies/${selectedPolicyKey}/draft`,
        { config: draft, expected_revision: policy.revision },
      );
      setPolicies((rows) =>
        rows.map((item) => (item.key === selectedPolicyKey ? next : item)),
      );
      setDraft(cloneConfig((next.draft || next.active).config));
      setEditing(false);
      setEvaluation(null);
      setMessage({
        intent: "success",
        text: "规则已保存为草稿，线上规则未改变；发布规则后才会正式生效",
      });
    } catch (reason) {
      setMessage({
        intent: "error",
        text: reason instanceof Error ? reason.message : "保存规则失败",
      });
    } finally {
      setBusy(null);
    }
  };
  const cancelRuleEditing = () => {
    if (effective) setDraft(cloneConfig(effective.config));
    setEditing(false);
    setMessage(null);
  };
  const preparePublish = async () => {
    if (!policy) return;
    setBusy("prepare-publish");
    try {
      let current = policy;
      if (dirty || !policy.draft) {
        current = await apiPut<StrategyPolicy>(
          `/projects/${project.id}/strategies/${selectedPolicyKey}/draft`,
          { config: draft, expected_revision: policy.revision },
        );
        setPolicies((rows) =>
          rows.map((item) => (item.key === selectedPolicyKey ? current : item)),
        );
      }
      const result = await apiPost<StrategyEvaluation>(
        `/projects/${project.id}/strategies/${selectedPolicyKey}/dry-run`,
        {},
      );
      setEvaluation(result);
      setMessage(null);
      setPublishOpen(true);
    } catch (reason) {
      setMessage({
        intent: "error",
        text: reason instanceof Error ? reason.message : "发布准备失败",
      });
    } finally {
      setBusy(null);
    }
  };
  const publish = async () => {
    if (!policy || !evaluation) return;
    setBusy("publish");
    try {
      const next = await apiPost<StrategyPolicy>(
        `/projects/${project.id}/strategies/${selectedPolicyKey}/publish`,
        { expected_revision: policy.revision, evaluation_id: evaluation.id },
      );
      setPolicies((rows) =>
        rows.map((item) => (item.key === selectedPolicyKey ? next : item)),
      );
      setPublishOpen(false);
      setEditing(false);
      setEvaluation(null);
      setMessage({
        intent: "success",
        text: `版本 v${next.active.version} 已发布，将从下一调度时间起生效`,
      });
    } catch (reason) {
      setMessage({
        intent: "error",
        text: reason instanceof Error ? reason.message : "策略发布失败",
      });
    } finally {
      setBusy(null);
    }
  };
  const loadSavedBuildPlanSettings = async () => {
    setBusy("load-saved-build-settings");
    try {
      const result = await apiGet<AdBuildPlanSettings>(
        `/projects/${project.id}/ad-build-plan-settings`,
      );
      setBuildPlanSettings(result);
      setSavedBuildPlanSettings(cloneBuildPlanSettings(result));
      setEditing(false);
    } catch (reason) {
      setMessage({
        intent: "error",
        text: reason instanceof Error ? reason.message : "读取已保存搭建规则失败",
      });
    } finally {
      setBusy(null);
    }
  };

  const readMaterialBuildPlans = async () => {
    setBusy("load-build-settings");
    try {
      const result = await apiGet<AdBuildPlanSettings>(
        `/projects/${project.id}/ad-build-plan-settings/material-plans`,
      );
      setBuildPlanSettings(result);
      setEditing(true);
      setMessage({
        intent: "success",
        text: `已读取物料中心 ${result.plan_count} 个计划，当前内容可编辑，请确认后保存规则`,
      });
    } catch (reason) {
      setMessage({
        intent: "error",
        text: reason instanceof Error ? reason.message : "读取物料中心计划失败",
      });
    } finally {
      setBusy(null);
    }
  };

  const updateBuildPlanRepeat = (campaignName: string, value: string) => {
    const repeatCount = Math.max(1, Math.min(20, Number(value) || 1));
    setBuildPlanSettings((current) => current ? {
      ...current,
      items: current.items.map((item) => item.campaign_name === campaignName
        ? { ...item, repeat_count: repeatCount }
        : item),
    } : current);
    setMessage(null);
  };

  const saveBuildPlanSettings = async () => {
    if (!buildPlanSettings) return;
    setBusy("save-build-settings");
    try {
      const result = await apiPut<AdBuildPlanSettings>(
        `/projects/${project.id}/ad-build-plan-settings`,
        {
          plans: buildPlanSettings.items.map((item) => ({
            campaign_name: item.campaign_name,
            repeat_count: item.repeat_count,
          })),
        },
      );
      setBuildPlanSettings(result);
      setSavedBuildPlanSettings(cloneBuildPlanSettings(result));
      setEditing(false);
      setMessage({
        intent: "success",
        text: "搭建设置草稿已保存，页面会保留当前内容；发布规则后才会正式生效",
      });
    } catch (reason) {
      setMessage({
        intent: "error",
        text: reason instanceof Error ? reason.message : "保存规则失败",
      });
    } finally {
      setBusy(null);
    }
  };

  const cancelBuildPlanEditing = () => {
    if (savedBuildPlanSettings) {
      setBuildPlanSettings(cloneBuildPlanSettings(savedBuildPlanSettings));
    } else {
      setBuildPlanSettings(null);
    }
    setEditing(false);
    setMessage(null);
  };

  const publishBuildPlanSettings = async () => {
    setBusy("publish-build-settings");
    try {
      const result = await apiPost<AdBuildPlanSettings>(
        `/projects/${project.id}/ad-build-plan-settings/publish`,
        {},
      );
      setBuildPlanSettings(result);
      setSavedBuildPlanSettings(cloneBuildPlanSettings(result));
      setBuildPublishOpen(false);
      setEditing(false);
      setMessage({
        intent: "success",
        text: "搭建设置已正式发布，后续新建任务将使用当前规则",
      });
    } catch (reason) {
      setMessage({
        intent: "error",
        text: reason instanceof Error ? reason.message : "搭建设置发布失败",
      });
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    if (!buildSettingsSelected) return;
    void loadSavedBuildPlanSettings();
  }, [project.id, buildSettingsSelected]);

  if (loading && !policies.length)
    return (
      <Skeleton className="strategy-loading">
        <SkeletonItem />
        <SkeletonItem />
        <SkeletonItem />
      </Skeleton>
    );
  if (!policy || !effective)
    return (
      <PopupMessage intent="error">
        {message?.text || "策略配置不完整"}
      </PopupMessage>
    );

  const roundAmounts = Array.isArray(draft.round_amounts)
    ? draft.round_amounts.filter(
        (item): item is StrategyRoundAmount =>
          typeof item === "object" &&
          item !== null &&
          "round" in item &&
          "amount" in item,
      )
    : [];
  const updateRoundAmount = (round: number, amount: string) => {
    update(
      "round_amounts",
      roundAmounts.map((item) =>
        item.round === round ? { ...item, amount } : item,
      ),
    );
  };
  const configFields = Object.keys(draft).filter(
    (key) =>
      key !== "schedule_times" &&
      key !== "round_amounts" &&
      key !== "execution_mode" &&
      key !== "execution_cycle" &&
      key !== "execution_period_days" &&
      !(
        selectedKey === "budget_reset" &&
        ["target_budget", "minimum_difference", "failure_retry_count", "failure_retry_interval_seconds"].includes(key)
      ) &&
      !(
        selectedKey === "budget_append" &&
        ["add_cost_limit", "utilization_limit"].includes(key)
      ) &&
      !(
        selectedKey === "elimination" &&
        ["spend_without_add_limit", "add_cost_limit"].includes(key)
      ),
  );
  const costJudgmentPolicy = policies.find((item) => item.key === "cost_judgment");
  const savedCostConfig = (costJudgmentPolicy?.draft || costJudgmentPolicy?.active)?.config as Record<string, unknown> | undefined;
  const savedCostMode = savedCostConfig?.mode === "copy_cash" ? "copy_cash" : "add_cash";
  const savedCostStandard = savedCostConfig?.[savedCostMode] && typeof savedCostConfig[savedCostMode] === "object"
    ? savedCostConfig[savedCostMode] as Record<string, unknown>
    : {};
  const savedConversionName = savedCostMode === "copy_cash" ? "复制" : "加粉";
  const savedColdStartLimit = String(savedCostStandard.cold_start_spend_limit ?? "100.00");
  const savedCostLimit = String(savedCostStandard.cost_limit ?? "120.00");
  const costJudgmentSource = costJudgmentPolicy?.draft ? "已保存的成本判断草稿" : "已发布的成本判断标准";
  const paneIds: StrategyPane[] = buildSettingsSelected || globalSelected
    ? ["rules"]
    : ["rules", "records"];
  const runtimeControlsLocked = buildSettingsSelected || globalSelected;
  const defaultExecutionCycle: ExecutionCycle = selectedKey === "budget_reset" ? "daily" : "closed_loop";
  const executionMode: ExecutionMode = runtimeControlsLocked
    ? "auto"
    : executionModeOptions.some((item) => item.value === draft.execution_mode)
      ? draft.execution_mode as ExecutionMode
      : "auto";
  const executionCycle: ExecutionCycle = runtimeControlsLocked
    ? "global"
    : executionCycleOptions.some((item) => item.value === draft.execution_cycle)
      ? draft.execution_cycle as ExecutionCycle
      : defaultExecutionCycle;
  const executionPeriodDays = Number(draft.execution_period_days || 1);
  const renderPolicyAction = (key: StrategyKey) =>
    policies.some((item) => item.key === key) ? (
      <button
        type="button"
        aria-current={action === key ? "page" : undefined}
        className={action === key ? "active" : ""}
        onClick={() => selectAction(key)}
      >
        {strategyMeta[key].name}
      </button>
    ) : null;
  return (
    <section className={`automatic-strategy-console${embedded ? " is-embedded" : ""}`}>
      <header className="strategy-release-bar">
        <div className="strategy-release-meta">
          <h1>自动策略</h1>
          {buildSettingsSelected ? (
            <>
              <span>上线准备</span>
              <span>搭建设置</span>
              <strong>
                {buildPlanSettings?.has_draft
                  ? "草稿已保存，尚未发布。"
                  : buildPlanSettings?.has_published
                    ? "当前显示已发布规则。"
                    : "读取物料中心计划后开始配置。"}
              </strong>
            </>
          ) : (
            <>
              <span>线上版本 {formatVersionCode(policy.active)}</span>
              <span className={policy.draft ? "is-draft" : ""}>
                {policy.draft
                  ? `编辑草稿 ${formatVersionCode(policy.draft)}`
                  : "尚无编辑草稿"}
              </span>
              <span>{evaluation ? "发布就绪" : policy.draft ? "待发布检查" : "线上生效"}</span>
              <strong>
                {policy.draft
                  ? "已创建编辑草稿，线上规则未改变。"
                  : "当前显示线上规则，编辑后将创建草稿。"}
              </strong>
            </>
          )}
        </div>
        {buildSettingsSelected ? (
            <Button
              appearance="primary"
              disabled={Boolean(busy) || !buildPlanSettings?.has_draft || editing}
              onClick={() => setBuildPublishOpen(true)}
            >
              发布规则
            </Button>
          ) : (
            <Button
              appearance="primary"
              disabled={Boolean(busy) || editing || (!dirty && !policy.draft)}
              onClick={() => void preparePublish()}
            >
              {busy === "prepare-publish" ? "准备发布…" : "发布规则"}
            </Button>
          )}
      </header>
      <div className="strategy-center">
        <nav className="strategy-action-navigation" aria-label="自动策略规则">
          <span>上线准备</span>
          <button
            type="button"
            aria-current={buildSettingsSelected ? "page" : undefined}
            className={buildSettingsSelected ? "active" : ""}
            onClick={() => selectAction("build-settings")}
          >
            搭建设置
          </button>
          <span>实时调整</span>
          {renderPolicyAction("budget_append")}
          {renderPolicyAction("elimination")}
          <span>周期调整</span>
          {renderPolicyAction("budget_reset")}
          <span>全局判定</span>
          {(["account-status", "cost-judgment", "loop-check"] as GlobalJudgmentAction[]).map((item) => (
          <button
            key={item}
            type="button"
            aria-current={globalAction === item ? "page" : undefined}
            className={globalAction === item ? "active" : ""}
            onClick={() => selectAction(item)}
          >
            {globalJudgmentMeta[item].name}
          </button>
          ))}
        </nav>
        <div
          className={`strategy-workspace${globalSelected ? " is-global-workspace" : ""}${globalAction === "loop-check" ? " is-loop-workspace" : ""}`}
          role="region"
          aria-label={`${actionName}工作区`}
        >
          <div className="strategy-detail-toolbar">
            <nav role="tablist" aria-label={`${actionName}内容`}>
              <button
                role="tab"
                aria-selected={pane === "rules"}
                className={pane === "rules" ? "active" : ""}
                onClick={() => setPane("rules")}
                onKeyDown={(event) =>
                  moveHorizontalTab(event, paneIds, pane, setPane)
                }
              >
                {buildSettingsSelected
                  ? "搭建设置"
                  : globalSelected
                    ? "规则设置"
                    : "规则设置"}
              </button>
              {!buildSettingsSelected && !globalSelected && <button
                role="tab"
                aria-selected={pane === "records"}
                className={pane === "records" ? "active" : ""}
                onClick={() => setPane("records")}
                onKeyDown={(event) =>
                  moveHorizontalTab(event, paneIds, pane, setPane)
                }
              >
                {selectedKey === "budget_reset" ? "执行失败记录" : "执行记录"}
              </button>}
            </nav>
            {pane === "rules" && <div className="strategy-execution-controls">
              <label>
                <span>执行模式</span>
                <select
                  aria-label="执行模式"
                  value={executionMode}
                  disabled={runtimeControlsLocked || !editing || Boolean(busy)}
                  onChange={(event) => update("execution_mode", event.target.value)}
                  title={runtimeControlsLocked ? "全局规则固定为自动执行" : undefined}
                >
                  {executionModeOptions.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>执行周期</span>
                <select
                  aria-label="执行周期"
                  value={executionCycle}
                  disabled={runtimeControlsLocked || !editing || Boolean(busy)}
                  onChange={(event) => update("execution_cycle", event.target.value)}
                  title={runtimeControlsLocked ? "全局规则固定为全局执行" : undefined}
                >
                  {executionCycleOptions.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>
              {executionCycle === "periodic" && (
                <label className="strategy-execution-period">
                  <span>周期</span>
                  <Input
                    aria-label="执行周期天数"
                    type="number"
                    min="1"
                    max="365"
                    step="1"
                    value={String(executionPeriodDays)}
                    contentAfter="日"
                    disabled={runtimeControlsLocked || !editing || Boolean(busy)}
                    onChange={(_, data) => update("execution_period_days", Number(data.value))}
                  />
                </label>
              )}
            </div>}
            {buildSettingsSelected && (
              <div className="strategy-edit-controls">
                {editing ? (
                  <>
                    <Button
                      appearance="secondary"
                      disabled={Boolean(busy)}
                      onClick={() => void readMaterialBuildPlans()}
                    >
                      {busy === "load-build-settings" ? "读取中…" : "读取物料中心计划"}
                    </Button>
                    <Button
                      appearance="secondary"
                      disabled={Boolean(busy)}
                      onClick={cancelBuildPlanEditing}
                    >
                      取消
                    </Button>
                    <Button
                      appearance="primary"
                      disabled={Boolean(busy) || !buildPlanSettings?.items.length}
                      onClick={() => void saveBuildPlanSettings()}
                    >
                      {busy === "save-build-settings" ? "保存中…" : "保存规则"}
                    </Button>
                  </>
                ) : (
                  <Button
                    appearance="primary"
                    disabled={Boolean(busy)}
                    onClick={() => setEditing(true)}
                  >
                    编辑规则
                  </Button>
                )}
              </div>
            )}
            {!buildSettingsSelected && pane === "rules" && (
              <div className="strategy-edit-controls">
                {editing ? (
                  <>
                    <Button
                      appearance="secondary"
                      disabled={Boolean(busy)}
                      onClick={cancelRuleEditing}
                    >
                      取消
                    </Button>
                    <Button
                      appearance="primary"
                      disabled={Boolean(busy) || (!dirty && !globalSelected)}
                      onClick={() => void saveRule()}
                    >
                      {busy === "save-rule" ? "保存中…" : "保存规则"}
                    </Button>
                  </>
                ) : (
                  <Button
                    appearance="primary"
                    disabled={Boolean(busy)}
                    onClick={() => setEditing(true)}
                  >
                    编辑规则
                  </Button>
                )}
              </div>
            )}
          </div>
          {message ? (
            <PopupMessage intent={message.intent}>{message.text}</PopupMessage>
          ) : null}
          {pane === "records" && !buildSettingsSelected && !globalSelected ? renderRecords?.(action) : null}
          {pane === "rules" && globalAction ? renderGlobal?.(globalAction, {
            config: draft,
            editing,
            busy: Boolean(busy),
            update,
          }) : null}
          {pane === "rules" && buildSettingsSelected ? (
            <section className="strategy-form-section build-plan-settings">
              {buildPlanSettings?.items.length ? (
                <div className="build-plan-settings-table-wrap">
                  <table className="build-plan-settings-table">
                    <thead>
                      <tr>
                        <th className="table-cell--start">计划</th>
                        <th className="table-cell--center">物料关键词</th>
                        <th className="table-cell--start">单元重复次数</th>
                      </tr>
                    </thead>
                    <tbody>
                      {buildPlanSettings.items.map((item) => (
                        <tr key={item.campaign_name}>
                          <td className="table-cell--start">{item.campaign_name}</td>
                          <td className="table-cell--center">
                            {item.keyword_count.toLocaleString("zh-CN")}
                          </td>
                          <td className="table-cell--start">
                            <Input
                              className="build-plan-repeat-input"
                              disabled={!editing || Boolean(busy)}
                              type="number"
                              min="1"
                              max="20"
                              step="1"
                              aria-label={`${item.campaign_name}单元重复次数`}
                              value={String(item.repeat_count)}
                              onChange={(_, data) =>
                                updateBuildPlanRepeat(item.campaign_name, data.value)
                              }
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="strategy-result-empty">
                  点击“读取物料中心计划”后，在这里设置各计划的单元重复次数
                </div>
              )}
            </section>
          ) : null}
          {pane === "rules" && !globalSelected && !buildSettingsSelected && (
            <>
              <section className="strategy-form-section">
                <fieldset
                  disabled={!editing || Boolean(busy)}
                  className="strategy-editor-fields"
                >
                  {selectedKey === "budget_reset" ? (
                    <section className="budget-reset-rule">
                      <div className="budget-reset-block">
                        <div className="budget-trigger-conditions-head strategy-inline-heading">
                          <h4>重置规则</h4>
                          <p>每天只恢复偏离初始预算的账户，不重新计算扩量目标</p>
                        </div>
                        <div className="budget-reset-line budget-reset-line--rule">
                          <span>当前日预算</span><em>≠</em><span>初始预算</span><em>→</em><span>重置为初始预算</span>
                          <span className="budget-reset-line-label">初始预算</span>
                          <Input
                            aria-label="初始预算"
                            type="number"
                            min="0.01"
                            max="1000000"
                            step="0.01"
                            value={String(draft.target_budget ?? "50.00")}
                            contentAfter="账户币"
                            onChange={(_, data) => update("target_budget", data.value)}
                          />
                          <span className="budget-reset-line-label">最小差额</span>
                          <Input
                            aria-label="预算重置最小差额"
                            type="number"
                            min="0.01"
                            max="1000000"
                            step="0.01"
                            value={String(draft.minimum_difference ?? "0.01")}
                            contentAfter="账户币"
                            onChange={(_, data) => update("minimum_difference", data.value)}
                          />
                        </div>
                        <div className="budget-reset-helper">只有差额达到最小差额才处理；不要求成本判断或数据水位，到点直接执行。</div>
                        <div className="budget-reset-line budget-reset-line--failure">
                          <span>失败处理</span><span>失败后重试</span>
                          <Input
                            aria-label="预算重置失败重试次数"
                            type="number"
                            min="0"
                            max="10"
                            step="1"
                            value={String(draft.failure_retry_count ?? 3)}
                            contentAfter="次"
                            onChange={(_, data) => update("failure_retry_count", Number(data.value))}
                          />
                          <span>每次间隔</span>
                          <Input
                            aria-label="预算重置重试间隔"
                            type="number"
                            min="10"
                            max="3600"
                            step="10"
                            value={String(draft.failure_retry_interval_seconds ?? 60)}
                            contentAfter="秒"
                            onChange={(_, data) => update("failure_retry_interval_seconds", Number(data.value))}
                          />
                          <span>最终失败时进入“执行失败记录”</span>
                        </div>
                      </div>
                    </section>
                  ) : null}
                  {selectedKey === "budget_append" ? (
                    <section className="budget-trigger-conditions">
                      <div className="budget-trigger-conditions-head strategy-inline-heading">
                        <h4>触发条件</h4>
                        <p>以下条件同时满足时，进入下一轮预算追加</p>
                      </div>
                      <div className="budget-trigger-conditions-grid">
                        <Field label={`${savedConversionName}现金成本合格线`} hint={`跟随${costJudgmentSource}`}>
                          <output className="strategy-followed-value" aria-label={`${savedConversionName}现金成本合格线`}>
                            <strong>{savedCostLimit}</strong><span>元</span>
                          </output>
                        </Field>
                        {["utilization_limit"].map((key) => (
                          <Field
                            key={key}
                            label={fieldMeta[key].label}
                            hint={key === "utilization_limit" ? undefined : fieldMeta[key].suffix}
                          >
                            <Input
                              type="number"
                              min={key === "utilization_limit" ? "0.01" : undefined}
                              max={key === "utilization_limit" ? "100" : undefined}
                              step={fieldMeta[key].step}
                              value={key === "utilization_limit"
                                ? utilizationPercent(draft[key])
                                : String(draft[key] ?? "")}
                              contentAfter={key === "utilization_limit" ? "%" : undefined}
                              onChange={(_, data) => update(
                                key,
                                key === "utilization_limit"
                                  ? utilizationRatio(data.value)
                                  : data.value,
                              )}
                            />
                          </Field>
                        ))}
                      </div>
                    </section>
                  ) : null}
                  {selectedKey === "elimination" ? (
                    <section className="budget-trigger-conditions">
                      <div className="budget-trigger-conditions-head strategy-inline-heading">
                        <h4>触发条件</h4>
                        <p>淘汰判定跟随{costJudgmentSource}</p>
                      </div>
                      <div className="budget-trigger-conditions-grid">
                        <Field label="无转化累计消耗线" hint={`没有${savedConversionName}时使用`}>
                          <output className="strategy-followed-value" aria-label="无转化累计现金消耗线">
                            <strong>{savedColdStartLimit}</strong><span>元</span>
                          </output>
                        </Field>
                        <Field label={`${savedConversionName}现金成本合格线`} hint="超过该值时直接暂停账户全部计划">
                          <output className="strategy-followed-value" aria-label={`${savedConversionName}现金成本合格线`}>
                            <strong>{savedCostLimit}</strong><span>元</span>
                          </output>
                        </Field>
                      </div>
                    </section>
                  ) : null}
                  {selectedKey === "budget_append" && roundAmounts.length ? (
                    <section className="budget-round-amounts">
                      <div className="budget-round-amounts-head">
                        <div className="strategy-inline-heading">
                          <h4>追加轮次</h4>
                          <p>每轮直接填写追加金额；第 10 轮及以上沿用最后一档</p>
                        </div>
                      </div>
                      <div className="budget-round-amounts-table-scroll">
                        <table aria-label="追加轮次金额">
                          <thead>
                            <tr>
                              {roundAmounts.map((item) => (
                                <th key={item.round} scope="col">
                                  {item.round === 10
                                    ? "第 10 轮及以上"
                                    : `第 ${item.round} 轮`}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            <tr>
                              {roundAmounts.map((item) => (
                                <td key={item.round}>
                                  <Input
                                    type="number"
                                    min="0.01"
                                    max="1000000"
                                    step="0.01"
                                    aria-label={`${item.round === 10 ? "第 10 轮及以上" : `第 ${item.round} 轮`}追加金额`}
                                    value={item.amount}
                                    contentAfter={<span className="budget-round-unit">账户币</span>}
                                    onChange={(_, data) =>
                                      updateRoundAmount(item.round, data.value)
                                    }
                                  />
                                </td>
                              ))}
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </section>
                  ) : null}
                  <div className="strategy-form-grid">
                    {configFields.map((key) => (
                      <Field
                        key={key}
                        label={fieldMeta[key]?.label || key}
                        hint={fieldMeta[key]?.description
                          ? `${fieldMeta[key].description} 单位：${fieldMeta[key].suffix}`
                          : fieldMeta[key]?.suffix}
                      >
                        <Input
                          type="number"
                          step={fieldMeta[key]?.step || "0.01"}
                          value={String(draft[key] ?? "")}
                          onChange={(_, value) => update(key, value.value)}
                        />
                      </Field>
                    ))}
                  </div>
                </fieldset>
              </section>
            </>
          )}
        </div>
      </div>
      <Dialog
        open={publishOpen}
        onOpenChange={(_, data) => {
          if (!busy) setPublishOpen(data.open);
        }}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitleWithSummary summary="发布后将作为当前生效版本执行">确认发布{actionName}</DialogTitleWithSummary>
            <DialogContent>
              <p>
                当前规则已经完成发布前检查；
                {globalAction
                  ? globalJudgmentMeta[globalAction].description
                  : `${strategyMeta[selectedKey].effect}仍会经过现有目标账户、限频、审计、幂等和回读链路`}
              </p>
              <div className="publish-summary">
                <span>{selectedKey === "elimination" ? "命中账户" : "候选数量"}</span>
                <strong>{selectedKey === "elimination" ? (evaluation?.result.matched_count ?? evaluation?.result.candidate_count ?? 0) : (evaluation?.result.candidate_count ?? 0)}</strong>
                <small>{evaluation?.result.action}</small>
              </div>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                onClick={() => setPublishOpen(false)}
              >
                取消
              </Button>
              <Button
                appearance="primary"
                disabled={busy === "publish"}
                onClick={() => void publish()}
              >
                {busy === "publish" ? "发布中…" : "确认发布"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog
        open={buildPublishOpen}
        onOpenChange={(_, data) => {
          if (!busy) setBuildPublishOpen(data.open);
        }}
      >
        <DialogSurface>
          <DialogBody>
            <DialogTitleWithSummary summary="发布后仅影响后续创建的广告任务">
              确认发布搭建设置
            </DialogTitleWithSummary>
            <DialogContent>
              <p>当前保存的草稿将成为正式搭建规则，后续任务会按各计划的单元重复次数执行。</p>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                onClick={() => setBuildPublishOpen(false)}
              >
                取消
              </Button>
              <Button
                appearance="primary"
                disabled={busy === "publish-build-settings"}
                onClick={() => void publishBuildPlanSettings()}
              >
                {busy === "publish-build-settings" ? "发布中…" : "确认发布"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </section>
  );
}
