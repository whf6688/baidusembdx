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

type StrategyKey = Exclude<StrategyPolicy["key"], "keyword_tiers">;
export type GlobalJudgmentAction = "account-status" | "cost-judgment" | "loop-check";
export type StrategyAction = StrategyKey | GlobalJudgmentAction | "build-settings";
type StrategyPane = "rules" | "records";

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
    description: "成本和预算利用率同时达标才进入追加候选",
    effect: "按边际效果追加预算",
  },
  elimination: {
    name: "账户淘汰",
    description: "达到现行淘汰阈值后进入原有执行与回读链路",
    effect: "删除账户全部计划",
  },
};

const globalJudgmentMeta: Record<
  GlobalJudgmentAction,
  { name: string; description: string; cycle: string }
> = {
  "account-status": {
    name: "账户状态",
    description: "根据账户、计划、历史数据与自动上线分配统一判定账户状态。",
    cycle: "数据刷新后",
  },
  "cost-judgment": {
    name: "成本判断",
    description: "分别维护加粉现金成本与复制现金成本的判定标准。",
    cycle: "数据刷新后",
  },
  "loop-check": {
    name: "实时闭环",
    description: "项目刷新、运行保护和闭环状态统一管理。",
    cycle: "实时闭环",
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
  renderGlobal?: (action: GlobalJudgmentAction) => ReactNode;
  requestedAction?: StrategyAction;
  embedded?: boolean;
}) {
  const [policies, setPolicies] = useState<StrategyPolicy[]>([]);
  const [selectedKey, setSelectedKey] = useState<StrategyKey>("budget_append");
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
  const [globalAction, setGlobalAction] = useState<GlobalJudgmentAction | null>(null);
  const [buildSettingsSelected, setBuildSettingsSelected] = useState(false);
  const [buildPlanSettings, setBuildPlanSettings] =
    useState<AdBuildPlanSettings | null>(null);
  const [savedBuildPlanSettings, setSavedBuildPlanSettings] =
    useState<AdBuildPlanSettings | null>(null);
  const [pane, setPane] = useState<StrategyPane>("rules");
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
  const selectAction = (next: StrategyAction) => {
    const nextGlobal = next === "account-status" || next === "cost-judgment" || next === "loop-check"
      ? next
      : null;
    setGlobalAction(nextGlobal);
    setBuildSettingsSelected(next === "build-settings");
    if (!nextGlobal && next !== "build-settings") setSelectedKey(next as StrategyKey);
    setPane("rules");
    setEditing(false);
    setMessage(null);
    if (effective) setDraft(cloneConfig(effective.config));
  };

  const policy = policies.find((item) => item.key === selectedKey);
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
  }, [project.id, selectedKey, effective?.id]);

  const update = (key: string, value: StrategyConfigValue) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setEvaluation(null);
    setMessage(null);
  };
  const saveRule = async () => {
    if (!policy || !dirty) return;
    setBusy("save-rule");
    try {
      const next = await apiPut<StrategyPolicy>(
        `/projects/${project.id}/strategies/${selectedKey}/draft`,
        { config: draft, expected_revision: policy.revision },
      );
      setPolicies((rows) =>
        rows.map((item) => (item.key === selectedKey ? next : item)),
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
          `/projects/${project.id}/strategies/${selectedKey}/draft`,
          { config: draft, expected_revision: policy.revision },
        );
        setPolicies((rows) =>
          rows.map((item) => (item.key === selectedKey ? current : item)),
        );
      }
      const result = await apiPost<StrategyEvaluation>(
        `/projects/${project.id}/strategies/${selectedKey}/dry-run`,
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
        `/projects/${project.id}/strategies/${selectedKey}/publish`,
        { expected_revision: policy.revision, evaluation_id: evaluation.id },
      );
      setPolicies((rows) =>
        rows.map((item) => (item.key === selectedKey ? next : item)),
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
      !(selectedKey === "budget_reset" && key === "target_budget") &&
      !(
        selectedKey === "budget_append" &&
        ["add_cost_limit", "utilization_limit"].includes(key)
      ),
  );
  const paneIds: StrategyPane[] = buildSettingsSelected || globalSelected
    ? ["rules"]
    : ["rules", "records"];
  const executionModeLabel = buildSettingsSelected
    ? "人工配置"
    : globalSelected
      ? "自动判定"
      : "自动执行";
  const executionCycleLabel = buildSettingsSelected
    ? "新任务生效"
    : globalAction
      ? globalJudgmentMeta[globalAction].cycle
      : selectedKey === "budget_append"
        ? "每小时评估"
        : "每日执行";
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
          ) : globalAction ? (
            <>
              <span>全局判定</span>
              <span>{globalJudgmentMeta[globalAction].name}</span>
              <strong>{globalJudgmentMeta[globalAction].description}</strong>
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
        {!globalSelected && (
          buildSettingsSelected ? (
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
          )
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
          <span>周期调整</span>
          {renderPolicyAction("budget_reset")}
          {renderPolicyAction("elimination")}
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
          className={`strategy-workspace${globalSelected ? " is-global-workspace" : ""}`}
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
              {!buildSettingsSelected && <button
                role="tab"
                aria-selected={pane === "records"}
                className={pane === "records" ? "active" : ""}
                onClick={() => setPane("records")}
                onKeyDown={(event) =>
                  moveHorizontalTab(event, paneIds, pane, setPane)
                }
              >
                执行记录
              </button>}
            </nav>
            {pane === "rules" && <div className="strategy-execution-controls">
              <label>
                <span>执行模式</span>
                <select aria-label="执行模式" value={executionModeLabel} onChange={() => undefined}>
                  <option>{executionModeLabel}</option>
                </select>
              </label>
              <label>
                <span>执行周期</span>
                <select aria-label="执行周期" value={executionCycleLabel} onChange={() => undefined}>
                  <option>{executionCycleLabel}</option>
                </select>
              </label>
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
            {!globalSelected && !buildSettingsSelected && pane === "rules" && (
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
                      disabled={Boolean(busy) || !dirty}
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
          {pane === "rules" && globalAction ? renderGlobal?.(globalAction) : null}
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
                      <div className="budget-trigger-conditions-head strategy-inline-heading">
                        <h4>触发条件</h4>
                        <p>以下条件同时满足时，才执行预算重置</p>
                      </div>
                      <div className="budget-reset-trigger-list">
                        <span>
                          <small>账户状态</small>
                          <strong>账户已启用且未淘汰</strong>
                        </span>
                        <span>
                          <small>成本判断</small>
                          <strong>冷启动期</strong>
                        </span>
                        <span>
                          <small>数据要求</small>
                          <strong>预算快照在 60 分钟内</strong>
                        </span>
                        <span>
                          <small>变更条件</small>
                          <strong>当前日预算不等于填写金额</strong>
                        </span>
                      </div>
                      <div className="budget-reset-target">
                        <Field label="固定日预算" hint="触发后直接设置为该金额，不做增减计算">
                          <Input
                            type="number"
                            min="0.01"
                            max="1000000"
                            step="0.01"
                            value={String(draft.target_budget ?? "")}
                            contentAfter="元"
                            onChange={(_, data) => update("target_budget", data.value)}
                          />
                        </Field>
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
                        {["add_cost_limit", "utilization_limit"].map((key) => (
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
                                    contentAfter="元"
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
            <DialogTitleWithSummary summary="发布后将作为当前生效版本执行">确认发布{strategyMeta[selectedKey].name}</DialogTitleWithSummary>
            <DialogContent>
              <p>
                当前规则已经完成发布前检查；
                {strategyMeta[selectedKey].effect}
                仍会经过现有目标账户、限频、审计、幂等和回读链路
              </p>
              <div className="publish-summary">
                <span>候选数量</span>
                <strong>{evaluation?.result.candidate_count ?? 0}</strong>
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
