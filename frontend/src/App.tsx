import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  Popover,
  PopoverSurface,
  PopoverTrigger,
  Skeleton,
  SkeletonItem,
  Spinner,
  Textarea,
} from "@fluentui/react-components";
import { DismissRegular, FilterRegular } from "@fluentui/react-icons";
import {
  apiDelete,
  apiDownload,
  apiGet,
  apiPatch,
  apiPost,
  apiUpload,
  getLocalIdentity,
  isAuthenticationError,
  probeSession,
  setLocalIdentity,
  setServerIdentity,
} from "./api";
import { DateFilterGroup } from "./components/DateFilterGroup";
import { DateRangePicker } from "./components/DateRangePicker";
import { PopupMessage } from "./components/PopupMessage";
import { DialogTitleWithSummary } from "./components/DialogTitleWithSummary";
import { SearchField } from "./components/SearchField";
import { ViewportStickyPagination } from "./components/ViewportStickyPagination";
import { AppSidebar, type SidebarGroup } from "./components/AppShell";
import { NotificationCenter } from "./components/NotificationCenter";
import { PageHeader, WorkspaceHeaderContext } from "./components/PageHeader";
import { moveHorizontalTab } from "./components/tabNavigation";
import { AccountWorkspaceTable } from "./features/accounts/AccountWorkspaceTable";
import { MembersPage } from "./features/members/MembersPage";
import { LoginPage } from "./features/auth/LoginPage";
import { ProjectManagementPage } from "./features/projects/ProjectManagementPage";
import { ReportsPage } from "./features/reports/ReportsPage";
import { FinanceReportsPage } from "./features/finance/FinanceReportsPage";
import { StrategyCenter } from "./features/strategies/StrategyCenter";
import type { GlobalJudgmentAction, StrategyAction } from "./features/strategies/StrategyCenter";
import { getUiTimeZone, setUiTimeZone } from "./uiTimeZone";
import { keywordTierRuleFields } from "./keywordTierRuleFields";
import { WeeklyScheduleSelector, type WeeklyScheduleWindow } from "./ui";
import type {
  Account,
  AccountManagementRow,
  AccountManager,
  AdBuildAccess,
  AdBuildCreateResult,
  AdBuildJob,
  AdBuildMode,
  AdBuildPreview,
  AdBuildRegionPreference,
  AlertRow,
  AuditEvent,
  DailyReport,
  KeywordBuildMode,
  CreativeCenter,
  CreativeSegmentType,
  CostJudgmentPreference,
  ImportPreview,
  KeywordTierDryRun,
  KeywordTierRules,
  MaterialKeywordFacets,
  MaterialKeywordPage,
  MaterialKeywordRow,
  NegativeKeywordLibrary,
  NegativeKeywordMatchType,
  OperationsCenter,
  PermissionModule,
  Project,
  ProjectAccess,
  BaiduRegionCatalog,
  BaiduRegionNode,
  ReferenceTemplate,
  SettingsPreference,
  TaskRow,
  TrackingCaptureCreateResult,
  TrackingCaptureTask,
  TrackingPreference,
  TrackingUnmatched,
} from "./types";

type AutoLaunchView = "delivery" | "materials" | "creatives" | "records";
type OperationsView =
  "loop-check" | "budget-reset" | "budget-append" | "eliminations";
type Page =
  | "accounts"
  | "account-list"
  | "auto-launch"
  | AutoLaunchView
  | "reports"
  | "finance-reports"
  | "strategies"
  | "loop-check"
  | "budget-reset"
  | "budget-append"
  | "eliminations"
  | "execution-records"
  | "members"
  | "settings";
type RuntimeHealth = {
  writes_enabled: boolean;
  account_auto_elimination_enabled: boolean;
  creative_auto_rebuild_enabled: boolean;
  baidu_app_configured: boolean;
};

type SessionInfo = {
  username: string;
  display_name: string;
  role: "admin" | "operator";
  allowed_roles: Array<"admin" | "operator">;
  environment: string;
  is_system_owner: boolean;
  auth_mode: "web" | "proxy" | "local";
};

type AccountBatchImportPreview = {
  file_name: string;
  sha256: string;
  row_count: number;
  matched_count: number;
  changed_count: number;
  unchanged_count: number;
  invalid_count: number;
  changed_fields: string[];
  errors: Array<{ row: number; selector: string; message: string }>;
  can_import: boolean;
  updated_count?: number;
};

type CampaignCurrentSetting = {
  configured: boolean;
  matched_account_count: number;
  online_schedule: WeeklyScheduleWindow[] | null;
  online_weekdays: number[] | null;
  online_start_hour: number | null;
  online_end_hour: number | null;
  schedule_status: string | null;
  schedule_task_id: string | null;
  schedule_account_count: number | null;
  schedule_plan_count: number | null;
  schedule_updated_at: string | null;
  pause: boolean | null;
  pause_status: string | null;
  pause_task_id: string | null;
  pause_account_count: number | null;
  pause_plan_count: number | null;
  pause_updated_at: string | null;
  updated_by: string | null;
};

type CampaignBatchPreview = {
  fingerprint: string;
  matched_account_count: number;
  sample_accounts: Array<{ account_id: number; account_name: string }>;
  plan_count_note: string;
  pause_schedule: Array<{
    weekDay: number;
    startHour: number;
    endHour: number;
  }> | null;
  writes_enabled: boolean;
};

type CustomIdMapping = {
  id: string;
  custom_id: string;
  account_id: number;
  account_name: string;
  account_subject: string | null;
  updated_at: string;
};

type CustomIdList = {
  total: number;
  limit: number;
  rows: CustomIdMapping[];
};

const navigation: SidebarGroup[] = [
  {
    group: "项目与账户",
    items: [
      { id: "accounts", label: "账户管理", shortLabel: "管" },
      { id: "account-list", label: "账户列表", shortLabel: "列" },
      { id: "auto-launch", label: "自动上线", shortLabel: "上" },
      { id: "reports", label: "数据报表", shortLabel: "报" },
      { id: "finance-reports", label: "财务报表", shortLabel: "财" },
    ],
  },
  {
    group: "系统设置",
    items: [
      { id: "strategies", label: "自动策略", shortLabel: "策" },
      { id: "members", label: "成员管理", shortLabel: "员" },
    ],
  },
];

const pagePermission: Record<"accounts" | "account-list" | "auto-launch" | "reports" | "finance-reports" | "members" | "strategies", PermissionModule> = {
  accounts: "account_management",
  "account-list": "account_list",
  "auto-launch": "auto_launch",
  reports: "reports",
  "finance-reports": "finance_reports",
  members: "member_management",
  strategies: "strategies",
};

const autoLaunchViews: Array<{
  id: AutoLaunchView;
  label: string;
}> = [
  { id: "delivery", label: "自动搭建" },
  { id: "materials", label: "物料中心" },
  { id: "creatives", label: "创意中心" },
  { id: "records", label: "执行记录" },
];

function isAutoLaunchView(value: string | null): value is AutoLaunchView {
  return (
    value === "materials" ||
    value === "creatives" ||
    value === "delivery" ||
    value === "records"
  );
}

function accountHasLowBalance(account: Account) {
  return account.is_active && account.balance_alert === true;
}

type StrategySection = "policies" | "refresh" | "runtime";
type ProjectRoute = {
  projectCode: string | null;
  requestedPage: string | null;
  requestedSection: StrategySection;
};

function currentProjectRoute(): ProjectRoute {
  const parts = window.location.pathname.split("/").filter(Boolean);
  const projectCode =
    parts.length === 1 ? decodeURIComponent(parts[0]).toLowerCase() : null;
  const query = new URLSearchParams(window.location.search);
  const requestedSection = query.get("section");
  return {
    projectCode,
    requestedPage: query.get("page"),
    requestedSection:
      requestedSection === "refresh" || requestedSection === "runtime"
        ? requestedSection
        : "policies",
  };
}

function pageFromRequest(requestedPage: string | null): {
  page: Page;
  autoLaunchView: AutoLaunchView;
} {
  const autoLaunchView = isAutoLaunchView(requestedPage)
    ? requestedPage
    : requestedPage === "execution-records"
      ? "records"
      : "delivery";
  if (isAutoLaunchView(requestedPage) || requestedPage === "execution-records")
    return { page: "auto-launch", autoLaunchView };
  if (requestedPage === "settings") return { page: "members", autoLaunchView };
  const isKnownPage = navigation.some((group) =>
    group.items.some((item) => item.id === requestedPage),
  );
  return {
    page: isKnownPage ? (requestedPage as Page) : "account-list",
    autoLaunchView,
  };
}

function projectUrl(projectCode: string, nextPage?: Page | AutoLaunchView) {
  const url = new URL(window.location.origin);
  url.pathname = `/${encodeURIComponent(projectCode)}`;
  if (nextPage) url.searchParams.set("page", nextPage);
  return `${url.pathname}${url.search}`;
}

function rememberPageInUrl(value: Page | AutoLaunchView) {
  const url = new URL(window.location.href);
  url.searchParams.set("page", value);
  if (value !== "strategies") url.searchParams.delete("section");
  window.history.pushState(
    window.history.state,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}

function rememberStrategySection(section: StrategySection) {
  const url = new URL(window.location.href);
  url.searchParams.set("page", "strategies");
  url.searchParams.set("section", section);
  window.history.pushState(
    window.history.state,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}

function App() {
  const [localIdentity, setLocalIdentityState] = useState(getLocalIdentity);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [authState, setAuthState] = useState<"checking" | "authenticated" | "required">("checking");
  const [locationRevision, setLocationRevision] = useState(0);
  const initialRoute = currentProjectRoute();
  const initialSelection = pageFromRequest(initialRoute.requestedPage);
  const [autoLaunchView, setAutoLaunchView] = useState<AutoLaunchView>(
    initialSelection.autoLaunchView,
  );
  const [page, setPage] = useState<Page>(initialSelection.page);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [managers, setManagers] = useState<AccountManager[]>([]);
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectAccess, setProjectAccess] = useState<ProjectAccess | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [runtimeHealth, setRuntimeHealth] = useState<RuntimeHealth | null>(
    null,
  );
  const loadedRouteRef = useRef<string | null>(null);
  const route = currentProjectRoute();
  const isProjectWorkspace = Boolean(route.projectCode);
  const navigationProjectCode =
    route.projectCode ||
    window.sessionStorage.getItem("search-console-last-project") ||
    projects.find((project) => project.enabled)?.code ||
    projects[0]?.code ||
    null;

  const selectPage = (nextPage: Page) => {
    if (!isProjectWorkspace) {
      if (navigationProjectCode)
        window.location.assign(
          projectUrl(
            navigationProjectCode,
            nextPage === "auto-launch" ? autoLaunchView : nextPage,
          ),
        );
      return;
    }
    if (nextPage === page) return;
    setPage(nextPage);
    rememberPageInUrl(nextPage === "auto-launch" ? autoLaunchView : nextPage);
  };

  const selectAutoLaunchView = (nextView: AutoLaunchView) => {
    setAutoLaunchView(nextView);
    rememberPageInUrl(nextView);
  };

  useLayoutEffect(() => {
    // Run after React updates the page but before the browser paints, so a
    // navigation click produces one frame instead of "old page scroll + new page".
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [page]);

  useEffect(() => {
    if (route.projectCode)
      window.sessionStorage.setItem(
        "search-console-last-project",
        route.projectCode,
      );
  }, [route.projectCode]);

  useEffect(() => {
    const handlePopState = () => {
      const nextRoute = currentProjectRoute();
      const nextSelection = pageFromRequest(nextRoute.requestedPage);
      setPage(nextSelection.page);
      setAutoLaunchView(nextSelection.autoLaunchView);
      setLocationRevision((value) => value + 1);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (authState !== "authenticated") return;
    const controller = new AbortController();
    const isRefresh = loadedRouteRef.current === route.projectCode;
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    apiGet<Project[]>("/projects", controller.signal)
      .then(async (projectRows) => {
        setProjects(projectRows);
        if (!route.projectCode)
          return {
            project: null,
            projectRows,
            access: null,
            managerRows: [],
            accountRows: [],
            alertRows: [],
            taskRows: [],
            settings: null,
          };
        const project = projectRows.find(
          (item) => item.code.toLowerCase() === route.projectCode,
        );
        if (!project) throw new Error(`未找到项目编码“${route.projectCode}”`);
        if (!project.enabled)
          return {
            project,
            projectRows,
            access: null,
            managerRows: [],
            accountRows: [],
            alertRows: [],
            taskRows: [],
            settings: null,
          };
        const access = await apiGet<ProjectAccess>(
          `/projects/${project.id}/access/me`,
          controller.signal,
        );
        const canRead = (module: PermissionModule) =>
          access.permissions[module] !== "hidden";
        const canReadAccounts = canRead("account_management") || canRead("account_list") || canRead("auto_launch");
        const canReadOperations = canReadAccounts || canRead("reports") || canRead("strategies");
        const [managerRows, accountRows, alertRows, taskRows, settings] =
          await Promise.all([
            canReadAccounts ? apiGet<AccountManager[]>(
              `/projects/${project.id}/managers`,
              controller.signal,
            ) : Promise.resolve([]),
            canReadAccounts ? apiGet<Account[]>(
              `/projects/${project.id}/accounts`,
              controller.signal,
            ) : Promise.resolve([]),
            canReadOperations ? apiGet<AlertRow[]>(
              `/projects/${project.id}/alerts`,
              controller.signal,
            ) : Promise.resolve([]),
            canReadOperations ? apiGet<TaskRow[]>(
              `/projects/${project.id}/tasks`,
              controller.signal,
            ) : Promise.resolve([]),
            canRead("strategies") ? apiGet<SettingsPreference>(
              `/projects/${project.id}/preferences/settings`,
              controller.signal,
            ) : Promise.resolve(null),
          ]);
        return {
          project,
          projectRows,
          access,
          managerRows,
          accountRows,
          alertRows,
          taskRows,
          settings,
        };
      })
      .then(
        ({
          project: _project,
          projectRows,
          access,
          managerRows,
          accountRows,
          alertRows,
          taskRows,
          settings,
        }) => {
          setProjects(projectRows);
          setProjectAccess(access);
          setManagers(managerRows);
          setAccounts(accountRows);
          setAlerts(alertRows);
          setTasks(taskRows);
          setError(null);
          setUiTimeZone(settings?.timezone || "Asia/Shanghai");
          loadedRouteRef.current = route.projectCode;
        },
      )
      .catch((reason: unknown) => {
        if (isAuthenticationError(reason)) {
          setAuthState("required");
          return;
        }
        if (!isRefresh) {
          setManagers([]);
          setAccounts([]);
          setAlerts([]);
          setTasks([]);
          setProjectAccess(null);
        }
        setError(
          reason instanceof Error ? reason.message : "无法读取后台真实数据",
        );
      })
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
    return () => controller.abort();
  }, [reloadKey, route.projectCode, locationRevision, authState]);

  useEffect(() => {
    if (authState !== "authenticated") return;
    apiGet<RuntimeHealth>("/health")
      .then(setRuntimeHealth)
      .catch(() => setRuntimeHealth(null));
  }, [reloadKey, authState]);

  useEffect(() => {
    const controller = new AbortController();
    probeSession<SessionInfo>(controller.signal)
      .then((value) => {
        setServerIdentity({ username: value.username, role: value.role });
        setSession(value);
        setAuthState("authenticated");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setSession(null);
        setAuthState("required");
      });
    return () => controller.abort();
  }, [reloadKey]);

  useEffect(() => {
    let checkingSession = false;
    const requireLogin = async () => {
      if (authState !== "authenticated" || checkingSession) return;
      checkingSession = true;
      try {
        const value = await probeSession<SessionInfo>();
        setServerIdentity({ username: value.username, role: value.role });
        setSession(value);
      } catch {
        setSession(null);
        setAuthState("required");
      } finally {
        checkingSession = false;
      }
    };
    window.addEventListener("search-console:auth-required", requireLogin);
    return () => window.removeEventListener("search-console:auth-required", requireLogin);
  }, [authState]);

  const currentProject = route.projectCode
    ? projects.find((item) => item.code.toLowerCase() === route.projectCode) ||
      null
    : null;
  const visibleNavigation = navigation
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => {
        if (!projectAccess) return false;
        const module = pagePermission[item.id as keyof typeof pagePermission];
        return module && projectAccess.permissions[module] !== "hidden";
      }),
    }))
    .filter((group) => group.items.length > 0);
  const currentPermissionModule: PermissionModule =
    page === "accounts" ? "account_management" :
    page === "account-list" || page === "loop-check" || page === "budget-reset" || page === "budget-append" || page === "eliminations" ? "account_list" :
    page === "reports" ? "reports" :
    page === "members" || page === "settings" ? "member_management" :
    page === "strategies" ? "strategies" : "auto_launch";
  const hasAnyProjectPermission = Boolean(projectAccess && Object.values(projectAccess.permissions).some((level) => level !== "hidden"));
  useEffect(() => {
    if (!projectAccess || projectAccess.permissions[currentPermissionModule] !== "hidden") return;
    const first = visibleNavigation[0]?.items[0]?.id as Page | undefined;
    if (!first) return;
    setPage(first);
    rememberPageInUrl(first);
  }, [currentPermissionModule, projectAccess]);
  const applyProjectChange = (changedProject: Project) => {
    setProjects((current) => {
      const exists = current.some(
        (project) => project.id === changedProject.id,
      );
      return exists
        ? current.map((project) =>
            project.id === changedProject.id ? changedProject : project,
          )
        : [...current, changedProject];
    });
  };

  const switchLocalIdentity = (
    username: "local-admin" | "wang_kang" | "wang_cong",
  ) => {
    const identity = {
      username,
      role: username === "local-admin" ? "admin" as const : "operator" as const,
    };
    setLocalIdentity(identity);
    setLocalIdentityState(identity);
    window.location.reload();
  };

  const openRuntimeStatus = () => {
    window.location.assign("/#runtime-health");
  };
  const runtimeNeedsAttention =
    Boolean(error) || runtimeHealth?.writes_enabled === false;
  const workspaceHeader = currentProject ? (
    <NotificationCenter
      projectId={currentProject.id}
      identityKey={
        session ? `${session.username}:${session.role}` : localIdentity.username
      }
    />
  ) : null;

  if (authState === "checking") {
    return (
      <main className="app-startup" role="status" aria-label="正在打开工作台">
        <span className="app-startup-mark" aria-hidden="true">百</span>
        <Spinner size="small" label="正在打开工作台…" />
      </main>
    );
  }

  if (authState === "required") {
    return (
      <LoginPage
        onAuthenticated={() => window.location.reload()}
      />
    );
  }

  const logout = async () => {
    try {
      await apiPost<{ logged_out: boolean }>("/auth/logout", {});
    } finally {
      window.location.reload();
    }
  };

  return (
    <div className="shell">
      <AppSidebar
        groups={isProjectWorkspace ? visibleNavigation : navigation}
        isProjectWorkspace={isProjectWorkspace}
        page={page}
        runtimeNeedsAttention={runtimeNeedsAttention}
        accountBalanceWarning={managers.some((manager) => manager.balance_warning_active === true)}
        onHome={() => window.location.assign("/")}
        onOpenRuntimeStatus={openRuntimeStatus}
        onSelect={(nextPage) => selectPage(nextPage as Page)}
        username={session?.display_name || session?.username || ""}
        onLogout={logout}
      />
      <main className="main">
        <div className="content">
          {loading ? (
            <LoadingView />
          ) : !isProjectWorkspace ? (
            <ProjectManagementPage
              projects={projects}
              onProjectChange={applyProjectChange}
              projectUrl={projectUrl}
              writesEnabled={runtimeHealth?.writes_enabled === true}
              canManageCodeSync={Boolean(session?.is_system_owner)}
            />
          ) : error && !currentProject ? (
            <ConnectionError
              message={error}
              onRetry={() => setReloadKey((value) => value + 1)}
            />
          ) : !currentProject ? (
            <ConnectionError
              message="项目不存在或没有访问权限"
              onRetry={() => window.location.assign("/")}
            />
          ) : !currentProject.enabled ? (
            <ProjectDisabled project={currentProject} />
          ) : projectAccess && !hasAnyProjectPermission ? (
            <NoProjectPermission />
          ) : (
            <WorkspaceHeaderContext.Provider value={workspaceHeader}>
              <PageContent
                page={page}
                autoLaunchView={autoLaunchView}
                strategySection={route.requestedSection}
                onAutoLaunchViewChange={selectAutoLaunchView}
                managers={managers}
                accounts={accounts}
                alerts={alerts}
                tasks={tasks}
                project={currentProject}
                writesEnabled={runtimeHealth?.writes_enabled === true && projectAccess?.permissions[currentPermissionModule] === "manage"}
                onRefresh={() => setReloadKey((value) => value + 1)}
                localIdentity={localIdentity.username}
                isLocalEnvironment={session?.auth_mode === "local"}
                onSwitchLocalIdentity={switchLocalIdentity}
                projectAccess={projectAccess}
              />
            </WorkspaceHeaderContext.Provider>
          )}
        </div>
      </main>
    </div>
  );
}

function NoProjectPermission() {
  return <section className="connection-error" role="status"><div><span className="eyebrow">项目访问受限</span><h1>当前项目尚未分配功能权限</h1><p>请联系系统管理员为你的登录账号配置导航权限。</p></div></section>;
}

function LoadingView() {
  return (
    <Skeleton className="loading">
      <SkeletonItem size={32} />
      <div className="metric-grid">
        {Array.from({ length: 6 }).map((_, index) => (
          <SkeletonItem key={index} className="metric-skeleton" />
        ))}
      </div>
      <SkeletonItem className="table-skeleton" />
    </Skeleton>
  );
}

function ConnectionError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <section className="connection-error" role="alert">
      <div>
        <span className="eyebrow">未显示任何演示数据</span>
        <h1>暂时无法读取真实数据</h1>
        <p>{message}</p>
        <p>请确认本地服务正在运行，然后重新连接</p>
      </div>
      <Button appearance="primary" onClick={onRetry}>
        重新连接
      </Button>
    </section>
  );
}

function PageContent({
  page,
  autoLaunchView,
  strategySection,
  onAutoLaunchViewChange,
  managers,
  accounts,
  alerts,
  tasks,
  project,
  writesEnabled,
  onRefresh,
  localIdentity,
  isLocalEnvironment,
  onSwitchLocalIdentity,
  projectAccess,
}: {
  page: Page;
  autoLaunchView: AutoLaunchView;
  strategySection: StrategySection;
  onAutoLaunchViewChange: (view: AutoLaunchView) => void;
  managers: AccountManager[];
  accounts: Account[];
  alerts: AlertRow[];
  tasks: TaskRow[];
  project: Project;
  writesEnabled: boolean;
  onRefresh: () => void;
  localIdentity: "local-admin" | "wang_kang" | "wang_cong";
  isLocalEnvironment: boolean;
  onSwitchLocalIdentity: (
    username: "local-admin" | "wang_kang" | "wang_cong",
  ) => void;
  projectAccess: ProjectAccess | null;
}) {
  if (page === "members" || page === "settings")
    return (
      <MembersPage
        project={project}
        localIdentity={localIdentity}
        isLocalEnvironment={isLocalEnvironment}
        onSwitchLocalIdentity={onSwitchLocalIdentity}
        isSystemOwner={projectAccess?.is_system_owner === true}
      />
    );
  if (page === "accounts")
    return (
      <ManagersAccountsPage
        mode="management"
        managers={managers}
        accounts={accounts}
        project={project}
        onRefresh={onRefresh}
        canManage={projectAccess?.permissions.account_management === "manage"}
      />
    );
  if (page === "account-list")
    return (
      <ManagersAccountsPage
        mode="operations"
        managers={managers}
        accounts={accounts}
        project={project}
        onRefresh={onRefresh}
        canManage={projectAccess?.permissions.account_list === "manage"}
      />
    );
  if (page === "strategies")
    return (
      <AutomationStrategyPage
        project={project}
        tasks={tasks}
        section={strategySection}
      />
    );
  if (page === "finance-reports")
    return (
      <FinanceReportsPage
        project={project}
        canManage={projectAccess?.permissions.finance_reports === "manage"}
      />
    );
  if (page === "loop-check")
    return <ProjectOperationsPage view="loop-check" project={project} />;
  if (page === "budget-reset")
    return <ProjectOperationsPage view="budget-reset" project={project} />;
  if (page === "budget-append")
    return <ProjectOperationsPage view="budget-append" project={project} />;
  if (page === "eliminations")
    return <ProjectOperationsPage view="eliminations" project={project} />;
  if (page === "execution-records")
    return (
      <AutoLaunchWorkspace
        view="records"
        onViewChange={onAutoLaunchViewChange}
        accounts={accounts}
        managers={managers}
        project={project}
        writesEnabled={writesEnabled}
        tasks={tasks}
      />
    );
  if (page === "auto-launch")
    return (
      <AutoLaunchWorkspace
        view={autoLaunchView}
        onViewChange={onAutoLaunchViewChange}
        accounts={accounts}
        managers={managers}
        project={project}
        writesEnabled={writesEnabled}
        tasks={tasks}
      />
    );
  if (page === "delivery")
    return (
      <AutoLaunchWorkspace
        view="delivery"
        onViewChange={onAutoLaunchViewChange}
        accounts={accounts}
        managers={managers}
        project={project}
        writesEnabled={writesEnabled}
        tasks={tasks}
      />
    );
  if (page === "materials")
    return (
      <AutoLaunchWorkspace
        view="materials"
        onViewChange={onAutoLaunchViewChange}
        accounts={accounts}
        managers={managers}
        project={project}
        writesEnabled={writesEnabled}
        tasks={tasks}
      />
    );
  if (page === "creatives")
    return (
      <AutoLaunchWorkspace
        view="creatives"
        onViewChange={onAutoLaunchViewChange}
        accounts={accounts}
        managers={managers}
        project={project}
        writesEnabled={writesEnabled}
        tasks={tasks}
      />
    );
  return <ReportsPage project={project} canManage={projectAccess?.permissions.reports === "manage"} />;
}

function ProjectDisabled({ project }: { project: Project }) {
  return (
    <section className="project-disabled" role="status">
      <div>
        <h1>项目已停用</h1>
        <p>{project.name} 当前不提供项目数据与操作；可返回项目管理后重新启用</p>
      </div>
      <Button
        appearance="primary"
        onClick={() => {
          window.location.assign("/");
        }}
      >
        返回项目管理
      </Button>
    </section>
  );
}

function AutoLaunchWorkspace({
  view,
  onViewChange,
  accounts,
  managers,
  project,
  writesEnabled,
  tasks,
}: {
  view: AutoLaunchView;
  onViewChange: (view: AutoLaunchView) => void;
  accounts: Account[];
  managers: AccountManager[];
  project: Project;
  writesEnabled: boolean;
  tasks: TaskRow[];
}) {
  const [workflowDialogOpen, setWorkflowDialogOpen] = useState(false);

  return (
    <section className="auto-launch-page">
      <PageHeader
        title="自动上线"
        description="自动搭建、物料、创意与执行记录是相互独立的工作区"
        summary={
          <Badge appearance="tint" color={writesEnabled ? "success" : "warning"}>
            {writesEnabled ? "百度写入已开启" : "百度写入关闭 · 可先创建队列"}
          </Badge>
        }
      />
      <div className="auto-launch-tabbar">
        <nav
          className="auto-launch-tabs"
          role="tablist"
          aria-label="自动上线功能"
        >
          {autoLaunchViews.map((item) => {
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={view === item.id}
                className={view === item.id ? "active" : ""}
                onClick={() => onViewChange(item.id)}
                onKeyDown={(event) =>
                  moveHorizontalTab(
                    event,
                    autoLaunchViews.map((value) => value.id),
                    view,
                    onViewChange,
                  )
                }
              >
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <Button
          className="auto-launch-workflow-help"
          appearance="secondary"
          size="small"
          onClick={() => setWorkflowDialogOpen(true)}
        >
          搭建流程说明
        </Button>
      </div>
      <div className={`auto-launch-content auto-launch-${view}`}>
        {view === "materials" ? (
          <MaterialsPage project={project} />
        ) : view === "creatives" ? (
          <CreativeCenterPage project={project} />
        ) : view === "records" ? (
          <ExecutionRecordsPage
            project={project}
            initialTasks={tasks}
            adBuildOnly
          />
        ) : (
          <AdBuildPage
            accounts={accounts}
            managers={managers}
            project={project}
            writesEnabled={writesEnabled}
            onOpenRecords={() => onViewChange("records")}
          />
        )}
      </div>
      <BuildWorkflowHelpDialog
        open={workflowDialogOpen}
        onOpenChange={setWorkflowDialogOpen}
      />
    </section>
  );
}

function BuildWorkflowHelpDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const steps = [
    ["账户限额", "日预算 50 元"],
    ["账户推广地域", "直接更新账户地域；计划不设置地域"],
    ["计划与单元", "预埋户更新已有计划并复用单元；其他账户新建"],
    ["oCPC 项目", "使用本次填写的项目出价"],
    ["关键词", "二跳逐词生成 zhanghuid=账户ID、keyword=UTF-8编码、e_adposition={adposition}；一跳不传 URL"],
    ["人群 / 创意", "创意中心随机 50 组，并持续查询审核状态"],
  ] as const;

  return (
    <Dialog open={open} onOpenChange={(_, data) => onOpenChange(data.open)}>
      <DialogSurface className="standard-dialog workflow-dialog">
        <DialogBody>
          <DialogTitleWithSummary summary="查看当前搭建流程、字段规则与执行前置条件">搭建流程说明</DialogTitleWithSummary>
          <DialogContent>
            <p className="dialog-description">系统版本化搭建规则；运行时不依赖任何参考账户</p>
            <div className="workflow-hierarchy" aria-label="百度投放对象父子关系">
              <span><small>父级</small><strong>oCPC项目</strong></span>
              <i aria-hidden="true">→</i>
              <span><small>下级</small><strong>计划</strong></span>
              <i aria-hidden="true">→</i>
              <span><small>下级</small><strong>单元</strong></span>
              <i aria-hidden="true">→</i>
              <div className="workflow-hierarchy-branches">
                <span><small>单元下</small><strong>关键词</strong></span>
                <span><small>单元下</small><strong>创意</strong></span>
              </div>
            </div>
            <ol className="workflow-dialog-list">
              {steps.map(([label, detail]) => (
                <li key={label}>
                  <strong>{label}</strong>
                  <span>{detail}</span>
                </li>
              ))}
            </ol>
            <section className="workflow-dialog-guard"><strong>执行前置条件</strong><p>普通账户必须具备页面类型、推广页面和推广链接；一跳预埋户不校验链接；已有计划按系统规则更新，已有单元直接复用</p></section>
          </DialogContent>
          <DialogActions><Button appearance="primary" onClick={() => onOpenChange(false)}>知道了</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function AccountBalanceCell({ account }: { account: Account }) {
  if (!account.balance_snapshot_at) return <>—</>;
  const days = Number(account.balance_days_remaining);
  const hasDays = Number.isFinite(days);
  const title =
    account.balance_group_fresh && hasDays
      ? `同一钱柜 ${account.balance_group_account_count || 0} 个账户余额合计 ¥${Number(account.cash_group_balance || 0).toFixed(2)}；近7个完整自然日平均消耗 ¥${Number(account.average_daily_spend_7d || 0).toFixed(2)}/天；预计可用 ${days.toFixed(2)} 天`
      : "暂无完整的钱柜账户近7日平均消耗，暂不触发充值提醒";
  return (
    <span
      className={
        accountHasLowBalance(account)
          ? "account-balance is-low"
          : "account-balance"
      }
      title={title}
    >
      <strong>¥{Number(account.balance).toFixed(2)}</strong>
      {account.balance_group_fresh && hasDays && (
        <small>钱柜可用 {days.toFixed(2)} 天</small>
      )}
    </span>
  );
}

function ManagersAccountsPage({
  mode,
  managers,
  accounts,
  project,
  onRefresh,
  canManage,
}: {
  mode: "management" | "operations";
  managers: AccountManager[];
  accounts: Account[];
  project: Project;
  onRefresh: () => void;
  canManage: boolean;
}) {
  const [showManagerForm, setShowManagerForm] = useState(false);
  const [showBatchForm, setShowBatchForm] = useState(false);
  const [showBatchImport, setShowBatchImport] = useState(false);
  const [showCustomIdSettings, setShowCustomIdSettings] = useState(false);
  const [showCustomIdList, setShowCustomIdList] = useState(false);
  const [customIdInput, setCustomIdInput] = useState("");
  const [customIdSearch, setCustomIdSearch] = useState("");
  const [customIdList, setCustomIdList] = useState<CustomIdList | null>(null);
  const [customIdPage, setCustomIdPage] = useState(1);
  const [customIdPageSize, setCustomIdPageSize] = useState(20);
  const [customIdBusy, setCustomIdBusy] = useState(false);
  const [customIdListBusy, setCustomIdListBusy] = useState(false);
  const [customIdError, setCustomIdError] = useState<string | null>(null);
  const [customIdSuccess, setCustomIdSuccess] = useState<string | null>(null);
  const customIdPageCount = Math.max(
    1,
    Math.ceil((customIdList?.total ?? 0) / customIdPageSize),
  );
  const customIdSafePage = Math.min(customIdPage, customIdPageCount);
  const pagedCustomIds = (customIdList?.rows ?? []).slice(
    (customIdSafePage - 1) * customIdPageSize,
    customIdSafePage * customIdPageSize,
  );
  const [showCampaignBatch, setShowCampaignBatch] = useState(false);
  const [campaignStateConfirm, setCampaignStateConfirm] = useState<"start" | "pause" | null>(null);
  const [campaignAccountType, setCampaignAccountType] = useState("");
  const [campaignPageType, setCampaignPageType] = useState("");
  const [campaignSchedule, setCampaignSchedule] = useState<WeeklyScheduleWindow[]>(
    () => Array.from({ length: 7 }, (_, index) => ({
      weekDay: index + 1,
      startHour: 8,
      endHour: 24,
    })),
  );
  const [campaignPreview, setCampaignPreview] =
    useState<CampaignBatchPreview | null>(null);
  const [campaignBatchBusy, setCampaignBatchBusy] = useState(false);
  const [campaignBatchError, setCampaignBatchError] = useState<string | null>(
    null,
  );
  const [managerLogin, setManagerLogin] = useState("");
  const [managerName, setManagerName] = useState("");
  const [managerRebate, setManagerRebate] = useState("");
  const [managerRecharge, setManagerRecharge] = useState("");
  const [batchSelectors, setBatchSelectors] = useState("");
  const [batchOperator, setBatchOperator] = useState("");
  const [batchAccountType, setBatchAccountType] = useState("");
  const [batchPageType, setBatchPageType] = useState("");
  const [batchPromotionPage, setBatchPromotionPage] = useState("");
  const [batchLink, setBatchLink] = useState("");
  const [batchRebate, setBatchRebate] = useState("");
  const [batchRecharge, setBatchRecharge] = useState("");
  const [selectedAccountIds, setSelectedAccountIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const [templateBusy, setTemplateBusy] = useState(false);
  const [batchImportBusy, setBatchImportBusy] = useState(false);
  const [batchImportFile, setBatchImportFile] = useState<File | null>(null);
  const [batchImportPreview, setBatchImportPreview] =
    useState<AccountBatchImportPreview | null>(null);
  const [batchImportError, setBatchImportError] = useState<string | null>(null);
  const batchImportInput = useRef<HTMLInputElement>(null);
  const [oauthBusyId, setOauthBusyId] = useState<string | null>(null);
  const [syncBusyId, setSyncBusyId] = useState<string | null>(null);
  const [balanceBusyId, setBalanceBusyId] = useState<string | null>(null);
  const [managerStatusBusyId, setManagerStatusBusyId] = useState<string | null>(null);
  const [managerSettingsBusyId, setManagerSettingsBusyId] = useState<string | null>(null);
  const [archiveBusyId, setArchiveBusyId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{
    intent: "success" | "error";
    text: string;
  } | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("oauth") !== "success") return;
    const count = Number(params.get("accounts") || 0);
    setFeedback({
      intent: "success",
      text: `百度授权完成，已从账户管家同步 ${count} 个推广账户`,
    });
    if ("BroadcastChannel" in window) {
      const channel = new BroadcastChannel("baidu-search-oauth");
      channel.postMessage({
        projectId: params.get("project_id"),
        accountCount: count,
      });
      channel.close();
    }
    const shouldClose = params.get("oauth_window") === "1";
    window.history.replaceState({}, "", window.location.pathname);
    if (shouldClose) window.setTimeout(() => window.close(), 500);
  }, []);
  useEffect(() => {
    if (!("BroadcastChannel" in window)) return;
    const channel = new BroadcastChannel("baidu-search-oauth");
    channel.onmessage = (event) => {
      if (event.data?.projectId !== project.id) return;
      const count = Number(event.data?.accountCount || 0);
      setFeedback({
        intent: "success",
        text: `百度授权完成，已从账户管家同步 ${count} 个推广账户`,
      });
      onRefresh();
    };
    return () => channel.close();
  }, [project.id, onRefresh]);

  const prepareOAuthWindow = () => {
    const authWindow = window.open("about:blank", "_blank");
    if (!authWindow) {
      setFeedback({
        intent: "error",
        text: "浏览器拦截了授权页面，请允许本站打开新窗口后重试",
      });
      return null;
    }
    authWindow.opener = null;
    authWindow.document.title = "正在打开百度授权";
    authWindow.document.body.textContent = "正在打开百度授权页面…";
    return authWindow;
  };

  const createManager = async () => {
    setBusy(true);
    setFeedback(null);
    try {
      const manager = await apiPost<AccountManager>(
        `/projects/${project.id}/managers`,
        {
          login_name: managerLogin,
          display_name: managerName || null,
          rebate_rate: managerRebate.trim() ? Number(managerRebate) : null,
          recharge_account: managerRecharge.trim() || null,
        },
      );
      setShowManagerForm(false);
      setManagerLogin("");
      setManagerName("");
      setManagerRebate("");
      setManagerRecharge("");
    } catch (reason) {
      setFeedback({
        intent: "error",
        text: reason instanceof Error ? reason.message : "保存失败",
      });
    } finally {
      setBusy(false);
    }
  };
  const startOAuth = async (manager: AccountManager) => {
    const authWindow = prepareOAuthWindow();
    if (!authWindow) return;
    setOauthBusyId(manager.id);
    setFeedback(null);
    try {
      const result = await apiPost<{
        authorization_url: string;
        expires_in: number;
      }>(`/projects/${project.id}/managers/${manager.id}/oauth/start`, {});
      authWindow.location.replace(result.authorization_url);
      setOauthBusyId(null);
      setFeedback({
        intent: "success",
        text: "百度授权页面已在新标签页打开，请在新页面完成登录和授权",
      });
    } catch (reason) {
      authWindow.close();
      setFeedback({
        intent: "error",
        text: reason instanceof Error ? reason.message : "无法开始百度授权",
      });
      setOauthBusyId(null);
    }
  };
  const syncManagerAccounts = async (manager: AccountManager) => {
    setSyncBusyId(manager.id);
    setFeedback(null);
    try {
      const result = await apiPost<{
        account_count: number;
        created_count: number;
        updated_count: number;
        deactivated_count: number;
      }>(`/projects/${project.id}/managers/${manager.id}/accounts/sync`, {});
      setFeedback({
        intent: "success",
        text: `同步完成：当前 ${result.account_count} 个账户，新增 ${result.created_count} 个，更新 ${result.updated_count} 个`,
      });
      onRefresh();
    } catch (reason) {
      setFeedback({
        intent: "error",
        text:
          reason instanceof Error ? reason.message : "无法同步账户管家下辖账户",
      });
    } finally {
      setSyncBusyId(null);
    }
  };
  const startAccountOAuth = async (account: AccountManagementRow) => {
    const authWindow = prepareOAuthWindow();
    if (!authWindow) return;
    setOauthBusyId(account.id);
    setFeedback(null);
    try {
      const result = await apiPost<{
        authorization_url: string;
        expires_in: number;
      }>(`/projects/${project.id}/accounts/${account.id}/oauth/start`, {});
      authWindow.location.replace(result.authorization_url);
      setFeedback({
        intent: "success",
        text: `已打开“${account.account_name}”的单账户授权页面`,
      });
    } catch (reason) {
      authWindow.close();
      setFeedback({
        intent: "error",
        text: reason instanceof Error ? reason.message : "无法开始单账户授权",
      });
    } finally {
      setOauthBusyId(null);
    }
  };
  const refreshManagerBalance = async (manager: AccountManager) => {
    setBalanceBusyId(manager.id);
    setFeedback(null);
    try {
      const result = await apiPost<{
        account_id: number;
        account_name: string;
        balance: string;
      }>(`/projects/${project.id}/managers/${manager.id}/balance/refresh`, {});
      setFeedback({
        intent: "success",
        text: `充值账户 ${result.account_name} 余额已更新为 ¥${Number(result.balance).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
      });
      onRefresh();
    } catch (reason) {
      setFeedback({
        intent: "error",
        text: reason instanceof Error ? reason.message : "无法读取充值账户余额",
      });
    } finally {
      setBalanceBusyId(null);
    }
  };
  const setManagerActive = async (manager: AccountManager, isActive: boolean): Promise<boolean> => {
    setManagerStatusBusyId(manager.id);
    setFeedback(null);
    try {
      await apiPost<{
        manager_id: string;
        is_active: boolean;
        account_count: number;
      }>(`/projects/${project.id}/managers/${manager.id}/status`, {
        is_active: isActive,
      });
      setFeedback({
        intent: "success",
        text: isActive
          ? `账户管家“${manager.display_name || manager.login_name}”已启用`
          : `账户管家“${manager.display_name || manager.login_name}”已停用，账户、授权和历史数据均已保留`,
      });
      onRefresh();
      return true;
    } catch (reason) {
      setFeedback({
        intent: "error",
        text:
          reason instanceof Error
            ? reason.message
            : isActive
              ? "无法启用账户管家"
              : "无法停用账户管家",
      });
      return false;
    } finally {
      setManagerStatusBusyId(null);
    }
  };
  const updateManagerSettings = async (
    manager: AccountManager,
    changes: { rebate_rate?: number; balance_warning_threshold?: number | null },
  ): Promise<boolean> => {
    setManagerSettingsBusyId(manager.id);
    setFeedback(null);
    try {
      await apiPatch<{
        manager_id: string;
        rebate_rate: string | null;
        balance_warning_threshold: string | null;
      }>(`/projects/${project.id}/managers/${manager.id}/settings`, changes);
      setFeedback({
        intent: "success",
        text: "rebate_rate" in changes
          ? `账户管家“${manager.display_name || manager.login_name}”的返点已更新`
          : `账户管家“${manager.display_name || manager.login_name}”的余额预警已更新`,
      });
      onRefresh();
      return true;
    } catch (reason) {
      setFeedback({
        intent: "error",
        text: reason instanceof Error ? reason.message : "账户管家设置保存失败",
      });
      return false;
    } finally {
      setManagerSettingsBusyId(null);
    }
  };
  const archiveManager = async (manager: AccountManager) => {
    setArchiveBusyId(manager.id);
    setFeedback(null);
    try {
      const result = await apiPost<{ accounts_archived: number }>(
        `/projects/${project.id}/managers/${manager.id}/archive`,
        {},
      );
      setFeedback({
        intent: "success",
        text: `账户管家已删除，其下 ${result.accounts_archived} 个账户及全部历史数据已存档保留`,
      });
      onRefresh();
    } catch (reason) {
      setFeedback({
        intent: "error",
        text: reason instanceof Error ? reason.message : "无法删除账户管家",
      });
      throw reason;
    } finally {
      setArchiveBusyId(null);
    }
  };
  const submitBatchSettings = async () => {
    if (!selectedAccountIds.length) {
      setFeedback({
        intent: "error",
        text: "请先在账户表格中选择要设置的账户",
      });
      return;
    }
    const payload: Record<string, unknown> = {
      account_ids: selectedAccountIds,
    };
    if (batchOperator) payload.operator_name = batchOperator;
    if (batchAccountType) payload.account_type = batchAccountType;
    if (batchPageType) payload.page_type = batchPageType;
    if (batchPromotionPage) payload.promotion_page = batchPromotionPage;
    if (batchLink.trim()) payload.promotion_link = batchLink.trim();
    if (Object.keys(payload).length === 1) {
      setFeedback({ intent: "error", text: "请至少填写一项要批量设置的内容" });
      return;
    }
    setBatchBusy(true);
    setFeedback(null);
    try {
      const result = await apiPost<{
        matched_count: number;
        updated_count: number;
        manager_count: number;
        propagated_account_count: number;
        unmatched: string[];
        ambiguous: string[];
      }>(`/projects/${project.id}/accounts/batch-settings`, payload);
      const notes = [
        `已精确匹配并更新 ${result.updated_count} 个账户`,
        "",
        result.unmatched.length ? `未找到：${result.unmatched.join("、")}` : "",
        result.ambiguous.length
          ? `存在歧义未更新：${result.ambiguous.join("、")}`
          : "",
      ].filter(Boolean);
      setFeedback({
        intent:
          result.unmatched.length || result.ambiguous.length
            ? "error"
            : "success",
        text: `${notes.join("；")}`,
      });
      onRefresh();
      if (!result.unmatched.length && !result.ambiguous.length)
        setShowBatchForm(false);
    } catch (reason) {
      setFeedback({
        intent: "error",
        text: reason instanceof Error ? reason.message : "批量设置失败",
      });
    } finally {
      setBatchBusy(false);
    }
  };

  const downloadBatchTemplate = async () => {
    setTemplateBusy(true);
    setFeedback(null);
    try {
      await apiDownload(
        `/projects/${project.id}/accounts/batch-settings/template`,
      );
      setFeedback({
        intent: "success",
        text: "账户批量设置模板已下载，修改绿色区域后即可导入",
      });
    } catch (reason) {
      setFeedback({
        intent: "error",
        text: reason instanceof Error ? reason.message : "模板下载失败",
      });
    } finally {
      setTemplateBusy(false);
    }
  };

  const previewBatchImport = async (file: File) => {
    setBatchImportFile(file);
    setBatchImportPreview(null);
    setBatchImportError(null);
    setShowBatchForm(false);
    setShowBatchImport(true);
    setBatchImportBusy(true);
    try {
      const preview = await apiUpload<AccountBatchImportPreview>(
        `/projects/${project.id}/accounts/batch-settings/import/preview`,
        file,
      );
      setBatchImportPreview(preview);
    } catch (reason) {
      setBatchImportError(
        reason instanceof Error ? reason.message : "无法预检工作簿",
      );
    } finally {
      setBatchImportBusy(false);
      if (batchImportInput.current) batchImportInput.current.value = "";
    }
  };

  const confirmBatchImport = async () => {
    if (!batchImportFile || !batchImportPreview?.can_import) return;
    setBatchImportBusy(true);
    setBatchImportError(null);
    try {
      const result = await apiUpload<AccountBatchImportPreview>(
        `/projects/${project.id}/accounts/batch-settings/import`,
        batchImportFile,
      );
      setFeedback({
        intent: "success",
        text: `模板导入完成，已更新 ${result.updated_count ?? result.changed_count} 个账户`,
      });
      setShowBatchImport(false);
      setBatchImportFile(null);
      setBatchImportPreview(null);
      onRefresh();
    } catch (reason) {
      setBatchImportError(
        reason instanceof Error ? reason.message : "模板导入失败",
      );
    } finally {
      setBatchImportBusy(false);
    }
  };

  useEffect(() => {
    if (!showCustomIdList) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setCustomIdListBusy(true);
      const query = new URLSearchParams({ limit: "1000" });
      if (customIdSearch.trim()) query.set("search", customIdSearch.trim());
      apiGet<CustomIdList>(
        `/projects/${project.id}/custom-ids?${query}`,
        controller.signal,
      )
        .then((result) => {
          setCustomIdList(result);
          setCustomIdError(null);
        })
        .catch((reason) => {
          if (!controller.signal.aborted)
            setCustomIdError(
              reason instanceof Error ? reason.message : "读取自定义ID失败",
            );
        })
        .finally(() => {
          if (!controller.signal.aborted) setCustomIdListBusy(false);
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [showCustomIdList, project.id, customIdSearch]);
  const reloadCustomIds = async () => {
    const query = new URLSearchParams({ limit: "1000" });
    if (customIdSearch.trim()) query.set("search", customIdSearch.trim());
    setCustomIdList(
      await apiGet<CustomIdList>(`/projects/${project.id}/custom-ids?${query}`),
    );
  };
  const parseCustomIdInput = () => {
    const mappings: Array<{ account: string; custom_id: string }> = [];
    const errors: string[] = [];
    customIdInput.split(/\r?\n/).forEach((rawLine, index) => {
      const line = rawLine.trim();
      if (!line) return;
      const matched = line.match(/^(.*?)\s+(\S+)$/u);
      if (!matched?.[1]?.trim() || !matched[2]?.trim()) {
        errors.push(`第 ${index + 1} 行格式不正确`);
        return;
      }
      mappings.push({
        account: matched[1].trim(),
        custom_id: matched[2].trim(),
      });
    });
    return { mappings, errors };
  };
  const createCustomId = async () => {
    const parsed = parseCustomIdInput();
    if (parsed.errors.length) {
      setCustomIdError(
        `${parsed.errors.slice(0, 8).join("；")}；每行请使用“账户 空格或Tab 自定义ID”的格式`,
      );
      return;
    }
    if (!parsed.mappings.length) {
      setCustomIdError("请至少输入一条账户和自定义ID");
      return;
    }
    setCustomIdBusy(true);
    setCustomIdError(null);
    setCustomIdSuccess(null);
    try {
      const result = await apiPost<{
        submitted_count: number;
        created_count: number;
        unchanged_count: number;
      }>(`/projects/${project.id}/custom-ids/batch`, {
        mappings: parsed.mappings,
      });
      const successText = `已处理 ${result.submitted_count} 条：新增 ${result.created_count} 条，已有映射 ${result.unchanged_count} 条`;
      setFeedback({ intent: "success", text: successText });
      setCustomIdSuccess(successText);
      setCustomIdInput("");
      await reloadCustomIds();
    } catch (reason) {
      setCustomIdError(
        reason instanceof Error ? reason.message : "添加自定义ID失败",
      );
    } finally {
      setCustomIdBusy(false);
    }
  };

  const campaignScopePayload = () => ({
    account_type: campaignAccountType || null,
    page_type: campaignPageType || null,
    account_ids: selectedAccountIds,
  });
  const campaignRequestPayload = () => ({
    ...campaignScopePayload(),
    action: "schedule",
    online_schedule: campaignSchedule,
    pause: null,
  });
  const loadCampaignCurrent = async () => {
    setCampaignBatchError(null);
    try {
      const current = await apiPost<CampaignCurrentSetting>(
          `/projects/${project.id}/campaign-settings/current`,
          campaignScopePayload(),
        );
      if (current.online_schedule?.length) {
        setCampaignSchedule(current.online_schedule);
      } else if (
        current.online_weekdays?.length &&
        current.online_start_hour != null &&
        current.online_end_hour != null
      ) {
        setCampaignSchedule(current.online_weekdays.map((weekDay) => ({
          weekDay,
          startHour: current.online_start_hour as number,
          endHour: current.online_end_hour as number,
        })));
      }
    } catch (reason) {
      setCampaignBatchError(
        reason instanceof Error ? reason.message : "读取当前计划设置失败",
      );
    }
  };
  useEffect(() => {
    if (!showCampaignBatch) return;
    setCampaignPreview(null);
    void loadCampaignCurrent();
  }, [showCampaignBatch, project.id, campaignAccountType, campaignPageType]);
  const previewCampaignBatch = async () => {
    if (!campaignSchedule.length) {
      setCampaignBatchError("请至少选择一个启用时段");
      return;
    }
    setCampaignBatchBusy(true);
    setCampaignBatchError(null);
    try {
      setCampaignPreview(
        await apiPost<CampaignBatchPreview>(
          `/projects/${project.id}/campaign-batch/preview`,
          campaignRequestPayload(),
        ),
      );
    } catch (reason) {
      setCampaignPreview(null);
      setCampaignBatchError(
        reason instanceof Error ? reason.message : "计划批量设置预检失败",
      );
    } finally {
      setCampaignBatchBusy(false);
    }
  };
  const submitCampaignBatch = async () => {
    setCampaignBatchBusy(true);
    setCampaignBatchError(null);
    try {
      const result = await apiPost<{
        task_id: string;
        matched_account_count: number;
      }>(`/projects/${project.id}/campaign-batch`, campaignRequestPayload());
      setFeedback({
        intent: "success",
        text: `已提交 ${result.matched_account_count} 个账户的计划任务，任务编号 ${result.task_id.slice(0, 8)}`,
      });
      setCampaignPreview(null);
      await loadCampaignCurrent();
      onRefresh();
    } catch (reason) {
      setCampaignBatchError(
        reason instanceof Error ? reason.message : "提交计划批量设置失败",
      );
    } finally {
      setCampaignBatchBusy(false);
    }
  };
  const submitCampaignStateConfirm = async () => {
    if (!campaignStateConfirm) return;
    const paused = campaignStateConfirm === "pause";
    setCampaignBatchBusy(true);
    setCampaignBatchError(null);
    try {
      const result = await apiPost<{
        task_id: string;
        matched_account_count: number;
      }>(`/projects/${project.id}/campaign-batch`, {
        account_type: null,
        page_type: null,
        account_ids: selectedAccountIds,
        action: "pause",
        online_schedule: null,
        pause: paused,
      });
      setFeedback({
        intent: "success",
        text: `已提交 ${result.matched_account_count} 个账户的批量${paused ? "暂停" : "启动"}任务，任务编号 ${result.task_id.slice(0, 8)}`,
      });
      setCampaignStateConfirm(null);
      onRefresh();
    } catch (reason) {
      setCampaignBatchError(
        reason instanceof Error ? reason.message : `批量${paused ? "暂停" : "启动"}提交失败`,
      );
    } finally {
      setCampaignBatchBusy(false);
    }
  };
  const openCampaignBatch = (ids: string[]) => {
    setSelectedAccountIds(ids);
    setCampaignPreview(null);
    setCampaignBatchError(null);
    setShowCampaignBatch(true);
  };
  const openCampaignStateConfirm = (ids: string[], paused: boolean) => {
    setSelectedAccountIds(ids);
    setCampaignBatchError(null);
    setCampaignStateConfirm(paused ? "pause" : "start");
  };
  const selectorCount = selectedAccountIds.length;
  return (
    <>
      <PageHeader
        title={mode === "management" ? "账户管理" : "账户列表"}
        description={
          mode === "management"
            ? "管理账户管家、基础资料与授权"
            : "账户状态、成本判断与投放数据"
        }
      />
      {feedback && (
        <PopupMessage intent={feedback.intent}>{feedback.text}</PopupMessage>
      )}
      <Dialog
        open={showManagerForm}
        onOpenChange={(_, data) => {
          if (!busy) setShowManagerForm(data.open);
        }}
      >
        <DialogSurface className="manager-create-dialog">
          <DialogBody>
            <DialogTitleWithSummary summary="保存后可在管家列表中单独发起百度 OAuth 授权">添加账户管家</DialogTitleWithSummary>
            <DialogContent>
              <p className="dialog-description">
                返点和充值账户按管家统一管理。保存后可在管家列表中单独发起百度 OAuth 授权，系统不保存百度登录密码。
              </p>
              <div className="dialog-form">
                <Field label="管家登录名" required>
                  <Input
                    value={managerLogin}
                    onChange={(_, data) => setManagerLogin(data.value)}
                  />
                </Field>
                <Field label="显示名称">
                  <Input
                    value={managerName}
                    onChange={(_, data) => setManagerName(data.value)}
                  />
                </Field>
                <Field label="统一返点（%）">
                  <Input
                    type="number"
                    min={0}
                    max={100}
                    step={0.01}
                    value={managerRebate}
                    onChange={(_, data) => setManagerRebate(data.value)}
                    placeholder="0–100"
                  />
                </Field>
                <Field label="统一充值账户">
                  <Input
                    value={managerRecharge}
                    onChange={(_, data) => setManagerRecharge(data.value)}
                    placeholder="钱柜账户名称"
                  />
                </Field>
              </div>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                disabled={busy}
                onClick={() => setShowManagerForm(false)}
              >
                取消
              </Button>
              <Button
                appearance="primary"
                disabled={busy || !managerLogin.trim()}
                onClick={() => void createManager()}
              >
                {busy ? "正在保存…" : "保存"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog
        open={showCustomIdSettings}
        onOpenChange={(_, data) => {
          if (!customIdBusy) setShowCustomIdSettings(data.open);
        }}
      >
        <DialogSurface className="custom-id-setting-dialog">
          <DialogBody>
            <DialogTitleWithSummary summary="批量添加账户与自定义ID的映射">
              设置自定义ID
            </DialogTitleWithSummary>
            <DialogContent>
              <p className="dialog-description">
                自定义ID用于匹配好多粉访问链接中的
                zhanghuid；账户必须在当前项目内精确匹配，已有绑定不会被自动覆盖
              </p>
              <section className="custom-id-create-panel">
                <Field
                  className="custom-id-input-field"
                  label="账户　自定义ID"
                  required
                >
                  <Textarea
                    className="custom-id-batch-input"
                    resize="vertical"
                    rows={6}
                    value={customIdInput}
                    onChange={(_, data) => {
                      setCustomIdInput(data.value);
                      setCustomIdError(null);
                      setCustomIdSuccess(null);
                    }}
                    placeholder={
                      "baidu-示例账户01    yyl042401\nbaidu-示例账户02\tyyl042402"
                    }
                  />
                </Field>
                <p className="custom-id-usage-note">支持 空格/Tab</p>
                {customIdError ? (
                  <PopupMessage intent="error">{customIdError}</PopupMessage>
                ) : null}
                {customIdSuccess ? (
                  <PopupMessage intent="success">
                    {customIdSuccess}
                  </PopupMessage>
                ) : null}
              </section>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                disabled={customIdBusy}
                onClick={() => setShowCustomIdSettings(false)}
              >
                取消
              </Button>
              <Button
                appearance="primary"
                disabled={customIdBusy || !customIdInput.trim()}
                onClick={() => void createCustomId()}
              >
                {customIdBusy ? "添加中…" : "批量添加映射"}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog
        open={showCustomIdList}
        onOpenChange={(_, data) => setShowCustomIdList(data.open)}
      >
        <DialogSurface className="custom-id-dialog">
          <DialogBody>
            <DialogTitleWithSummary summary="查询当前项目已建立的账户映射">
              自定义ID列表
            </DialogTitleWithSummary>
            <DialogContent>
              <section className="custom-id-list-panel">
                <div className="custom-id-list-head">
                  <div className="custom-id-list-summary">
                    <strong>已有自定义ID</strong>
                    <span>
                      {customIdList
                        ? `共 ${customIdList.total} 条`
                        : "正在读取"}
                    </span>
                  </div>
                  <SearchField
                    ariaLabel="搜索自定义ID"
                    value={customIdSearch}
                    onChange={(value) => {
                      setCustomIdSearch(value);
                      setCustomIdPage(1);
                    }}
                    placeholder="账户 / 自定义ID / 账户ID"
                  />
                </div>
                {customIdError ? (
                  <PopupMessage intent="error">{customIdError}</PopupMessage>
                ) : null}
                {customIdListBusy && !customIdList ? (
                  <Skeleton className="custom-id-loading">
                    <SkeletonItem />
                    <SkeletonItem />
                    <SkeletonItem />
                  </Skeleton>
                ) : pagedCustomIds.length ? (
                  <div className="custom-id-table-scroll">
                    <table className="custom-id-table">
                      <thead>
                        <tr>
                          <th className="table-cell--start">账户名称</th>
                          <th className="table-cell--start table-cell--id">账户ID</th>
                          <th className="table-cell--start table-cell--id">自定义ID</th>
                          <th className="table-cell--center table-cell--date">更新时间</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pagedCustomIds.map((row) => (
                          <tr key={row.id}>
                            <td className="table-cell--start">
                              <span>{row.account_name}</span>
                            </td>
                            <td className="table-cell--start table-cell--id">{row.account_id}</td>
                            <td className="table-cell--start table-cell--id">
                              <strong>{row.custom_id}</strong>
                            </td>
                            <td className="table-cell--center table-cell--date">{formatDateTime(row.updated_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="custom-id-empty">
                    {customIdListBusy
                      ? "正在搜索…"
                      : customIdSearch.trim()
                        ? "没有匹配的自定义ID"
                        : "当前项目还没有自定义ID"}
                  </div>
                )}
                {customIdList?.total ? (
                  <ViewportStickyPagination
                    contained
                    page={customIdSafePage}
                    totalPages={customIdPageCount}
                    total={customIdList.total}
                    pageSize={customIdPageSize}
                    loading={customIdListBusy}
                    ariaLabel="自定义ID列表分页"
                    onPageChange={setCustomIdPage}
                    onPageSizeChange={(size) => {
                      setCustomIdPage(1);
                      setCustomIdPageSize(size);
                    }}
                  />
                ) : null}
              </section>
            </DialogContent>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog
        open={showCampaignBatch}
        onOpenChange={(_, data) => {
          if (!campaignBatchBusy) setShowCampaignBatch(data.open);
        }}
      >
        <DialogSurface
          className="campaign-batch-dialog"
          style={{ width: "min(980px, calc(100vw - 32px))", maxWidth: "980px" }}
        >
          <DialogBody>
            <DialogTitleWithSummary summary="为已选账户统一设置每周启用时段">
              批量设置计划时段
            </DialogTitleWithSummary>
            <DialogContent className="campaign-dialog-content">
              <WeeklyScheduleSelector
                value={campaignSchedule}
                ariaLabel="每周计划启用时段"
                selectedLabel="启用时段"
                unselectedLabel="暂停时段"
                onChange={(next) => {
                  setCampaignSchedule(next);
                  setCampaignPreview(null);
                  setCampaignBatchError(null);
                }}
              />
              {campaignBatchError ? (
                <PopupMessage intent="error">{campaignBatchError}</PopupMessage>
              ) : null}
              {campaignPreview ? (
                <PopupMessage
                  intent={
                    campaignPreview.matched_account_count &&
                    campaignPreview.writes_enabled
                      ? "success"
                      : "warning"
                  }
                >
                  预检完成：匹配 {campaignPreview.matched_account_count}{" "}
                  个账户；
                  {`系统已换算为 ${campaignPreview.pause_schedule?.length || 0} 个百度暂停区间`}
                  {!campaignPreview.matched_account_count
                    ? "当前范围没有可执行账户"
                    : campaignPreview.writes_enabled
                      ? "可提交后台执行"
                      : "当前百度写入开关关闭，只能预检"}
                </PopupMessage>
              ) : null}
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                disabled={campaignBatchBusy}
                onClick={() => setShowCampaignBatch(false)}
              >
                取消
              </Button>
              <Button
                appearance="secondary"
                disabled={campaignBatchBusy}
                onClick={() => void previewCampaignBatch()}
              >
                {campaignBatchBusy ? "处理中…" : "预检"}
              </Button>
              <Button
                appearance="primary"
                disabled={
                  campaignBatchBusy ||
                  !campaignPreview?.matched_account_count ||
                  !campaignPreview.writes_enabled
                }
                onClick={() => void submitCampaignBatch()}
              >
                提交后台任务
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog
        open={campaignStateConfirm !== null}
        onOpenChange={(_, data) => {
          if (!data.open && !campaignBatchBusy) {
            setCampaignStateConfirm(null);
            setCampaignBatchError(null);
          }
        }}
      >
        <DialogSurface className="account-confirm-dialog campaign-state-confirm-dialog">
          <DialogBody>
            <DialogTitleWithSummary summary="确认后将提交后台批量执行">
              确认批量{campaignStateConfirm === "pause" ? "暂停" : "启动"}
            </DialogTitleWithSummary>
            <DialogContent>
              <p>
                确定将已选择的 {selectedAccountIds.length} 个账户中的全部计划批量
                {campaignStateConfirm === "pause" ? "暂停" : "启动"}吗？
              </p>
              {campaignBatchError ? <PopupMessage intent="error">{campaignBatchError}</PopupMessage> : null}
            </DialogContent>
            <DialogActions>
              <Button appearance="secondary" disabled={campaignBatchBusy} onClick={() => setCampaignStateConfirm(null)}>取消</Button>
              <Button className={campaignStateConfirm === "pause" ? "campaign-state-confirm-action is-pause" : "campaign-state-confirm-action"} appearance="primary" disabled={campaignBatchBusy} onClick={() => void submitCampaignStateConfirm()}>
                {campaignBatchBusy ? "提交中…" : `确认${campaignStateConfirm === "pause" ? "暂停" : "启动"}`}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog
        open={showBatchForm}
        onOpenChange={(_, data) => {
          if (!batchBusy) setShowBatchForm(data.open);
        }}
      >
        <DialogSurface className="batch-dialog">
          <DialogBody>
            <DialogTitleWithSummary summary="按账户名称或账号主体精确匹配后批量写入资料">
              批量设置账户资料
            </DialogTitleWithSummary>
            <DialogContent>
              <div className="batch-selection-summary">
                <span>本次设置范围</span>
                <strong>{selectorCount} 个已选账户</strong>
                <small>
                  只修改表格中明确勾选的账户，不读取 Excel，也不会扩大到同名账户
                </small>
              </div>
              <section className="batch-settings-panel">
                <div className="batch-section-heading">
                  <div>
                    <strong>统一设置</strong>
                    <span>留空即保持原值</span>
                  </div>
                </div>
                <div className="batch-dialog-fields">
                  <>
                      <Field label="运营">
                        <select
                          value={batchOperator}
                          onChange={(event) =>
                            setBatchOperator(event.target.value)
                          }
                        >
                          <option value="">不修改</option>
                          <option value="王康">王康</option>
                          <option value="王聪">王聪</option>
                        </select>
                      </Field>
                      <Field label="账户类型">
                        <select
                          value={batchAccountType}
                          onChange={(event) =>
                            setBatchAccountType(event.target.value)
                          }
                        >
                          <option value="">不修改</option>
                          <option value="一跳预埋户">一跳预埋户</option>
                          <option value="一跳空户">一跳空户</option>
                          <option value="二跳账户">二跳账户</option>
                        </select>
                      </Field>
                      <Field label="页面类型">
                        <select
                          value={batchPageType}
                          onChange={(event) =>
                            setBatchPageType(event.target.value)
                          }
                        >
                          <option value="">不修改</option>
                          <option value="科普账户">科普账户</option>
                          <option value="软文账户">软文账户</option>
                        </select>
                      </Field>
                      <Field label="推广页面">
                        <select
                          value={batchPromotionPage}
                          onChange={(event) =>
                            setBatchPromotionPage(event.target.value)
                          }
                        >
                          <option value="">不修改</option>
                          <option value="科普基木鱼">科普基木鱼</option>
                          <option value="科普全文">科普全文</option>
                          <option value="精华帖">精华帖</option>
                          <option value="中医论坛">中医论坛</option>
                          <option value="中医秘方">中医秘方</option>
                          <option value="快瘦汤">快瘦汤</option>
                        </select>
                      </Field>
                      <Field className="batch-field-wide" label="推广链接">
                        <Input
                          value={batchLink}
                          onChange={(_, data) => setBatchLink(data.value)}
                          placeholder="https://..."
                        />
                      </Field>
                  </>
                </div>
                <div className="batch-rule-note">
                  <span>
                    <strong>安全写入</strong>{" "}
                    提交前显示明确账户数；空白字段不会清空已有设置
                  </span>
                </div>
              </section>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                disabled={batchBusy}
                onClick={() => setShowBatchForm(false)}
              >
                取消
              </Button>
              <Button
                appearance="primary"
                disabled={batchBusy || !selectorCount}
                onClick={() => void submitBatchSettings()}
              >
                {batchBusy ? "设置中…" : `确认设置 ${selectorCount} 个账户`}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog
        open={showBatchImport}
        onOpenChange={(_, data) => {
          if (!batchImportBusy) setShowBatchImport(data.open);
        }}
      >
        <DialogSurface className="batch-import-dialog">
          <DialogBody>
            <DialogTitleWithSummary summary="上传模板后先预检，再生成批量设置结果">导入批量设置</DialogTitleWithSummary>
            <DialogContent>
              <div className="import-file-bar">
                <div>
                  <strong>{batchImportFile?.name || "尚未选择文件"}</strong>
                  <span>系统先校验整张表，确认后才会写入数据库</span>
                </div>
                <Button
                  size="small"
                  appearance="secondary"
                  disabled={batchImportBusy}
                  onClick={() => batchImportInput.current?.click()}
                >
                  重新选择
                </Button>
              </div>
              {batchImportBusy && !batchImportPreview ? (
                <div className="import-checking">
                  <Skeleton>
                    <SkeletonItem />
                    <SkeletonItem />
                    <SkeletonItem />
                  </Skeleton>
                  <span>正在核对账户、字段和变更内容…</span>
                </div>
              ) : null}
              {batchImportError ? (
                <PopupMessage intent="error">{batchImportError}</PopupMessage>
              ) : null}
              {batchImportPreview ? (
                <>
                  <div className="import-preview-stats">
                    <div>
                      <span>有效数据</span>
                      <strong>{batchImportPreview.row_count}</strong>
                    </div>
                    <div>
                      <span>匹配账户</span>
                      <strong>{batchImportPreview.matched_count}</strong>
                    </div>
                    <div className="is-change">
                      <span>将更新</span>
                      <strong>{batchImportPreview.changed_count}</strong>
                    </div>
                    <div>
                      <span>保持不变</span>
                      <strong>{batchImportPreview.unchanged_count}</strong>
                    </div>
                    <div
                      className={
                        batchImportPreview.invalid_count ? "is-error" : ""
                      }
                    >
                      <span>错误</span>
                      <strong>{batchImportPreview.invalid_count}</strong>
                    </div>
                  </div>
                  {batchImportPreview.invalid_count ? (
                    <div className="import-error-panel">
                      <div>
                        <strong>请先修正以下内容</strong>
                        <span>存在错误时整份文件都不会写入</span>
                      </div>
                      <ul>
                        {batchImportPreview.errors
                          .slice(0, 12)
                          .map((error, index) => (
                            <li key={`${error.row}-${index}`}>
                              <b>第 {error.row} 行</b>
                              <span>
                                {error.selector ? `${error.selector}：` : ""}
                                {error.message}
                              </span>
                            </li>
                          ))}
                      </ul>
                      {batchImportPreview.errors.length > 12 ? (
                        <small>
                          另有 {batchImportPreview.errors.length - 12}{" "}
                          条错误，请修正后重新上传
                        </small>
                      ) : null}
                    </div>
                  ) : batchImportPreview.changed_count ? (
                    <PopupMessage intent="success">
                      预检通过；确认后将更新 {batchImportPreview.changed_count}{" "}
                      个账户，{batchImportPreview.unchanged_count}{" "}
                      个账户保持不变
                    </PopupMessage>
                  ) : (
                    <PopupMessage intent="info">
                      工作簿与当前数据一致，没有需要更新的内容
                    </PopupMessage>
                  )}
                </>
              ) : null}
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                disabled={batchImportBusy}
                onClick={() => setShowBatchImport(false)}
              >
                取消
              </Button>
              <Button
                appearance="primary"
                disabled={batchImportBusy || !batchImportPreview?.can_import}
                onClick={() => void confirmBatchImport()}
              >
                {batchImportBusy && batchImportPreview
                  ? "导入中…"
                  : `确认导入${batchImportPreview?.changed_count ? ` ${batchImportPreview.changed_count} 个账户` : ""}`}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <AccountWorkspaceTable
        mode={mode}
        project={project}
        managers={managers}
        onAddManager={() => setShowManagerForm(true)}
        onOpenCustomIdSettings={() => {
          setCustomIdError(null);
          setCustomIdSuccess(null);
          setShowCustomIdSettings(true);
        }}
        onOpenCustomIdList={() => {
          setCustomIdError(null);
          setCustomIdSuccess(null);
          setShowCustomIdList(true);
        }}
        onOpenCampaignSchedule={(ids) => openCampaignBatch(ids)}
        onConfirmCampaignState={(ids, paused) => openCampaignStateConfirm(ids, paused)}
        onOpenBatchSettings={(ids) => {
          setSelectedAccountIds(ids);
          setShowBatchForm(true);
        }}
        onAuthorizeManager={(manager) => void startOAuth(manager)}
        onAuthorizeAccount={(account) => void startAccountOAuth(account)}
        onSyncManagerAccounts={(manager) => void syncManagerAccounts(manager)}
        onRefreshManagerBalance={(manager) =>
          void refreshManagerBalance(manager)
        }
        onSetManagerActive={setManagerActive}
        onUpdateManagerSettings={updateManagerSettings}
        onArchiveManager={archiveManager}
        oauthBusyId={oauthBusyId}
        syncBusyId={syncBusyId}
        balanceBusyId={balanceBusyId}
        statusBusyId={managerStatusBusyId}
        settingsBusyId={managerSettingsBusyId}
        archiveBusyId={archiveBusyId}
        canManage={canManage}
      />
    </>
  );
}

type ExecutionStatusFilter =
  | "all"
  | "active"
  | "waiting"
  | "succeeded"
  | "failed";
type ExecutionActionFilter =
  | "all"
  | "campaign_schedule"
  | "campaign_pause"
  | "budget"
  | "data_sync"
  | "ad_build"
  | "elimination"
  | "other";

const executionActionTabs: Array<[ExecutionActionFilter, string]> = [
  ["all", "全部动作"],
  ["campaign_schedule", "批量时段"],
  ["campaign_pause", "暂停 / 启用"],
  ["budget", "预算操作"],
  ["data_sync", "数据同步"],
  ["ad_build", "广告新建 / 清理"],
  ["elimination", "账户淘汰"],
  ["other", "其他"],
];

const adBuildExecutionNodeColumns = [
  ["material_preflight", "物料预检"],
  ["account_settings", "账户设置"],
  ["campaigns", "计划"],
  ["adgroups", "单元"],
  ["ocpc", "oCPC"],
  ["keywords", "关键词"],
  ["audiences", "人群"],
  ["creatives", "创意"],
  ["final_readback", "回读验证"],
] as const;

function adBuildExecutionStatusText(status: string, scheduledAt: string) {
  const scheduledTimestamp = Date.parse(scheduledAt);
  if (
    ["pending", "scheduled"].includes(status) &&
    Number.isFinite(scheduledTimestamp) &&
    scheduledTimestamp > Date.now()
  ) {
    return "等待";
  }
  return statusText(status);
}

function taskActionGroup(task: TaskRow): Exclude<ExecutionActionFilter, "all"> {
  if (task.task_type === "campaign_batch_update") {
    return task.execution_action === "pause"
      ? "campaign_pause"
      : "campaign_schedule";
  }
  if (
    ["budget_reset_automation", "budget_append_automation"].includes(
      task.task_type,
    )
  )
    return "budget";
  if (task.task_type === "account_elimination_cycle") return "elimination";
  if (
    ["search_ad_build_workflow", "search_ad_build_cleanup"].includes(
      task.task_type,
    )
  )
    return "ad_build";
  if (
    task.task_type.includes("sync") ||
    task.task_type.includes("refresh") ||
    task.task_type.includes("backfill") ||
    task.task_type.includes("archive") ||
    task.task_type.includes("snapshot") ||
    task.task_type.includes("capture") ||
    task.task_type.includes("import")
  )
    return "data_sync";
  return "other";
}

function taskDisplayText(task: TaskRow) {
  if (task.task_type === "campaign_batch_update") {
    return task.execution_action === "pause"
      ? "计划批量暂停 / 启用"
      : "计划批量时段";
  }
  return taskTypeText(task.task_type);
}

function taskTypeText(value: string) {
  return (
    (
      {
        campaign_batch_update: "计划时段与启停修改",
        campaign_cache_sync: "计划数据同步",
        budget_reset_automation: "预算重置",
        budget_append_automation: "预算追加",
        account_elimination_cycle: "账户淘汰",
        baidu_account_hourly_refresh: "账户数据小时同步",
        baidu_account_backfill: "账户数据补齐",
        baidu_account_final_archive: "账户日报归档",
        baidu_budget_snapshot: "账户余额同步",
        baidu_keyword_backfill: "关键词数据补齐",
        baidu_keyword_daily_archive: "关键词日报归档",
        hduofen_capture: "好多粉数据采集",
        hduofen_history_import: "好多粉历史数据导入",
        creative_review_sync: "创意审核同步",
        reference_template_sync: "参考模板同步",
        search_ad_build_workflow: "账户广告新建",
        search_ad_build_cleanup: "账户广告清理",
      } as Record<string, string>
    )[value] || value.replaceAll("_", " ")
  );
}

function taskNodeText(value: string) {
  if (value.startsWith("read_campaigns_"))
    return `正在读取账户 ${value.replace("read_campaigns_", "")} 的计划`;
  if (value.startsWith("sync_campaigns_"))
    return `正在同步账户 ${value.replace("sync_campaigns_", "")} 的计划`;
  if (value.startsWith("cached_"))
    return `账户 ${value.replace("cached_", "")} 的计划已缓存`;
  if (value.startsWith("verified_"))
    return `已回读验证账户 ${value.replace("verified_", "")}`;
  if (value.startsWith("keywords_batch_"))
    return `正在提交第 ${value.replace("keywords_batch_", "")} 批关键词`;
  if (value.startsWith("keywords_acknowledged_"))
    return `关键词已提交至第 ${value.replace("keywords_acknowledged_", "")} 个单元`;
  return (
    (
      {
        queued: "等待调度",
        queued_for_resume: "等待续跑",
        adgroup_readback_wait: "百度单元数据延迟可见，等待后台回读验证",
        heartbeat_timeout: "任务心跳超时，需要处理",
        campaign_batch_auto_retry_wait: "失败账户等待自动安全续跑",
        campaign_batch_auto_retry_dispatched: "失败账户已进入自动续跑队列",
        campaign_batch_auto_retry_scheduled: "已安排失败账户自动安全续跑",
        next_account_batch: "等待执行下一批账户",
        rate_limited: "百度接口限频，等待自动继续",
        complete: "全部完成",
        account_failed: "当前账户执行失败",
        campaign_batch_incomplete: "部分账户执行失败",
        waiting_writes: "等待百度写入开启",
        authorization_blocked: "百度授权不可用",
        scheduled: "等待计划时间执行",
        fetch_account_budget_snapshot: "正在读取账户余额",
        budget_snapshot_blocked: "账户余额读取受阻",
        budget_snapshot_complete: "账户余额同步完成",
        budget_snapshot_incomplete: "部分账户余额读取失败",
        baidu_writes_disabled: "等待开启百度写入",
        budget_reset_execute: "正在重置账户预算",
        budget_reset_complete: "预算重置完成",
        budget_append_execute: "正在追加账户预算",
        budget_append_complete: "预算追加完成",
        data_freshness_guard: "数据尚未闭环，已停止自动操作",
        invalid_request: "任务参数无效",
        scope_recheck_skipped: "账户已不在本次执行范围",
        campaign_cache_incomplete: "部分账户计划缓存失败",
        template_ready: "参考模板同步完成",
        reference_sync_failed: "参考模板同步失败",
        fetch_account_daily_reports: "正在读取账户日报",
        account_daily_backfill_complete: "账户数据同步完成",
        account_daily_backfill_incomplete: "部分账户数据同步失败",
        fetch_second_hop_keyword_daily_reports: "正在读取二跳账户关键词日报",
        keyword_report_blocked: "关键词报表读取受阻",
        keyword_daily_backfill_complete: "关键词数据同步完成",
        keyword_daily_backfill_incomplete: "部分关键词数据同步失败",
        runtime_disabled: "好多粉采集未启用",
        final_archive_protected: "最终归档受数据保护规则阻止",
        capture_complete: "好多粉采集完成",
        capture_failed: "好多粉采集失败",
        capture_blocked: "好多粉采集受阻",
        incomplete_dataset: "采集数据不完整，未写入正式数据",
        history_import_complete: "好多粉历史数据导入完成",
        elimination_complete: "账户淘汰完成",
        elimination_incomplete: "部分账户淘汰失败",
        no_matching_accounts: "没有符合条件的账户",
        automation_write_disabled: "自动操作写入未开启",
        waiting_for_2300_data: "等待当天 23:00 数据闭环",
        delete_account_campaigns: "正在删除淘汰账户计划",
        queued_safety_check: "等待安全检查",
        failed: "执行失败",
        material_preflight: "检查物料与账户配置",
        adgroups: "正在创建单元",
        campaigns: "正在创建计划",
        keywords: "正在提交关键词",
        audiences: "正在配置人群",
        creatives: "正在创建创意",
        permission_and_material_preflight: "权限与物料检查完成",
        account_settings_verified: "账户设置已更新并验证",
        campaign_verified: "计划已新建并验证",
        adgroups_verified: "单元已新建并验证",
        ocpc_project_verified: "项目出价已设置并验证",
        keywords_acknowledged: "关键词已提交，正在继续后续步骤",
        keyword_batches_planned: "关键词批次已规划",
        keyword_deferred_for_account_activation: "等待账户生效后继续提交关键词",
        keyword_activation_bootstrap_ready: "账户生效，准备继续关键词任务",
        audiences_verified: "人群已新建并验证",
        creatives_verified: "创意已新建并验证",
        awaiting_baidu_account_activation: "等待百度账户生效",
        cleanup_inventory_verified: "已核对待清理对象",
        audience_bindings_deleted: "人群绑定已清理",
        ocpc_deleted: "项目出价已清理",
        campaigns_deleted: "计划及下级对象已清理",
        audiences_deleted: "人群已清理",
      } as Record<string, string>
    )[value] || "未知节点"
  );
}

function taskReadbackText(task: TaskRow) {
  if (!task.readback) return null;
  const parts = [
    ["计划", task.readback.campaign_count],
    ["单元", task.readback.adgroup_count],
    ["关键词", task.readback.keyword_count],
    ["创意", task.readback.creative_count],
    ["人群", task.readback.audience_count],
  ].filter((item): item is [string, number] => typeof item[1] === "number");
  return parts.length
    ? `百度回读：${parts.map(([label, value]) => `${label} ${value.toLocaleString("zh-CN")}`).join(" · ")}`
    : null;
}

function taskProblemTitle(task: TaskRow) {
  if (task.current_node === "campaign_batch_auto_retry_scheduled")
    return "自动安全续跑已安排";
  if (task.current_node === "adgroup_readback_wait") return "后台延迟验证中";
  if (task.current_node === "heartbeat_timeout") return "心跳超时 / 需要处理";
  if (task.superseded) return "历史失败，后续已完成";
  if (task.last_error) return "需要处理";
  if (task.status === "blocked") return "等待处理";
  if (task.status === "succeeded")
    return task.readback ? "回读完成" : "执行完成";
  if (task.status === "running") return "正在执行";
  return "等待执行";
}

function readableTaskError(error: string) {
  if (error === "required data snapshots are incomplete or stale") {
    return "百度或好多粉数据尚未完整同步，系统已停止自动操作";
  }
  const budgetFailures = error.match(/^(\d+) account budget snapshots failed$/);
  if (budgetFailures)
    return `${budgetFailures[1]} 个账户余额读取失败，请查看账户明细`;
  const accountFailures = error.match(/^(\d+) accounts failed$/);
  if (accountFailures)
    return `${accountFailures[1]} 个账户执行失败，请查看账户明细`;
  if (error.includes("好多粉采集失败：IntegrityError")) {
    return "好多粉数据写入时发现重复或冲突记录，任务已停止";
  }
  return error;
}

function taskProblemText(task: TaskRow) {
  if (task.superseded)
    return "同一账户已有更新的成功任务，本次历史失败无需续跑";
  if (task.last_error) return readableTaskError(task.last_error);
  return (
    taskReadbackText(task) ||
    task.result_summary ||
    taskNodeText(task.current_node)
  );
}

function taskRecoveryHint(task: TaskRow) {
  if (!task.last_error) return null;
  if (task.current_node === "adgroup_readback_wait")
    return "后台只会重新查询单元，不会再次创建；无需手工续跑";
  if (task.current_node === "heartbeat_timeout")
    return "任务已停止显示为运行中；请先核对百度实际状态，再决定是否安全续跑";
  if (task.last_error.includes("BAIDU_ACCOUNT_ACTIVATION_REQUIRED"))
    return "账户生效后可从当前节点安全续跑";
  if (
    task.last_error.includes("90180006493") ||
    task.last_error.includes("创意")
  )
    return "拒绝组合会进入黑名单，续跑时改用已通过组合";
  return "问题处理后可从当前节点安全续跑，不重复已成功步骤";
}

function taskBadgeColor(
  status: string,
): "success" | "danger" | "warning" | "informative" {
  if (status === "succeeded") return "success";
  if (status === "failed") return "danger";
  if (status === "blocked") return "warning";
  return "informative";
}

export function ExecutionRecordsPage({
  project,
  initialTasks,
  strategyScope,
  adBuildOnly = false,
}: {
  project: Project;
  initialTasks: TaskRow[];
  strategyScope?: StrategyAction;
  adBuildOnly?: boolean;
}) {
  const [rows, setRows] = useState<TaskRow[]>(initialTasks);
  const [buildJobs, setBuildJobs] = useState<AdBuildJob[]>([]);
  const [filter, setFilter] = useState<ExecutionStatusFilter>("all");
  const [actionFilter, setActionFilter] =
    useState<ExecutionActionFilter>("all");
  const [recordKeyword, setRecordKeyword] = useState("");
  const [recordPage, setRecordPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [cancelTaskId, setCancelTaskId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date>(new Date());

  const load = async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [nextRows, nextBuildJobs] = await Promise.all([
        apiGet<TaskRow[]>(`/projects/${project.id}/tasks`),
        apiGet<AdBuildJob[]>(`/projects/${project.id}/ad-builds`),
      ]);
      setRows(nextRows);
      setBuildJobs(nextBuildJobs);
      setLastUpdatedAt(new Date());
      setError(null);
    } catch (reason) {
      if (!quiet)
        setError(reason instanceof Error ? reason.message : "读取执行记录失败");
    } finally {
      if (!quiet) setLoading(false);
    }
  };

  useEffect(() => {
    let mounted = true;
    setRows(initialTasks);
    setRecordPage(1);
    setActionFilter("all");
    setRecordKeyword("");
    const refresh = () =>
      Promise.all([
        apiGet<TaskRow[]>(`/projects/${project.id}/tasks`),
        apiGet<AdBuildJob[]>(`/projects/${project.id}/ad-builds`),
      ])
        .then(([nextRows, nextBuildJobs]) => {
          if (mounted) {
            setRows(nextRows);
            setBuildJobs(nextBuildJobs);
            setError(null);
            setLastUpdatedAt(new Date());
          }
        })
        .catch(() => undefined);
    void refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [project.id]);

  const scopedRows = rows.filter((item) =>
    adBuildOnly
      ? item.task_type === "search_ad_build_workflow"
      : !strategyScope ||
        (strategyScope === "budget_reset"
          ? item.task_type === "budget_reset_automation"
          : strategyScope === "budget_append"
            ? item.task_type === "budget_append_automation"
            : strategyScope === "elimination"
              ? item.task_type === "account_elimination_cycle"
              : [
                    "baidu_account_backfill",
                    "baidu_account_hourly_refresh",
                    "baidu_account_final_archive",
                    "baidu_keyword_backfill",
                    "baidu_keyword_daily_archive",
                    "hduofen_capture",
                    "baidu_budget_snapshot",
                    "creative_review_sync",
                  ].includes(item.task_type)),
  );
  const activeCount = scopedRows.filter((item) =>
    ["pending", "running"].includes(item.status),
  ).length;
  const runningCount = scopedRows.filter((item) => item.status === "running").length;
  const waitingCount = scopedRows.filter((item) => item.status === "pending").length;
  const succeededCount = scopedRows.filter(
    (item) => item.status === "succeeded",
  ).length;
  const failedCount = scopedRows.filter(
    (item) => ["failed", "blocked"].includes(item.status) && !item.superseded,
  ).length;
  const normalizedKeyword = recordKeyword.trim().toLocaleLowerCase("zh-CN");
  const filteredRows = scopedRows.filter((item) => {
    const matchesAction =
      actionFilter === "all" || taskActionGroup(item) === actionFilter;
    const matchesStatus =
      filter === "all" ||
      (filter === "active" && (strategyScope ? item.status === "running" : ["pending", "running"].includes(item.status))) ||
      (filter === "waiting" && item.status === "pending") ||
      (filter === "succeeded" && item.status === "succeeded") ||
      (filter === "failed" &&
        ["failed", "blocked"].includes(item.status) &&
        !item.superseded);
    const matchesKeyword =
      !normalizedKeyword ||
      [
        item.account_name,
        item.account_id,
        item.manager_login_name,
        item.id,
        taskDisplayText(item),
        taskNodeText(item.current_node),
        taskProblemText(item),
      ].some((value) =>
        String(value || "")
          .toLocaleLowerCase("zh-CN")
          .includes(normalizedKeyword),
      );
    return matchesAction && matchesStatus && matchesKeyword;
  });
  const pageCount = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  const safePage = Math.min(recordPage, pageCount);
  const visibleRows = filteredRows.slice(
    (safePage - 1) * pageSize,
    safePage * pageSize,
  );
  const multiAccountJobs = strategyScope ? [] : buildJobs;

  const selectFilter = (value: ExecutionStatusFilter) => {
    setFilter(value);
    setRecordPage(1);
  };
  const selectActionFilter = (value: ExecutionActionFilter) => {
    setActionFilter(value);
    setRecordPage(1);
  };
  const resume = async (id: string) => {
    setBusyId(id);
    setError(null);
    try {
      await apiPost(`/projects/${project.id}/tasks/${id}/resume`, {});
      await load(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "续跑失败");
    } finally {
      setBusyId(null);
    }
  };
  const cancel = async (id: string) => {
    setBusyId(id);
    setError(null);
    try {
      await apiPost(`/projects/${project.id}/tasks/${id}/cancel`, {});
      setCancelTaskId(null);
      await load(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "取消任务失败");
    } finally {
      setBusyId(null);
    }
  };

  if (adBuildOnly) {
    const accountRuns = buildJobs.flatMap((job) =>
      job.batches.flatMap((batch) =>
        (batch.accounts || []).map((account) => ({
          job,
          batch,
          account,
        })),
      ),
    );
    const isWaiting = (status: string, scheduledAt: string) => {
      const scheduledTimestamp = Date.parse(scheduledAt);
      return (
        ["pending", "scheduled"].includes(status) &&
        Number.isFinite(scheduledTimestamp) &&
        scheduledTimestamp > Date.now()
      );
    };
    const buildActiveCount = accountRuns.filter(({ account }) =>
      account.status === "running",
    ).length + accountRuns.filter(({ account, batch }) =>
      account.status === "pending" && !isWaiting(account.status, batch.scheduled_at),
    ).length;
    const buildWaitingCount = accountRuns.filter(({ account, batch }) =>
      isWaiting(account.status, batch.scheduled_at),
    ).length;
    const buildSucceededCount = accountRuns.filter(
      ({ account }) => account.status === "succeeded",
    ).length;
    const buildFailedCount = accountRuns.filter(({ account }) =>
      ["failed", "blocked"].includes(account.status),
    ).length;
    const visibleAccountRuns = accountRuns.filter(({ job, batch, account }) => {
      const matchesStatus =
        filter === "all" ||
        (filter === "active" &&
          (account.status === "running" ||
            (account.status === "pending" &&
              !isWaiting(account.status, batch.scheduled_at)))) ||
        (filter === "waiting" &&
          isWaiting(account.status, batch.scheduled_at)) ||
        (filter === "succeeded" && account.status === "succeeded") ||
        (filter === "failed" && ["failed", "blocked"].includes(account.status));
      const haystack = [
        job.id,
        account.task_id,
        batch.number,
        account.account_name,
        account.account_id,
        account.account_subject,
        account.manager_login_name,
        account.current_node,
      ]
        .join(" ")
        .toLocaleLowerCase("zh-CN");
      return (
        matchesStatus &&
        (!normalizedKeyword || haystack.includes(normalizedKeyword))
      );
    });
    const buildPageCount = Math.max(
      1,
      Math.ceil(visibleAccountRuns.length / pageSize),
    );
    const buildSafePage = Math.min(recordPage, buildPageCount);
    const pagedAccountRuns = visibleAccountRuns.slice(
      (buildSafePage - 1) * pageSize,
      buildSafePage * pageSize,
    );
    return (
      <section className="execution-records-page ad-build-execution-page">
        {error && <PopupMessage intent="error">{error}</PopupMessage>}
        <section className="execution-summary-toolbar" aria-label="自动上线执行筛选">
          <div className="execution-data-tabs" role="group" aria-label="按执行状态筛选">
            {(
              [
                ["all", "全部", accountRuns.length],
                ["active", "进行中", buildActiveCount],
                ["waiting", "等待", buildWaitingCount],
                ["succeeded", "已完成", buildSucceededCount],
                ["failed", "异常", buildFailedCount],
              ] as Array<[ExecutionStatusFilter, string, number]>
            ).map(([value, label, count]) => (
              <Button
                key={value}
                appearance="subtle"
                aria-pressed={filter === value}
                className={filter === value ? "is-active" : ""}
                onClick={() => selectFilter(value)}
              >
                <span>{label}</span>
                <span className="execution-tab-count">{count}</span>
              </Button>
            ))}
          </div>
          <Button
            appearance="secondary"
            size="small"
            disabled={loading}
            onClick={() => void load()}
          >
            {loading ? "刷新中…" : "刷新状态"}
          </Button>
        </section>
        <section className="panel ad-build-record-panel">
          <div className="execution-toolbar">
            <SearchField
              className="execution-search"
              ariaLabel="搜索自动上线执行记录"
              value={recordKeyword}
              onChange={(value) => {
                setRecordKeyword(value);
                setRecordPage(1);
              }}
              placeholder="账户 / ID / 主体 / 管家 / 任务号"
            />
            {buildActiveCount > 0 && (
              <span>
                <i className="is-live" />
                每 5 秒自动更新
              </span>
            )}
          </div>
          <div className="ad-build-record-table-wrap">
            <table className="ad-build-record-table">
              <colgroup>
                <col className="col-task-id" />
                <col className="col-account-name" />
                <col className="col-account-id" />
                <col className="col-status" />
                <col className="col-date" />
                {adBuildExecutionNodeColumns.map(([key]) => (
                  <col className="col-node" key={key} />
                ))}
                <col className="col-result" />
                <col className="col-date" />
                <col className="col-actions" />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">任务ID</th>
                  <th scope="col">账户名称</th>
                  <th scope="col">账户ID</th>
                  <th scope="col">状态</th>
                  <th scope="col">预定时间</th>
                  {adBuildExecutionNodeColumns.map(([key, label]) => (
                    <th scope="col" key={key}>{label}</th>
                  ))}
                  <th className="execution-result-header" scope="col">执行结果</th>
                  <th scope="col">执行完毕时间</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {pagedAccountRuns.map(({ job, batch, account }, index) => {
                  const nodeMap = new Map(
                    (account.nodes || []).map((node) => [node.key, node]),
                  );
                  const isTerminal = [
                    "succeeded",
                    "failed",
                    "blocked",
                    "cancelled",
                  ].includes(account.status);
                  const completedAt = isTerminal
                    ? [...(account.nodes || [])]
                        .reverse()
                        .find((node) => node.completed_at)?.completed_at ||
                      account.updated_at
                    : null;
                  const failedNode = (account.nodes || []).find(
                    (node) => node.status === "failed",
                  );
                  const exceptionReason = failedNode?.message || account.last_error;
                  const executionResult = exceptionReason
                    ? readableTaskError(exceptionReason)
                    : account.status === "succeeded"
                      ? account.result_summary || "执行完成"
                      : account.status === "cancelled"
                        ? "任务已取消"
                        : isWaiting(account.status, batch.scheduled_at)
                          ? "等待预定时间"
                          : account.status === "running"
                            ? account.result_summary || taskNodeText(account.current_node)
                            : account.result_summary || "等待执行";
                  return (
                    <tr
                      className={account.last_error ? "has-error" : ""}
                      key={
                        account.operation_id ||
                        `${job.id}-${account.account_id || index}`
                      }
                    >
                      <td className="task-id-cell" title={account.task_id || job.id}>
                        {account.task_id ? account.task_id.slice(0, 8) : "—"}
                      </td>
                      <td title={account.account_name || ""}>
                        {account.account_name || "未知账户"}
                      </td>
                      <td className="numeric-cell">{account.account_id || "—"}</td>
                      <td className="status-cell">
                        <Badge appearance="tint" color={taskBadgeColor(account.status)}>
                          {adBuildExecutionStatusText(
                            account.status,
                            batch.scheduled_at,
                          )}
                        </Badge>
                      </td>
                      <td className="date-cell">{formatDateTime(batch.scheduled_at)}</td>
                      {adBuildExecutionNodeColumns.map(([key]) => {
                        const node = nodeMap.get(key);
                        const nodeStatus = node?.status || "pending";
                        return (
                          <td
                            className={`node-result-cell is-${nodeStatus}`}
                            key={key}
                            title={node?.label || "待执行"}
                          >
                            <span>
                              {nodeStatus === "succeeded"
                                ? "完成"
                                : nodeStatus === "failed"
                                  ? "异常"
                                  : nodeStatus === "running"
                                    ? "执行中"
                                    : "待执行"}
                            </span>
                          </td>
                        );
                      })}
                      <td className="execution-result-cell" title={executionResult}>
                        {executionResult}
                      </td>
                      <td className="date-cell">
                        {completedAt ? formatDateTime(completedAt) : "—"}
                      </td>
                      <td className="actions-cell">
                        {account.task_id && account.status === "pending" && (
                          <Button
                            size="small"
                            appearance="secondary"
                            disabled={busyId === account.task_id}
                            onClick={() => setCancelTaskId(account.task_id!)}
                          >
                            取消任务
                          </Button>
                        )}
                        {account.task_id &&
                          ["failed", "blocked"].includes(account.status) && (
                            <Button
                              size="small"
                              appearance="secondary"
                              disabled={busyId === account.task_id}
                              onClick={() => void resume(account.task_id!)}
                            >
                              {busyId === account.task_id ? "提交中…" : "安全续跑"}
                            </Button>
                          )}
                        {(!account.task_id ||
                          !["pending", "failed", "blocked"].includes(
                            account.status,
                          )) && <span className="execution-no-action">—</span>}
                      </td>
                    </tr>
                  );
                })}
                {!pagedAccountRuns.length && (
                  <tr>
                    <td className="ad-build-empty-cell" colSpan={17}>
                      <EmptyState
                        title="当前筛选下没有自动上线记录"
                        text="创建自动搭建任务后，每个账户的节点状态会显示在这里"
                      />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <ViewportStickyPagination
            page={buildSafePage}
            totalPages={buildPageCount}
            total={visibleAccountRuns.length}
            pageSize={pageSize}
            loading={loading}
            ariaLabel="自动上线执行记录分页"
            onPageChange={setRecordPage}
            onPageSizeChange={(size) => {
              setRecordPage(1);
              setPageSize(size);
            }}
          />
        </section>
        <Dialog
          open={Boolean(cancelTaskId)}
          onOpenChange={(_, data) => {
            if (!data.open && !busyId) setCancelTaskId(null);
          }}
        >
          <DialogSurface className="task-cancel-dialog">
            <DialogBody>
              <DialogTitle>取消任务</DialogTitle>
              <DialogContent>
                仅取消尚未开始的任务；已经执行的百度操作不会撤回
              </DialogContent>
              <DialogActions>
                <Button
                  appearance="secondary"
                  disabled={Boolean(busyId)}
                  onClick={() => setCancelTaskId(null)}
                >
                  返回
                </Button>
                <Button
                  appearance="primary"
                  disabled={!cancelTaskId || Boolean(busyId)}
                  onClick={() => cancelTaskId && void cancel(cancelTaskId)}
                >
                  {busyId ? "取消中…" : "确认取消"}
                </Button>
              </DialogActions>
            </DialogBody>
          </DialogSurface>
        </Dialog>
      </section>
    );
  }

  if (strategyScope) {
    const strategyStatusTabs: Array<[ExecutionStatusFilter, string, number]> = [
      ["all", "全部", scopedRows.length],
      ["active", "进行中", runningCount],
      ["waiting", "等待", waitingCount],
      ["succeeded", "已完成", succeededCount],
      ["failed", "异常", failedCount],
    ];
    return (
      <section className="strategy-execution-records" aria-label="自动策略执行记录">
        <div className="strategy-record-toolbar">
          <div className="strategy-record-status-tabs" role="group" aria-label="执行状态筛选">
            {strategyStatusTabs.map(([value, label, count]) => (
              <button
                key={value}
                type="button"
                className={filter === value ? "is-active" : ""}
                aria-pressed={filter === value}
                onClick={() => selectFilter(value)}
              >
                <span>{label}</span><em>{count}</em>
              </button>
            ))}
          </div>
          <div className="strategy-record-toolbar-actions">
            <SearchField
              className="strategy-record-search"
              ariaLabel="搜索自动策略执行记录"
              value={recordKeyword}
              onChange={(value) => { setRecordKeyword(value); setRecordPage(1); }}
              placeholder="账户 / ID / 任务号"
            />
            <Button
              className="toolbar-refresh-button"
              appearance="secondary"
              size="small"
              aria-label="刷新"
              title="刷新"
              disabled={loading}
              onClick={() => void load()}
            ><span aria-hidden="true">↻</span></Button>
          </div>
        </div>
        {error && <PopupMessage intent="error">{error}</PopupMessage>}
        <div className="strategy-record-table-wrap" aria-busy={loading}>
          <table className="strategy-record-table">
            <colgroup>
              <col className="col-created" />
              <col className="col-task-id" />
              <col className="col-action" />
              <col className="col-account-name" />
              <col className="col-account-id" />
              <col className="col-manager" />
              <col className="col-step" />
              <col className="col-progress" />
              <col className="col-retry" />
              <col className="col-status" />
              <col className="col-result" />
              <col className="col-finished" />
              <col className="col-actions" />
            </colgroup>
            <thead><tr>
              <th className="table-cell--center">执行时间</th>
              <th className="table-cell--center">任务ID</th>
              <th className="table-cell--start">执行动作</th>
              <th className="table-cell--start">账户名称</th>
              <th className="table-cell--center">账户ID</th>
              <th className="table-cell--start">账户管家</th>
              <th className="table-cell--start">当前步骤</th>
              <th className="table-cell--end">进度</th>
              <th className="table-cell--end">重试次数</th>
              <th className="table-cell--center">状态</th>
              <th className="table-cell--start">执行结果</th>
              <th className="table-cell--center">完成时间</th>
              <th className="table-cell--center">操作</th>
            </tr></thead>
            <tbody>
              {visibleRows.map((task) => {
                const terminal = ["succeeded", "failed", "blocked", "cancelled"].includes(task.status);
                const problemText = taskProblemText(task);
                return <tr key={task.id} className={task.last_error && !task.superseded ? "has-error" : ""}>
                  <td className="table-cell--center table-cell--date">{formatDateTime(task.created_at)}</td>
                  <td className="table-cell--center strategy-record-id" title={task.id}>{task.id.slice(0, 8)}</td>
                  <td className="table-cell--start strategy-record-single-line" title={taskDisplayText(task)}>{taskDisplayText(task)}</td>
                  <td className="table-cell--start strategy-record-single-line" title={task.account_name || "项目级任务"}>{task.account_name || "项目级任务"}</td>
                  <td className="table-cell--center strategy-record-id">{task.account_id || "—"}</td>
                  <td className="table-cell--start strategy-record-single-line" title={task.manager_login_name || "—"}>{task.manager_login_name || "—"}</td>
                  <td className="table-cell--start strategy-record-single-line" title={taskNodeText(task.current_node)}>{taskNodeText(task.current_node)}</td>
                  <td className="table-cell--end strategy-record-number">{Math.max(0, Math.min(100, task.progress || 0))}%</td>
                  <td className="table-cell--end strategy-record-number">{task.retry_count || 0}</td>
                  <td className="table-cell--center"><Badge appearance="tint" color={task.superseded ? "informative" : taskBadgeColor(task.status)}>{task.superseded ? "历史失败" : task.status === "pending" ? "等待" : statusText(task.status)}</Badge></td>
                  <td className={`table-cell--start strategy-record-result${task.last_error ? " has-error" : ""}`} title={problemText}>{problemText}</td>
                  <td className="table-cell--center table-cell--date">{terminal ? formatDateTime(task.updated_at || task.heartbeat_at || task.created_at) : "—"}</td>
                  <td className="table-cell--center"><div className="strategy-record-actions">
                    {task.status === "pending" ? <Button size="small" appearance="secondary" disabled={busyId === task.id} onClick={() => setCancelTaskId(task.id)}>取消任务</Button> : null}
                    {task.can_resume ? <Button size="small" appearance="secondary" disabled={busyId === task.id} onClick={() => void resume(task.id)}>{busyId === task.id ? "提交中…" : "安全续跑"}</Button> : null}
                    {task.status !== "pending" && !task.can_resume ? <span>—</span> : null}
                  </div></td>
                </tr>;
              })}
              {!visibleRows.length ? <tr><td className="strategy-record-empty" colSpan={13}>{recordKeyword.trim() ? "当前搜索没有匹配记录" : "当前状态下没有执行记录"}</td></tr> : null}
            </tbody>
          </table>
        </div>
        <ViewportStickyPagination
          page={safePage}
          totalPages={pageCount}
          total={filteredRows.length}
          pageSize={pageSize}
          loading={loading}
          ariaLabel="自动策略执行记录分页"
          onPageChange={setRecordPage}
          onPageSizeChange={(size) => { setRecordPage(1); setPageSize(size); }}
        />
        <Dialog open={Boolean(cancelTaskId)} onOpenChange={(_, data) => { if (!data.open && !busyId) setCancelTaskId(null); }}>
          <DialogSurface className="task-cancel-dialog"><DialogBody>
            <DialogTitle>取消任务</DialogTitle>
            <DialogContent>仅取消尚未开始的任务；已经执行的百度操作不会撤回</DialogContent>
            <DialogActions><Button appearance="secondary" disabled={Boolean(busyId)} onClick={() => setCancelTaskId(null)}>返回</Button><Button appearance="primary" disabled={!cancelTaskId || Boolean(busyId)} onClick={() => cancelTaskId && void cancel(cancelTaskId)}>{busyId ? "取消中…" : "确认取消"}</Button></DialogActions>
          </DialogBody></DialogSurface>
        </Dialog>
      </section>
    );
  }

  return (
    <section
      className={`execution-records-page ${strategyScope ? "strategy-scoped-records" : ""}`}
    >
      <section className="page-heading compact execution-record-heading">
        <div>
          <h1>{adBuildOnly ? "自动上线执行记录" : "执行记录"}</h1>
          <p>
            {adBuildOnly
              ? "按任务、批次和账户持续跟踪自动搭建的全部执行节点"
              : "直接查看每个账户做到哪一步、是否有问题，以及百度最终回读数量"}
            </p>
        </div>
        <div className="execution-heading-controls">
          <div className="execution-filters" role="group" aria-label="执行状态筛选">
            {(
              [
                ["all", "全部"],
                ["active", "进行中"],
                ["succeeded", "已完成"],
                ["failed", "失败 / 阻塞"],
              ] as Array<[ExecutionStatusFilter, string]>
            ).map(([value, label]) => (
              <Button
                key={value}
                size="small"
                appearance="subtle"
                className={filter === value ? "is-active" : ""}
                aria-pressed={filter === value}
                onClick={() => selectFilter(value)}
              >
                {label}
              </Button>
            ))}
          </div>
          <Button
            appearance="secondary"
            size="small"
            disabled={loading}
            onClick={() => void load()}
          >
            {loading ? "刷新中…" : "刷新状态"}
          </Button>
          <SearchField
            className="execution-search"
            ariaLabel="搜索执行记录"
            value={recordKeyword}
            onChange={(value) => {
              setRecordKeyword(value);
              setRecordPage(1);
            }}
            placeholder="动作 / 账户 / ID / 任务号"
          />
        </div>
      </section>
      {error && <PopupMessage intent="error">{error}</PopupMessage>}
      <section className="execution-summary" aria-label="执行记录汇总">
        <div>
          <span>最近任务</span>
          <strong>{scopedRows.length}</strong>
        </div>
        <div>
          <span>进行中</span>
          <strong>{activeCount}</strong>
        </div>
        <div>
          <span>已完成</span>
          <strong>{succeededCount}</strong>
        </div>
        <div className={failedCount ? "needs-attention" : ""}>
          <span>需要处理</span>
          <strong>{failedCount}</strong>
        </div>
      </section>
      {multiAccountJobs.length > 0 && (
        <section className="panel multi-build-records">
          <div className="panel-head">
            <div>
              <h2>多账户新建明细</h2>
              <p>按批次查看每个账户的当前步骤；失败和受阻账户优先显示</p>
            </div>
            <Badge appearance="tint">{multiAccountJobs.length} 个任务</Badge>
          </div>
          <div className="multi-build-list">
            {multiAccountJobs.map((job, jobIndex) => {
              const accounts = job.batches
                .flatMap((batch) =>
                  (batch.accounts || []).map((account) => ({
                    ...account,
                    batchNumber: batch.number,
                    scheduledAt: batch.scheduled_at,
                  })),
                )
                .sort((left, right) => {
                  const rank = (status: string) =>
                    ["failed", "blocked"].includes(status)
                      ? 0
                      : ["running", "pending"].includes(status)
                        ? 1
                        : 2;
                  return rank(left.status) - rank(right.status);
                });
              const failed = accounts.filter((account) =>
                ["failed", "blocked"].includes(account.status),
              ).length;
              const running = accounts.filter((account) =>
                ["running", "pending"].includes(account.status),
              ).length;
              const succeeded = accounts.filter(
                (account) => account.status === "succeeded",
              ).length;
              return (
                <details key={job.id} open={jobIndex === 0 || failed > 0}>
                  <summary>
                    <span className={`job-state ${job.status}`} />
                    <div>
                      <strong>
                        {job.execution_mode === "scheduled"
                          ? "定时新建"
                          : "一键新建"}{" "}
                        ·{" "}
                        {job.keyword_mode === "full" ? "全量模式" : "优选模式"}{" "}
                        · {job.account_count} 个账户
                      </strong>
                      <small>
                        {job.batch_count} 批 · 提交于{" "}
                        {formatDateTime(job.created_at)}
                      </small>
                    </div>
                    <div className="multi-build-counts">
                      <span>完成 {succeeded}</span>
                      <span>进行中 {running}</span>
                      <span className={failed ? "has-error" : ""}>
                        异常 {failed}
                      </span>
                    </div>
                    <Badge
                      appearance="tint"
                      color={
                        failed ? "danger" : running ? "informative" : "success"
                      }
                    >
                      {failed ? "需要处理" : running ? "执行中" : "已完成"}
                    </Badge>
                  </summary>
                  <div className="multi-build-table">
                    <div className="multi-build-table-head">
                      <span className="table-grid-cell table-cell--start">账户 / 账户 ID</span>
                      <span className="table-grid-cell table-cell--start">批次</span>
                      <span className="table-grid-cell table-cell--start">节点执行状态</span>
                      <span className="table-grid-cell table-cell--start">结果</span>
                      <span className="table-grid-cell table-cell--center">操作</span>
                    </div>
                    {accounts.map((account, index) => (
                      <div
                        className={`multi-build-account-row ${account.last_error ? "has-error" : ""}`}
                        key={
                          account.operation_id ||
                          `${job.id}-${account.account_id || index}`
                        }
                      >
                        <div className="table-grid-cell table-cell--start">
                          <strong>{account.account_name || "未知账户"}</strong>
                          <small>
                            {account.account_id
                              ? `账户 ID：${account.account_id}`
                              : "尚未取得账户 ID"}
                            {account.account_subject
                              ? ` · ${account.account_subject}`
                              : ""}
                          </small>
                        </div>
                        <div className="table-grid-cell table-cell--start">
                          <strong>第 {account.batchNumber} 批</strong>
                          <small>{formatDateTime(account.scheduledAt)}</small>
                        </div>
                        <div className="ad-node-track table-grid-cell table-cell--start">
                          {(account.nodes || []).map((node) => (
                            <span
                              key={node.key}
                              className={`ad-node ${node.status}`}
                              title={
                                node.message ||
                                (node.duration_seconds != null
                                  ? `耗时 ${node.duration_seconds} 秒`
                                  : node.label)
                              }
                            >
                              <i />
                              {node.label}
                            </span>
                          ))}
                        </div>
                        <div className="table-grid-cell table-cell--start">
                          <Badge
                            appearance="tint"
                            color={taskBadgeColor(account.status)}
                          >
                            {statusText(account.status)}
                          </Badge>
                          <span>
                            {account.last_error
                              ? readableTaskError(account.last_error)
                              : account.result_summary ||
                                taskNodeText(account.current_node)}
                          </span>
                          <small>
                            {account.progress || 0}% ·{" "}
                            {taskNodeText(account.current_node)}
                          </small>
                        </div>
                        <div className="table-grid-cell table-cell--center">
                          {account.task_id &&
                          ["failed", "blocked"].includes(account.status) ? (
                            <Button
                              size="small"
                              appearance="secondary"
                              disabled={busyId === account.task_id}
                              onClick={() => void resume(account.task_id!)}
                            >
                              {busyId === account.task_id
                                ? "提交中…"
                                : "安全续跑"}
                            </Button>
                          ) : (
                            <span className="execution-no-action">—</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
              );
            })}
          </div>
        </section>
      )}
      <section className="panel execution-record-panel">
        {!strategyScope && !adBuildOnly && (
          <div
            className="execution-action-tabs"
            role="tablist"
            aria-label="按执行动作筛选"
          >
            {executionActionTabs.map(([value, label]) => {
              const count =
                value === "all"
                  ? rows.length
                  : rows.filter((task) => taskActionGroup(task) === value)
                      .length;
              return (
                <Button
                  key={value}
                  role="tab"
                  aria-selected={actionFilter === value}
                  size="small"
                  appearance={actionFilter === value ? "primary" : "subtle"}
                  onClick={() => selectActionFilter(value)}
                  onKeyDown={(event) =>
                    moveHorizontalTab(
                      event,
                      executionActionTabs.map(([id]) => id),
                      actionFilter,
                      selectActionFilter,
                    )
                  }
                >
                  {label} {count}
                </Button>
              );
            })}
          </div>
        )}
        <div className="execution-update-row">
          <span>
            <i className={activeCount ? "is-live" : ""} />
            {activeCount ? "每 5 秒自动更新" : "当前没有进行中任务"} · 最近更新{" "}
            {lastUpdatedAt.toLocaleTimeString("zh-CN", { hour12: false })}
          </span>
        </div>
        {visibleRows.length ? (
          <div className="execution-table-scroll">
            <table className="execution-records-table">
              <thead>
                <tr>
                  <th className="table-cell--start">执行动作</th>
                  <th className="table-cell--start">账户 / 账户 ID</th>
                  <th className="table-cell--start">当前步骤</th>
                  <th className="table-cell--center">状态</th>
                  <th className="table-cell--start">执行结果</th>
                  <th className="table-cell--center table-cell--date">更新时间</th>
                  <th className="table-cell--center">操作</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((task) => {
                  const problemText = taskProblemText(task);
                  const recoveryHint = taskRecoveryHint(task);
                  return (
                    <tr
                      className={
                        task.last_error && !task.superseded ? "has-error" : ""
                      }
                      key={task.id}
                    >
                      <td className="table-cell--start">
                        <div className="execution-action-cell">
                          <strong>{taskDisplayText(task)}</strong>
                          <small title={task.id}>
                            任务 {task.id.slice(0, 8)}
                          </small>
                        </div>
                      </td>
                      <td className="table-cell--start">
                        <div className="execution-account">
                          <div>
                            <strong title={task.account_name || "项目级任务"}>
                              {task.account_name || "项目级任务"}
                            </strong>
                            <small>
                              {task.account_id
                                ? `账户 ID：${task.account_id}`
                                : "不涉及单一账户"}
                            </small>
                            {task.manager_login_name && (
                              <small title={task.manager_login_name}>
                                管家：{task.manager_login_name}
                              </small>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="table-cell--start">
                        <div className="execution-task-progress">
                          <div className="execution-task-label">
                            <strong title={taskNodeText(task.current_node)}>
                              {taskNodeText(task.current_node)}
                            </strong>
                          </div>
                          <div className="execution-progress">
                            <div>
                              <span
                                style={{
                                  width: `${Math.max(0, Math.min(100, task.progress || 0))}%`,
                                }}
                              />
                            </div>
                            <strong>{task.progress || 0}%</strong>
                          </div>
                        </div>
                      </td>
                      <td className="table-cell--center">
                        <Badge
                          appearance="tint"
                          color={
                            task.superseded
                              ? "informative"
                              : taskBadgeColor(task.status)
                          }
                        >
                          {task.superseded
                            ? "历史失败"
                            : statusText(task.status)}
                        </Badge>
                        {task.retry_count > 0 && (
                          <small className="execution-retry">
                            已重试 {task.retry_count} 次
                          </small>
                        )}
                      </td>
                      <td className="table-cell--start">
                        <div
                          className={`execution-result ${task.last_error ? "has-error" : ""}`}
                        >
                          <strong>{taskProblemTitle(task)}</strong>
                          <span
                            className="execution-result-summary"
                            title={problemText}
                          >
                            {problemText}
                          </span>
                          {recoveryHint && (
                            <small title={recoveryHint}>{recoveryHint}</small>
                          )}
                        </div>
                      </td>
                      <td className="table-cell--center table-cell--date">
                        <div className="execution-time">
                          <strong>
                            {formatDateTime(
                              task.heartbeat_at ||
                                task.updated_at ||
                                task.created_at,
                            )}
                          </strong>
                          <small>提交 {formatDateTime(task.created_at)}</small>
                        </div>
                      </td>
                      <td className="table-cell--center">
                        {task.can_resume ? (
                          <Button
                            size="small"
                            appearance="secondary"
                            disabled={busyId === task.id}
                            onClick={() => void resume(task.id)}
                          >
                            {busyId === task.id ? "提交中…" : "安全续跑"}
                          </Button>
                        ) : (
                          <span className="execution-no-action">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="当前筛选下没有执行记录"
            text={
              recordKeyword.trim()
                ? "没有匹配的动作、账户或任务，请尝试其他关键词"
                : "任务提交后会自动出现在这里，并持续更新进度与结果"
            }
          />
        )}
        <ViewportStickyPagination
          page={safePage}
          totalPages={pageCount}
          total={filteredRows.length}
          pageSize={pageSize}
          loading={loading}
          ariaLabel="执行记录分页"
          onPageChange={setRecordPage}
          onPageSizeChange={(size) => {
            setRecordPage(1);
            setPageSize(size);
          }}
        />
      </section>
    </section>
  );
}

function budgetSnapshotIssueText(
  snapshot: Pick<
    OperationsCenter["budget_reset"],
    | "budget_snapshot_status"
    | "budget_snapshot_fresh_count"
    | "budget_snapshot_missing_count"
  >,
  operation: "预算重置" | "预算追加",
) {
  if (snapshot.budget_snapshot_status === "partial") {
    return `预算快照已接入，本轮已获取 ${snapshot.budget_snapshot_fresh_count} 个冷启动期账户，仍有 ${snapshot.budget_snapshot_missing_count} 个未获得有效快照；${operation}保持保护状态`;
  }
  if (snapshot.budget_snapshot_status === "stale") {
    return `已有预算快照，但当前冷启动期账户的快照已超过 60 分钟；${operation}保持保护状态，等待下次同步`;
  }
  return `尚未获取到冷启动期账户的百度当前预算快照；${operation}保持保护状态，系统不会猜测账户预算`;
}

function ProjectOperationsPage({
  view,
  project,
  recordsOnly = false,
  embedded = false,
}: {
  view: OperationsView;
  project: Project;
  recordsOnly?: boolean;
  embedded?: boolean;
}) {
  const [data, setData] = useState<OperationsCenter | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [dateFrom, setDateFrom] = useState(() =>
    view === "budget-reset" ? dateInput(0) : dateInput(29),
  );
  const [dateTo, setDateTo] = useState(() => dateInput(0));
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const load = () => {
    setLoading(true);
    setError(null);
    const query = new URLSearchParams({
      date_from: dateFrom,
      date_to: dateTo,
      page: String(page),
      page_size: String(pageSize),
    });
    apiGet<OperationsCenter>(
      `/projects/${project.id}/operations-center?${query}`,
    )
      .then(setData)
      .catch((reason) =>
        setError(
          reason instanceof Error ? reason.message : "读取项目运行数据失败",
        ),
      )
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
  }, [project.id, view, dateFrom, dateTo, page, pageSize]);
  useEffect(() => {
    setDateFrom(view === "budget-reset" ? dateInput(0) : dateInput(29));
    setDateTo(dateInput(0));
    setPage(1);
  }, [project.id, view]);

  const pageMeta: Record<
    OperationsView,
    { title: string; description: string }
  > = {
    "loop-check": {
      title: "闭环运行状态",
      description: "持续检查百度数据、好多粉数据、归因、同步水位与规则评估链路",
    },
    "budget-reset": {
      title: "预算重置",
      description: data
        ? `每日 ${data.budget_reset.schedule} 检查成本判断为冷启动期的账户，将命中账户的日预算固定为 ${data.budget_reset.target_budget} 元`
        : "按已发布规则检查冷启动期账户，并将命中账户的日预算固定为填写金额",
    },
    "budget-append": {
      title: "预算追加",
      description: "满足成本与预算利用率条件后追加 50 元，并持续检查边际效果",
    },
    eliminations: {
      title: "淘汰记录",
      description: "集中查看已淘汰账户的消费、加粉成本和钱柜账户",
    },
  };
  const meta = pageMeta[view];
  const pagination = data
    ? view === "budget-reset"
      ? data.budget_reset.history
      : view === "budget-append"
        ? data.budget_append.history
        : data.eliminations
    : null;

  return (
    <section
      className={`operations-page ${recordsOnly ? "strategy-results-only" : ""} ${embedded ? "strategy-embedded-operations" : ""}`}
    >
      <section className="page-heading compact">
        <div>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <Button appearance="secondary" disabled={loading} onClick={load}>
          {loading ? "读取中…" : "刷新"}
        </Button>
      </section>
      {error && <PopupMessage intent="error">{error}</PopupMessage>}
      {view !== "loop-check" && (
        <div className="operations-filter-bar">
          <DateFilterGroup
            valueFrom={dateFrom}
            valueTo={dateTo}
            max={dateInput(0)}
            onChange={(range) => {
              setDateFrom(range.from);
              setDateTo(range.to);
              setPage(1);
            }}
            label={`${meta.title}日期`}
          />
          {data && (
            <span className="blacklist-summary">
              黑名单 <strong>{data.blacklist.account_count}</strong> 个账户
            </span>
          )}
        </div>
      )}
      {loading && !data ? (
        <Skeleton className="loading">
          <SkeletonItem size={28} />
          <SkeletonItem className="table-skeleton" />
        </Skeleton>
      ) : (
        data && (
          <>
            {view === "loop-check" && (
              <>
                <div className="operations-facts">
                  <span>
                    <small>检测频率</small>
                    <strong>{data.loop_check.interval_minutes} 分钟</strong>
                  </span>
                  <span>
                    <small>闭环状态</small>
                    <strong>
                      {data.loop_check.status === "healthy"
                        ? "运行正常"
                        : "等待数据"}
                    </strong>
                  </span>
                  <span>
                    <small>百度数据</small>
                    <strong>
                      {formatDateTime(data.loop_check.baidu_watermark)}
                    </strong>
                  </span>
                  <span>
                    <small>好多粉数据</small>
                    <strong>
                      {formatDateTime(data.loop_check.hduofen_watermark)}
                    </strong>
                  </span>
                  <span>
                    <small>预算快照</small>
                    <strong>
                      {formatDateTime(data.loop_check.budget_watermark)}
                    </strong>
                  </span>
                  <span>
                    <small>创意审核</small>
                    <strong>
                      {formatDateTime(data.loop_check.creative_watermark)}
                    </strong>
                  </span>
                </div>
                {data.loop_check.status !== "healthy" && (
                  <PopupMessage intent="warning">
                    百度日报、好多粉、预算快照或创意审核未同时满足 60
                    分钟新鲜度，自动规则保持保护状态，不产生写入动作
                  </PopupMessage>
                )}
                <section className="panel loop-check-panel">
                  <div className="panel-head">
                    <div>
                      <h2>60 分钟闭环</h2>
                      <p>只有前一节点完整，才会继续评估下一节点</p>
                    </div>
                    <Badge
                      appearance="tint"
                      color={
                        data.loop_check.status === "healthy"
                          ? "success"
                          : "warning"
                      }
                    >
                      {data.loop_check.status === "healthy"
                        ? "闭环正常"
                        : "保护中"}
                    </Badge>
                  </div>
                  <div className="loop-flow">
                    {[
                      ["01", "百度日报同步", "读取在用账户消费数据"],
                      ["02", "好多粉同步", "读取访客、复制与加粉"],
                      [
                        "03",
                        "账户预算与余额",
                        "回读在用账户的当前预算、余额与预算类型；余额低于预警值时生成充值提醒",
                      ],
                      ["04", "创意审核", "检查拒审并按创意中心规则重建"],
                      ["05", "账户归因", "账户与关键词必须唯一匹配"],
                      ["06", "规则评估", data.loop_check.next_action],
                    ].map(([index, title, text]) => (
                      <article key={index}>
                        <span>{index}</span>
                        <div>
                          <strong>{title}</strong>
                          <small>{text}</small>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              </>
            )}

            {view === "budget-reset" && (
              <>
                <div className="operations-facts">
                  <span>
                    <small>执行时间</small>
                    <strong>每日 {data.budget_reset.schedule}</strong>
                  </span>
                  <span>
                    <small>目标预算</small>
                    <strong>¥{data.budget_reset.target_budget}</strong>
                  </span>
                  <span>
                    <small>执行范围</small>
                    <strong>{data.budget_reset.scope}</strong>
                  </span>
                  <span>
                    <small>预算查询账户</small>
                    <strong>{data.budget_reset.test_account_count}</strong>
                  </span>
                </div>
                {!data.budget_reset.budget_snapshot_available && (
                  <PopupMessage intent="warning">
                    {budgetSnapshotIssueText(data.budget_reset, "预算重置")}
                  </PopupMessage>
                )}
                <section className="panel budget-rule-panel">
                  <div className="panel-head">
                    <div>
                      <h2>重置规则</h2>
                      <p>每天只执行一次，重复运行使用同一幂等键</p>
                    </div>
                    <Badge
                      appearance="tint"
                      color={
                        data.budget_reset.writes_enabled ? "success" : "warning"
                      }
                    >
                      {data.budget_reset.writes_enabled
                        ? "写入已启用"
                        : "安全只读"}
                    </Badge>
                  </div>
                  <div className="budget-rule-grid">
                    <article>
                      <small>账户范围</small>
                      <strong>成本判断 = 冷启动期</strong>
                      <p>其他成本判断账户一律跳过</p>
                    </article>
                    <article>
                      <small>变更条件</small>
                      <strong>
                        当前预算 ≠ ¥{data.budget_reset.target_budget}
                      </strong>
                      <p>预算没有变化的账户不提交百度</p>
                    </article>
                    <article>
                      <small>执行结果</small>
                      <strong>
                        固定为 ¥{data.budget_reset.target_budget}
                      </strong>
                      <p>写入后回读并记录差异与审计</p>
                    </article>
                  </div>
                  <footer>
                    <span>需重置账户</span>
                    <strong>{data.budget_reset.candidate_count ?? "—"}</strong>
                    <small>
                      {data.budget_reset.budget_snapshot_available
                        ? `已排除当前预算为 ${data.budget_reset.target_budget} 元的账户`
                        : "等待预算快照"}
                    </small>
                  </footer>
                </section>
                <BudgetHistoryPanel
                  title="预算重置记录"
                  history={data.budget_reset.history}
                  emptyText="所选日期没有预算重置记录"
                />
              </>
            )}

            {view === "budget-append" && (
              <>
                <div className="operations-facts">
                  <span>
                    <small>评估频率</small>
                    <strong>{data.budget_append.interval_minutes} 分钟</strong>
                  </span>
                  <span>
                    <small>加粉成本</small>
                    <strong>&lt; ¥{data.budget_append.add_cost_limit}</strong>
                  </span>
                  <span>
                    <small>预算利用率</small>
                    <strong>
                      &gt; {data.budget_append.utilization_threshold}%
                    </strong>
                  </span>
                  <span>
                    <small>轮次金额</small>
                    <strong>
                      第1轮 ¥{data.budget_append.round_amounts[0]?.amount ?? "—"}
                      {" / "}
                      10轮+ ¥{data.budget_append.round_amounts[9]?.amount ?? "—"}
                    </strong>
                  </span>
                </div>
                {!data.budget_append.budget_snapshot_available && (
                  <PopupMessage intent="warning">
                    {budgetSnapshotIssueText(data.budget_append, "预算追加")}
                  </PopupMessage>
                )}
                <section className="panel budget-rule-panel">
                  <div className="panel-head">
                    <div>
                      <h2>追加与边际判断</h2>
                      <p>每次追加后重新进入观察窗口，不连续无条件加预算</p>
                    </div>
                    <Badge
                      appearance="tint"
                      color={
                        data.budget_append.writes_enabled
                          ? "success"
                          : "warning"
                      }
                    >
                      {data.budget_append.writes_enabled
                        ? "写入已启用"
                        : "安全只读"}
                    </Badge>
                  </div>
                  <div className="marginal-flow">
                    <article>
                      <span>1</span>
                      <div>
                        <strong>成本达标</strong>
                        <small>加粉数大于 0，且加粉成本低于 100 元</small>
                      </div>
                    </article>
                    <article>
                      <span>2</span>
                      <div>
                        <strong>预算接近用完</strong>
                        <small>当前消费 ÷ 当前预算大于 80%</small>
                      </div>
                    </article>
                    <article>
                      <span>3</span>
                      <div>
                        <strong>按轮次追加金额</strong>
                        <small>每轮采用已发布的固定金额，执行后回读百度预算</small>
                      </div>
                    </article>
                    <article>
                      <span>4</span>
                      <div>
                        <strong>复查边际效果</strong>
                        <small>
                          下个 60
                          分钟窗口重新计算；成本恶化或利用率不足即停止追加
                        </small>
                      </div>
                    </article>
                  </div>
                  <footer>
                    <span>本次候选账户</span>
                    <strong>{data.budget_append.candidate_count ?? "—"}</strong>
                    <small>
                      {data.budget_append.budget_snapshot_available
                        ? "等待下次评估"
                        : "等待预算快照"}
                    </small>
                  </footer>
                </section>
                <BudgetHistoryPanel
                  title="预算追加记录"
                  history={data.budget_append.history}
                  emptyText="所选日期没有预算追加记录"
                />
              </>
            )}

            {view === "eliminations" && (
              <>
                <PopupMessage intent="info">
                  已淘汰账户已进入 API
                  黑名单；常规同步、预算规则和再次淘汰都会跳过；仅次日最终归档补取前一天数据一次
                </PopupMessage>
                <section className="panel elimination-panel">
                  <div className="panel-head">
                    <div>
                      <h2>淘汰明细</h2>
                      <p>金额与加粉成本由后台统一计算，分母为零时显示“—”</p>
                    </div>
                    <Badge appearance="tint">{data.eliminations.total}</Badge>
                  </div>
                  {data.eliminations.rows.length ? (
                    <div className="operations-table-scroll">
                      <table className="operations-table">
                        <thead>
                          <tr>
                            <th className="table-cell--center table-cell--date">时间</th>
                            <th className="table-cell--start">账户</th>
                            <th className="table-cell--start table-cell--id">账户ID</th>
                            <th className="table-cell--end table-cell--number">消费</th>
                            <th className="table-cell--end table-cell--number">加粉</th>
                            <th className="table-cell--end table-cell--number">加粉成本</th>
                            <th className="table-cell--start">钱柜账户</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.eliminations.rows.map((row) => (
                            <tr key={row.id}>
                              <td className="table-cell--center table-cell--date">{formatDateTime(row.eliminated_at)}</td>
                              <td className="table-cell--start">
                                <strong>{row.account_name}</strong>
                              </td>
                              <td className="table-cell--start table-cell--id">{row.account_id}</td>
                              <td className="table-cell--end table-cell--number">
                                ¥
                                {Number(row.spend).toLocaleString("zh-CN", {
                                  minimumFractionDigits: 2,
                                })}
                              </td>
                              <td className="table-cell--end table-cell--number">{formatNumber(row.adds)}</td>
                              <td className="table-cell--end table-cell--number">
                                {row.add_cost == null
                                  ? "—"
                                  : `¥${Number(row.add_cost).toFixed(2)}`}
                              </td>
                              <td className="table-cell--start">{row.recharge_account || "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <EmptyState
                      title="所选日期没有淘汰记录"
                      text="可调整日期范围查看历史淘汰账户"
                    />
                  )}
                </section>
              </>
            )}
            {view !== "loop-check" && pagination && (
              <ViewportStickyPagination
                page={pagination.page}
                totalPages={pagination.total_pages}
                total={pagination.total}
                pageSize={pagination.page_size}
                loading={loading}
                ariaLabel="项目运行记录分页"
                onPageChange={setPage}
                onPageSizeChange={(size) => {
                  setPageSize(size);
                  setPage(1);
                }}
              />
            )}
          </>
        )
      )}
    </section>
  );
}

function BudgetHistoryPanel({
  title,
  history,
  emptyText,
}: {
  title: string;
  history: OperationsCenter["budget_reset"]["history"];
  emptyText: string;
}) {
  return (
    <section className="panel operations-history-panel">
      <div className="panel-head">
        <div>
          <h2>{title}</h2>
          <p>只展示后台真实执行与回读结果</p>
        </div>
        <Badge appearance="tint">{history.total}</Badge>
      </div>
      {history.rows.length ? (
        <div className="operations-table-scroll">
          <table className="operations-table budget-history-table">
            <thead>
              <tr>
                <th className="table-cell--center table-cell--date">时间</th>
                <th className="table-cell--start">账户</th>
                <th className="table-cell--end table-cell--number">调整前</th>
                <th className="table-cell--end table-cell--number">调整后</th>
                <th className="table-cell--center">状态</th>
              </tr>
            </thead>
            <tbody>
              {history.rows.map((row) => (
                <tr key={row.id}>
                  <td className="table-cell--center table-cell--date">{formatDateTime(row.created_at)}</td>
                  <td className="table-cell--start">
                    <strong>{row.account_name}</strong>
                    <small>{row.account_id || "—"}</small>
                  </td>
                  <td className="table-cell--end table-cell--number">
                    {row.before_budget == null
                      ? "—"
                      : `¥${Number(row.before_budget).toFixed(2)}`}
                  </td>
                  <td className="table-cell--end table-cell--number">
                    {row.after_budget == null
                      ? "—"
                      : `¥${Number(row.after_budget).toFixed(2)}`}
                  </td>
                  <td className="table-cell--center">{row.status === "succeeded" ? "已完成" : row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title={emptyText} text="调整日期范围后可查看其他执行记录" />
      )}
    </section>
  );
}

const DEFAULT_SCHEDULE_TIMES = ["09:00", "15:00", "19:00"];
const SCHEDULE_HOUR_OPTIONS = Array.from(
  { length: 24 },
  (_, hour) => `${String(hour).padStart(2, "0")}:00`,
);
const DEFAULT_ONLINE_SCHEDULE: WeeklyScheduleWindow[] = Array.from(
  { length: 7 },
  (_, index) => ({ weekDay: index + 1, startHour: 0, endHour: 24 }),
);

function calculateDefaultScheduleDates(
  requiredBatchCount: number,
  scheduledTimes: string[],
  nowMs = Date.now(),
) {
  if (requiredBatchCount <= 0 || scheduledTimes.length === 0) return [];
  const cursor = new Date(nowMs + 8 * 60 * 60 * 1000);
  cursor.setUTCHours(0, 0, 0, 0);
  const dates: string[] = [];
  let availableSlots = 0;
  for (
    let dayOffset = 0;
    dayOffset < 366 && availableSlots < requiredBatchCount;
    dayOffset += 1
  ) {
    const dateValue = `${cursor.getUTCFullYear()}-${String(cursor.getUTCMonth() + 1).padStart(2, "0")}-${String(cursor.getUTCDate()).padStart(2, "0")}`;
    const daySlots = scheduledTimes.filter(
      (value) => Date.parse(`${dateValue}T${value}:00+08:00`) > nowMs,
    ).length;
    if (daySlots > 0) {
      dates.push(dateValue);
      availableSlots += daySlots;
    }
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return dates;
}

type SelectionColumnOption = [value: string, label: string];
type SelectionColumnFilterKey =
  | "accountName"
  | "accountId"
  | "accountManager"
  | "managerName"
  | "managerLogin"
  | "managerAccountCount";

function uniqueSelectionOptions(options: SelectionColumnOption[]) {
  return Array.from(new Map(options).entries()).sort((left, right) =>
    left[1].localeCompare(right[1], "zh-CN", { numeric: true }),
  );
}

function SelectionColumnFilter({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: SelectionColumnOption[];
  selected: string[];
  onChange: (values: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <span className="selection-column-heading">
      <span>{label}</span>
      <Popover
        open={open}
        onOpenChange={(_, data) => setOpen(data.open)}
        positioning={{ position: "below", align: "start", offset: 8 }}
        trapFocus
      >
        <PopoverTrigger disableButtonEnhancement>
          <button
            type="button"
            className={`account-column-filter-trigger${selected.length ? " is-active" : ""}`}
            aria-label={`筛选${label}`}
            aria-expanded={open}
          >
            <FilterRegular />
          </button>
        </PopoverTrigger>
        <PopoverSurface className="account-column-filter-popover">
          <SelectionColumnFilterMenu
            key={`${label}:${selected.join("\u0000")}`}
            label={label}
            options={options}
            selected={selected}
            onApply={(values) => {
              onChange(values);
              setOpen(false);
            }}
            onClose={() => setOpen(false)}
          />
        </PopoverSurface>
      </Popover>
    </span>
  );
}

function SelectionColumnFilterMenu({
  label,
  options,
  selected,
  onApply,
  onClose,
}: {
  label: string;
  options: SelectionColumnOption[];
  selected: string[];
  onApply: (values: string[]) => void;
  onClose: () => void;
}) {
  const allValues = options.map(([value]) => value);
  const [keyword, setKeyword] = useState("");
  const [draft, setDraft] = useState<string[]>(() =>
    selected.length ? selected : allValues,
  );
  const normalizedKeyword = keyword.trim().toLocaleLowerCase("zh-CN");
  const visibleOptions = options.filter(([, optionLabel]) =>
    normalizedKeyword
      ? optionLabel.toLocaleLowerCase("zh-CN").includes(normalizedKeyword)
      : true,
  );
  const allSelected = Boolean(
    allValues.length && allValues.every((value) => draft.includes(value)),
  );
  const partlySelected = Boolean(draft.length && !allSelected);
  const toggleValue = (value: string, checked: boolean) =>
    setDraft((current) =>
      checked
        ? Array.from(new Set([...current, value]))
        : current.filter((item) => item !== value),
    );
  return (
    <div
      className="account-column-filter-menu"
      role="group"
      aria-label={`${label}筛选`}
    >
      <div className="account-column-filter-menu-head">
        <strong>{label}筛选</strong>
        <button type="button" aria-label={`关闭${label}筛选`} onClick={onClose}>
          <DismissRegular />
        </button>
      </div>
      <div className="account-column-filter-search-row">
        <label className="account-column-filter-select-all" title="全选">
          <input
            type="checkbox"
            checked={allSelected}
            ref={(node) => {
              if (node) node.indeterminate = partlySelected;
            }}
            aria-label={`全选${label}`}
            onChange={(event) =>
              setDraft(event.target.checked ? allValues : [])
            }
          />
        </label>
        <SearchField
          className="account-column-filter-search"
          value={keyword}
          placeholder={`搜索${label}`}
          ariaLabel={`搜索${label}`}
          onChange={setKeyword}
          onSearch={() => undefined}
          onClear={() => setKeyword("")}
        />
      </div>
      <div className="account-column-filter-options">
        {visibleOptions.length ? (
          visibleOptions.map(([value, optionLabel]) => (
            <label key={value}>
              <input
                type="checkbox"
                checked={draft.includes(value)}
                onChange={(event) => toggleValue(value, event.target.checked)}
              />
              <span>{optionLabel}</span>
            </label>
          ))
        ) : (
          <span>没有匹配项</span>
        )}
      </div>
      <div className="account-column-filter-actions">
        <Button
          size="small"
          appearance="secondary"
          onClick={() => setDraft(allValues)}
        >
          重置
        </Button>
        <Button
          size="small"
          appearance="primary"
          disabled={!draft.length}
          onClick={() => onApply(allSelected ? [] : draft)}
        >
          应用
        </Button>
      </div>
    </div>
  );
}

function TextColumnFilter({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <span className="selection-column-heading">
      <span>{label}</span>
      <Popover
        open={open}
        onOpenChange={(_, data) => setOpen(data.open)}
        positioning={{ position: "below", align: "start", offset: 8 }}
        trapFocus
      >
        <PopoverTrigger disableButtonEnhancement>
          <button
            type="button"
            className={`account-column-filter-trigger${value ? " is-active" : ""}`}
            aria-label={`筛选${label}`}
            aria-expanded={open}
          >
            <FilterRegular />
          </button>
        </PopoverTrigger>
        <PopoverSurface className="account-column-filter-popover">
          <TextColumnFilterMenu
            key={`${label}:${value}`}
            label={label}
            value={value}
            onApply={(nextValue) => {
              onChange(nextValue);
              setOpen(false);
            }}
            onClose={() => setOpen(false)}
          />
        </PopoverSurface>
      </Popover>
    </span>
  );
}

function TextColumnFilterMenu({
  label,
  value,
  onApply,
  onClose,
}: {
  label: string;
  value: string;
  onApply: (value: string) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(value);
  return (
    <div
      className="account-column-filter-menu material-text-column-filter"
      role="group"
      aria-label={`${label}筛选`}
    >
      <div className="account-column-filter-menu-head">
        <strong>{label}筛选</strong>
        <button type="button" aria-label={`关闭${label}筛选`} onClick={onClose}>
          <DismissRegular />
        </button>
      </div>
      <SearchField
        className="account-column-filter-search"
        value={draft}
        placeholder={`搜索${label}`}
        ariaLabel={`搜索${label}`}
        onChange={setDraft}
        onSearch={() => onApply(draft.trim())}
        onClear={() => setDraft("")}
      />
      <div className="account-column-filter-actions">
        <Button size="small" appearance="secondary" onClick={() => setDraft("")}>
          重置
        </Button>
        <Button size="small" appearance="primary" onClick={() => onApply(draft.trim())}>
          应用
        </Button>
      </div>
    </div>
  );
}

function RegionSettingsDialog({
  open,
  catalog,
  selectedIds,
  saving,
  error,
  onCancel,
  onSave,
}: {
  open: boolean;
  catalog: BaiduRegionCatalog | null;
  selectedIds: number[];
  saving: boolean;
  error: string | null;
  onCancel: () => void;
  onSave: (ids: number[]) => void;
}) {
  const [draft, setDraft] = useState<Set<number>>(new Set(selectedIds));
  const [citySearch, setCitySearch] = useState("");
  const [activeProvinceId, setActiveProvinceId] = useState<number | null>(null);

  useEffect(() => {
    if (!open || !catalog) return;
    const initialDraft = selectedIds.includes(catalog.country.id)
      ? new Set(catalog.regions.map((province) => province.id))
      : new Set(selectedIds);
    const firstSelectedProvince = catalog.regions.find(
      (province) =>
        initialDraft.has(province.id) ||
        (province.children ?? []).some((city) => initialDraft.has(city.id)),
    );
    setDraft(initialDraft);
    setCitySearch("");
    setActiveProvinceId(
      firstSelectedProvince?.id ?? catalog.regions[0]?.id ?? null,
    );
  }, [open, catalog, selectedIds.join("|")]);

  const countryId = catalog?.country.id ?? 9999999;
  const activeProvince =
    catalog?.regions.find((province) => province.id === activeProvinceId) ??
    catalog?.regions[0] ??
    null;
  const normalizedCitySearch = citySearch.trim().toLocaleLowerCase("zh-CN");
  const visibleCities = (activeProvince?.children ?? []).filter(
    (city) =>
      !normalizedCitySearch ||
      city.name.toLocaleLowerCase("zh-CN").includes(normalizedCitySearch),
  );
  const toggleProvince = (province: BaiduRegionNode, checked: boolean) => {
    setDraft((current) => {
      const next = new Set(current);
      next.delete(countryId);
      (province.children ?? []).forEach((city) => next.delete(city.id));
      if (checked) next.add(province.id);
      else next.delete(province.id);
      return next;
    });
  };
  const toggleCity = (
    province: BaiduRegionNode,
    city: BaiduRegionNode,
    checked: boolean,
  ) => {
    setDraft((current) => {
      const next = new Set(current);
      next.delete(countryId);
      const provinceWasSelected = next.has(province.id);
      next.delete(province.id);
      if (provinceWasSelected) {
        (province.children ?? []).forEach((provinceCity) =>
          next.add(provinceCity.id),
        );
      }
      if (checked) next.add(city.id);
      else next.delete(city.id);
      const children = province.children ?? [];
      if (children.length && children.every((provinceCity) => next.has(provinceCity.id))) {
        children.forEach((provinceCity) => next.delete(provinceCity.id));
        next.add(province.id);
      }
      return next;
    });
  };

  return (
    <Dialog open={open} onOpenChange={(_, data) => !data.open && onCancel()}>
      <DialogSurface className="standard-dialog region-settings-dialog">
        <DialogBody>
          <DialogTitleWithSummary summary="按百度省市地域代码选择；保存后作为当前项目的自动搭建默认值">
            设置推广地域
          </DialogTitleWithSummary>
          <DialogContent>
            {error && <PopupMessage intent="error">{error}</PopupMessage>}
            {!catalog ? (
              <LoadingView />
            ) : (
              <div className="region-transfer">
                <section className="region-transfer-panel region-source-panel">
                  <header>
                    <strong>省级地域</strong>
                    <small>选择后在右侧设置</small>
                  </header>
                  <div className="region-province-list" role="listbox" aria-label="省级地域">
                    {catalog.regions.map((province) => {
                      const hasSelectedCity = (province.children ?? []).some((city) =>
                        draft.has(city.id),
                      );
                      return (
                      <div
                        role="option"
                        aria-selected={activeProvince?.id === province.id}
                        className={`region-province-row${activeProvince?.id === province.id ? " is-active" : ""}`}
                        key={province.id}
                      >
                        <Checkbox
                          aria-label={`选择${province.name}全部地域`}
                          checked={
                            draft.has(province.id)
                              ? true
                              : hasSelectedCity
                                ? "mixed"
                                : false
                          }
                          onChange={(_, data) =>
                            toggleProvince(province, data.checked === true)
                          }
                        />
                        <button
                          type="button"
                          onClick={() => {
                            setActiveProvinceId(province.id);
                            setCitySearch("");
                          }}
                        >
                          {province.name}
                        </button>
                      </div>
                    )})}
                  </div>
                </section>
                <section className="region-transfer-panel region-target-panel">
                  <header>
                    <strong>{activeProvince?.name ?? "市级地域"}</strong>
                    <span>已选 {draft.size}</span>
                    <button type="button" disabled={!draft.size} onClick={() => setDraft(new Set())}>
                      清空
                    </button>
                  </header>
                  <SearchField
                    value={citySearch}
                    onChange={setCitySearch}
                    onClear={() => setCitySearch("")}
                    placeholder={`搜索${activeProvince?.name ?? ""}市级地域`}
                    ariaLabel="搜索市级地域"
                  />
                  <div
                    className="region-city-list"
                    role="group"
                    aria-label={`${activeProvince?.name ?? "当前省份"}市级地域`}
                  >
                    {activeProvince && !normalizedCitySearch && (
                      <label className="region-city-row region-city-all">
                        <Checkbox
                          checked={
                            draft.has(activeProvince.id)
                              ? true
                              : (activeProvince.children ?? []).some((city) => draft.has(city.id))
                                ? "mixed"
                                : false
                          }
                          onChange={(_, data) =>
                            toggleProvince(activeProvince, data.checked === true)
                          }
                        />
                        <span>
                          <strong>
                            {(activeProvince.children ?? []).length ? "全省" : "全市"}
                          </strong>
                          <small>选择 {activeProvince.name} 全部地域</small>
                        </span>
                      </label>
                    )}
                    {activeProvince && visibleCities.map((city) => (
                      <label className="region-city-row" key={city.id}>
                        <Checkbox
                          checked={
                            draft.has(activeProvince.id) || draft.has(city.id)
                          }
                          onChange={(_, data) =>
                            toggleCity(activeProvince, city, data.checked === true)
                          }
                        />
                        <span><strong>{city.name}</strong></span>
                      </label>
                    ))}
                    {activeProvince && normalizedCitySearch && !visibleCities.length && (
                      <div className="region-transfer-empty">没有匹配的市级地域</div>
                    )}
                  </div>
                </section>
              </div>
            )}
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={onCancel}>取消</Button>
            <Button
              appearance="primary"
              disabled={saving || !catalog || draft.size === 0 || draft.size > 500}
              onClick={() => onSave(Array.from(draft))}
            >
              {saving ? "保存中…" : "保存为默认"}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function AdBuildPage({
  accounts,
  managers,
  project,
  writesEnabled,
  onOpenRecords,
}: {
  accounts: Account[];
  managers: AccountManager[];
  project: Project;
  writesEnabled: boolean;
  onOpenRecords: () => void;
}) {
  const defaultScheduleDates = calculateDefaultScheduleDates(
    1,
    DEFAULT_SCHEDULE_TIMES,
  );
  const defaultScheduleDate = defaultScheduleDates[0] || "";
  const [mode, setMode] = useState<AdBuildMode>("specified_managers");
  const [keywordMode, setKeywordMode] = useState<KeywordBuildMode>("preferred");
  const [selectedAccountIds, setSelectedAccountIds] = useState<Set<number>>(
    new Set(),
  );
  const [selectedManagerLogins, setSelectedManagerLogins] = useState<Set<string>>(
    new Set(),
  );
  const [selectionSearch, setSelectionSearch] = useState("");
  const [selectionColumnFilters, setSelectionColumnFilters] = useState<
    Record<SelectionColumnFilterKey, string[]>
  >({
    accountName: [],
    accountId: [],
    accountManager: [],
    managerName: [],
    managerLogin: [],
    managerAccountCount: [],
  });
  const [selectionPage, setSelectionPage] = useState(1);
  const [selectionPageSize, setSelectionPageSize] = useState(20);
  const [selectionSeed, setSelectionSeed] = useState<string>(() =>
    crypto.randomUUID(),
  );
  const [executionMode, setExecutionMode] = useState<"immediate" | "scheduled">(
    "immediate",
  );
  const [scheduleDates, setScheduleDates] = useState<string[]>([
    defaultScheduleDate,
  ]);
  const [scheduleDateDraft, setScheduleDateDraft] =
    useState(defaultScheduleDate);
  const [scheduleTimes, setScheduleTimes] = useState<string[]>(
    DEFAULT_SCHEDULE_TIMES,
  );
  const [scheduleUnlimited, setScheduleUnlimited] = useState(false);
  const [batchSize, setBatchSize] = useState(10);
  const [buildQuantity, setBuildQuantity] = useState("10");
  const [projectBid, setProjectBid] = useState("258.88");
  const [showPlanScheduleDialog, setShowPlanScheduleDialog] = useState(false);
  const [showRegionDialog, setShowRegionDialog] = useState(false);
  const [regionCatalog, setRegionCatalog] = useState<BaiduRegionCatalog | null>(null);
  const [regionPreference, setRegionPreference] =
    useState<AdBuildRegionPreference | null>(null);
  const [regionTarget, setRegionTarget] = useState<number[]>([]);
  const [regionSaving, setRegionSaving] = useState(false);
  const [regionError, setRegionError] = useState<string | null>(null);
  const [showExecutionScheduleDialog, setShowExecutionScheduleDialog] =
    useState(false);
  const [onlineSchedule, setOnlineSchedule] = useState<WeeklyScheduleWindow[]>(
    () => DEFAULT_ONLINE_SCHEDULE.map((window) => ({ ...window })),
  );
  const [preview, setPreview] = useState<AdBuildPreview | null>(null);
  const [access, setAccess] = useState<AdBuildAccess | null>(null);
  const [liveAccounts, setLiveAccounts] = useState<Account[]>(accounts);
  const [created, setCreated] = useState<AdBuildCreateResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const planScheduleSnapshot = useRef<{
    schedule: WeeklyScheduleWindow[];
  } | null>(null);
  const executionScheduleSnapshot = useRef<{
    mode: "immediate" | "scheduled";
    dates: string[];
    dateDraft: string;
    times: string[];
    unlimited: boolean;
    batchSize: number;
  } | null>(null);
  const modeOptions: Array<{ id: AdBuildMode; title: string; text: string }> = [
    {
      id: "specified_managers",
      title: "指定管家搭建",
      text: "选择账户管家，将其名下空账户加入队列",
    },
    {
      id: "specified_accounts",
      title: "指定账户搭建",
      text: "从当前可用的空账户中多选",
    },
    {
      id: "random",
      title: "随机搭建",
      text: "随机纳入全部配置完整的空账户",
    },
  ];
  const allowedBuildOperators =
    access?.operator_names ??
    (access?.restricted && access.operator_name ? [access.operator_name] : null);
  const eligibleAccounts =
    access === null
      ? []
      : allowedBuildOperators
        ? liveAccounts.filter(
            (item) => allowedBuildOperators.includes(item.operator_name || ""),
          )
        : liveAccounts;
  const adBuildAllowed = Boolean(access?.is_active && access?.can_build_ads);
  const emptyAccounts = eligibleAccounts
    .filter(
      (item) => item.is_active && item.account_status === "空账户",
    )
    .sort((left, right) => left.baidu_account_id - right.baidu_account_id);
  const managerDisplayNames = new Map(
    managers.map((manager) => [
      manager.login_name,
      manager.display_name || manager.login_name,
    ]),
  );
  const managerMap = new Map<string, Account[]>();
  emptyAccounts.forEach((item) => {
    const login = item.manager_login_name;
    managerMap.set(login, [...(managerMap.get(login) || []), item]);
  });
  const managerRows = Array.from(managerMap.entries())
    .map(([login, rows]) => ({
      login,
      displayName: managerDisplayNames.get(login) || login,
      rows,
    }))
    .sort((left, right) =>
      left.displayName.localeCompare(right.displayName, "zh-CN"),
    );
  const accountNameOptions = uniqueSelectionOptions(
    emptyAccounts.map((account) => [account.login_name, account.login_name]),
  );
  const accountIdOptions = uniqueSelectionOptions(
    emptyAccounts.map((account) => [
      String(account.baidu_account_id),
      String(account.baidu_account_id),
    ]),
  );
  const accountManagerOptions = uniqueSelectionOptions(
    emptyAccounts.map((account) => [
      account.manager_login_name,
      managerDisplayNames.get(account.manager_login_name) ||
        account.manager_login_name,
    ]),
  );
  const managerNameOptions = uniqueSelectionOptions(
    managerRows.map((manager) => [manager.login, manager.displayName]),
  );
  const managerLoginOptions = uniqueSelectionOptions(
    managerRows.map((manager) => [manager.login, manager.login]),
  );
  const managerAccountCountOptions = uniqueSelectionOptions(
    managerRows.map((manager) => [
      String(manager.rows.length),
      String(manager.rows.length),
    ]),
  );
  const selectionSearchTerms = selectionSearch
    .trim()
    .toLocaleLowerCase("zh-CN")
    .split(/\s+/)
    .filter(Boolean);
  const matchesSelectionSearch = (parts: Array<string | number | null | undefined>) => {
    if (!selectionSearchTerms.length) return true;
    const searchText = parts
      .filter((part): part is string | number => part !== null && part !== undefined)
      .join(" ")
      .toLocaleLowerCase("zh-CN");
    return selectionSearchTerms.every((term) => searchText.includes(term));
  };
  const matchesColumnFilter = (key: SelectionColumnFilterKey, value: string) =>
    !selectionColumnFilters[key].length ||
    selectionColumnFilters[key].includes(value);
  const updateSelectionColumnFilter = (
    key: SelectionColumnFilterKey,
    values: string[],
  ) => {
    setSelectionColumnFilters((current) => ({ ...current, [key]: values }));
    setSelectionPage(1);
  };
  const filteredEmptyAccounts = emptyAccounts.filter(
    (account) =>
      matchesSelectionSearch([
        account.login_name,
        account.baidu_account_id,
        account.manager_login_name,
        managerDisplayNames.get(account.manager_login_name),
      ]) &&
      matchesColumnFilter("accountName", account.login_name) &&
      matchesColumnFilter("accountId", String(account.baidu_account_id)) &&
      matchesColumnFilter("accountManager", account.manager_login_name),
  );
  const filteredManagerRows = managerRows.filter(
    (manager) =>
      matchesSelectionSearch([
        manager.displayName,
        manager.login,
        ...manager.rows.flatMap((account) => [
          account.login_name,
          account.baidu_account_id,
        ]),
      ]) &&
      matchesColumnFilter("managerName", manager.login) &&
      matchesColumnFilter("managerLogin", manager.login) &&
      matchesColumnFilter("managerAccountCount", String(manager.rows.length)),
  );
  const selectionTotal =
    mode === "specified_managers"
      ? filteredManagerRows.length
      : filteredEmptyAccounts.length;
  const selectionTotalPages = Math.max(
    1,
    Math.ceil(selectionTotal / selectionPageSize),
  );
  const safeSelectionPage = Math.min(selectionPage, selectionTotalPages);
  const selectionOffset = (safeSelectionPage - 1) * selectionPageSize;
  const pagedEmptyAccounts = filteredEmptyAccounts.slice(
    selectionOffset,
    selectionOffset + selectionPageSize,
  );
  const pagedManagerRows = filteredManagerRows.slice(
    selectionOffset,
    selectionOffset + selectionPageSize,
  );
  const configuredEmptyCount = eligibleAccounts.filter(
    (item) =>
      item.is_active &&
      item.account_status === "空账户" &&
      item.page_type &&
      item.promotion_page &&
      (item.account_type === "一跳预埋户" || item.landing_url_template),
  ).length;
  const requestedBuildQuantity = Math.max(
    0,
    Math.trunc(Number(buildQuantity) || 0),
  );
  const selectedManagerAccountCount = managerRows
    .filter((manager) => selectedManagerLogins.has(manager.login))
    .reduce((total, manager) => total + manager.rows.length, 0);
  const plannedAccountCount =
    preview?.selected_count ??
    (mode === "specified_accounts"
      ? selectedAccountIds.size
      : mode === "specified_managers"
        ? Math.min(
            requestedBuildQuantity * selectedManagerLogins.size,
            selectedManagerAccountCount,
          )
        : Math.min(requestedBuildQuantity, configuredEmptyCount));
  const requiredScheduleBatchCount =
    plannedAccountCount > 0 ? Math.ceil(plannedAccountCount / batchSize) : 0;

  useEffect(() => {
    if (
      executionMode !== "scheduled" ||
      scheduleUnlimited ||
      requiredScheduleBatchCount <= 0 ||
      scheduleTimes.length === 0
    )
      return;
    const dates = calculateDefaultScheduleDates(
      requiredScheduleBatchCount,
      scheduleTimes,
    );
    setScheduleDates(dates);
    setScheduleDateDraft(dates.at(-1) || "");
    setPreview(null);
    setCreated(null);
  }, [
    executionMode,
    scheduleUnlimited,
    requiredScheduleBatchCount,
    scheduleTimes.join("|"),
  ]);

  useEffect(() => {
    setLiveAccounts(accounts);
  }, [accounts]);
  useEffect(() => {
    setAccess(null);
    setPreview(null);
    setCreated(null);
    setError(null);
    apiGet<AdBuildAccess>(`/projects/${project.id}/ad-build-access/me`)
      .then((scope) => setAccess(scope))
      .catch((reason) => {
        setAccess(null);
        setError(
          reason instanceof Error ? reason.message : "读取投放账户权限失败",
        );
      });
  }, [project.id]);

  useEffect(() => {
    let active = true;
    setRegionCatalog(null);
    setRegionPreference(null);
    setRegionTarget([]);
    setRegionError(null);
    Promise.all([
      apiGet<BaiduRegionCatalog>("/baidu-regions"),
      apiGet<AdBuildRegionPreference>(
        `/projects/${project.id}/preferences/ad_build_region`,
      ),
    ])
      .then(([catalog, preference]) => {
        if (!active) return;
        setRegionCatalog(catalog);
        setRegionPreference(preference);
        setRegionTarget(preference.region_target);
      })
      .catch((reason) => {
        if (!active) return;
        setRegionError(
          reason instanceof Error ? reason.message : "读取推广地域默认设置失败",
        );
      });
    return () => {
      active = false;
    };
  }, [project.id]);

  useEffect(() => {
    let mounted = true;
    const refreshLiveState = () =>
      apiGet<Account[]>(`/projects/${project.id}/accounts`)
        .then((accountRows) => {
          if (!mounted) return;
          setLiveAccounts(accountRows);
        })
        .catch(() => undefined);
    void refreshLiveState();
    const timer = window.setInterval(refreshLiveState, 60000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [project.id]);

  const toggleAccount = (accountId: number, checked: boolean) => {
    setSelectedAccountIds((current) => {
      const next = new Set(current);
      if (checked) next.add(accountId);
      else next.delete(accountId);
      return next;
    });
    setPreview(null);
    setCreated(null);
  };

  const toggleManager = (managerLogin: string, checked: boolean) => {
    setSelectedManagerLogins((current) => {
      const next = new Set(current);
      if (checked) next.add(managerLogin);
      else next.delete(managerLogin);
      return next;
    });
    setPreview(null);
    setCreated(null);
  };

  const addScheduleDate = () => {
    if (!scheduleDateDraft) return;
    setScheduleDates((current) =>
      [...new Set([...current, scheduleDateDraft])].sort(),
    );
    setPreview(null);
    setCreated(null);
  };

  const toggleScheduleTime = (scheduledTime: string) => {
    setScheduleTimes((current) =>
      current.includes(scheduledTime)
        ? current.filter((item) => item !== scheduledTime)
        : [...current, scheduledTime].sort(),
    );
    setPreview(null);
    setCreated(null);
  };

  const selectBuildMode = (nextMode: AdBuildMode) => {
    setMode(nextMode);
    if (nextMode === "random") setSelectionSeed(crypto.randomUUID());
    setSelectionSearch("");
    setSelectionPage(1);
    setPreview(null);
    setCreated(null);
    setError(null);
  };

  const openPlanScheduleDialog = () => {
    planScheduleSnapshot.current = {
      schedule: onlineSchedule.map((window) => ({ ...window })),
    };
    setShowPlanScheduleDialog(true);
  };

  const cancelPlanScheduleDialog = () => {
    const snapshot = planScheduleSnapshot.current;
    if (snapshot) {
      setOnlineSchedule(snapshot.schedule.map((window) => ({ ...window })));
    }
    setShowPlanScheduleDialog(false);
  };

  const saveRegionDefault = async (ids: number[]) => {
    setRegionSaving(true);
    setRegionError(null);
    try {
      const saved = await apiPatch<AdBuildRegionPreference>(
        `/projects/${project.id}/preferences/ad_build_region`,
        { value: { region_target: ids, geo_location_status: 1 } },
      );
      setRegionPreference(saved);
      setRegionTarget(saved.region_target);
      setShowRegionDialog(false);
      setPreview(null);
      setCreated(null);
    } catch (reason) {
      setRegionError(
        reason instanceof Error ? reason.message : "保存推广地域默认设置失败",
      );
    } finally {
      setRegionSaving(false);
    }
  };

  const openExecutionScheduleDialog = () => {
    executionScheduleSnapshot.current = {
      mode: executionMode,
      dates: [...scheduleDates],
      dateDraft: scheduleDateDraft,
      times: [...scheduleTimes],
      unlimited: scheduleUnlimited,
      batchSize,
    };
    setExecutionMode("scheduled");
    setShowExecutionScheduleDialog(true);
    setPreview(null);
    setCreated(null);
  };

  const cancelExecutionScheduleDialog = () => {
    const snapshot = executionScheduleSnapshot.current;
    if (snapshot) {
      setExecutionMode(snapshot.mode);
      setScheduleDates(snapshot.dates);
      setScheduleDateDraft(snapshot.dateDraft);
      setScheduleTimes(snapshot.times);
      setScheduleUnlimited(snapshot.unlimited);
      setBatchSize(snapshot.batchSize);
    }
    setShowExecutionScheduleDialog(false);
  };

  const requestPayload = (execution: "immediate" | "scheduled") => {
    const selectors = emptyAccounts
      .filter((account) => selectedAccountIds.has(account.baidu_account_id))
      .map((account) => String(account.baidu_account_id));
    if (execution === "scheduled") {
      if (!scheduleDates.length)
        throw new Error(
          scheduleUnlimited ? "请选择开始日期" : "请至少添加一个执行日期",
        );
      if (!scheduleTimes.length) throw new Error("请至少添加一个执行时间");
    }
    const bid = Number(projectBid);
    if (!Number.isFinite(bid) || bid < 0.1 || bid > 99999.99)
      throw new Error("项目出价必须在 0.1 到 99999.99 之间");
    const quantity = Number(buildQuantity);
    if (
      mode !== "specified_accounts" &&
      (!Number.isInteger(quantity) || quantity < 1 || quantity > 10000)
    )
      throw new Error(
        mode === "specified_managers"
          ? "每个管家搭建数量必须是 1 到 10000 的整数"
          : "搭建数量必须是 1 到 10000 的整数",
      );
    if (!onlineSchedule.length)
      throw new Error("请至少选择一个计划启用时段");
    if (!regionPreference || !regionTarget.length)
      throw new Error("请先设置推广地域并保存为默认");
    const legacyWeekdays = Array.from(
      new Set(onlineSchedule.map((window) => window.weekDay)),
    ).sort();
    const legacyWindow = onlineSchedule[0] ?? DEFAULT_ONLINE_SCHEDULE[0];
    return {
      project_id: project.id,
      keyword_mode: keywordMode,
      selection_mode: mode,
      account_selectors: mode === "specified_accounts" ? selectors : [],
      manager_login_names:
        mode === "specified_managers"
          ? Array.from(selectedManagerLogins)
          : [],
      subject_names: [],
      quantity: mode === "specified_accounts" ? null : quantity,
      selection_seed: selectionSeed,
      execution_mode: execution,
      scheduled_at: null,
      scheduled_dates:
        execution === "scheduled"
          ? scheduleUnlimited
            ? scheduleDates.slice(0, 1)
            : scheduleDates
          : [],
      scheduled_times: execution === "scheduled" ? scheduleTimes : [],
      schedule_unlimited: execution === "scheduled" && scheduleUnlimited,
      batch_size: batchSize,
      project_bid: bid.toFixed(2),
      online_schedule_enabled: true,
      online_schedule: onlineSchedule,
      online_weekdays: legacyWeekdays.length ? legacyWeekdays : [1, 2, 3, 4, 5, 6, 7],
      online_start_hour: legacyWindow.startHour,
      online_end_hour: legacyWindow.endHour,
      region_target: regionTarget,
      geo_location_status: regionPreference.geo_location_status,
    };
  };

  const createQueue = async () => {
    setBusy(true);
    setError(null);
    setCreated(null);
    try {
      const payload = requestPayload(executionMode);
      const checked = await apiPost<AdBuildPreview>(
        "/ad-builds/preview",
        payload,
      );
      setPreview(checked);
      if (!checked.can_submit) throw new Error(checked.errors.join("；"));
      const result = await apiPost<AdBuildCreateResult>("/ad-builds", {
        ...payload,
        selected_account_ids: checked.selected_account_ids,
        selection_fingerprint: checked.selection_fingerprint,
        material_fingerprint: checked.material_fingerprint,
        negative_keyword_fingerprint: checked.negative_keyword_fingerprint,
        build_rule_version: checked.build_rule.version,
      });
      setCreated(result);
      onOpenRecords();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "新建任务队列失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <section className="build-mode-selector" aria-label="搭建对象">
        <div className="build-mode-group" role="group" aria-label="选择搭建对象">
          <span className="build-mode-label">搭建对象</span>
          <div className="build-mode-options">
            {modeOptions.map((option) => (
              <button
                type="button"
                key={option.id}
                aria-pressed={mode === option.id}
                className={mode === option.id ? "active" : ""}
                onClick={() => selectBuildMode(option.id)}
              >
                {option.title}
              </button>
            ))}
          </div>
        </div>
        <div className="build-mode-group" role="group" aria-label="选择关键词模式">
          <span className="build-mode-label">关键词模式</span>
          <div className="build-mode-options">
            <button
              type="button"
              className={keywordMode === "preferred" ? "active" : ""}
              aria-pressed={keywordMode === "preferred"}
              onClick={() => {
                setKeywordMode("preferred");
                setPreview(null);
                setCreated(null);
              }}
            >
              优选模式
            </button>
            <button
              type="button"
              className={keywordMode === "full" ? "active" : ""}
              aria-pressed={keywordMode === "full"}
              onClick={() => {
                setKeywordMode("full");
                setPreview(null);
                setCreated(null);
              }}
            >
              全量模式
            </button>
          </div>
        </div>
        <div className="build-mode-execution-tools" aria-label="搭建执行设置">
          {mode !== "specified_accounts" && (
            <label className="build-mode-inline-field build-mode-quantity">
              <span>
                {mode === "specified_managers"
                  ? "每个管家搭建数量"
                  : "搭建数量"}
              </span>
              <Input
                type="number"
                min={1}
                max={10000}
                step={1}
                value={buildQuantity}
                onChange={(_, data) => {
                  setBuildQuantity(data.value);
                  setPreview(null);
                  setCreated(null);
                }}
              />
            </label>
          )}
          <label className="build-mode-inline-field build-mode-bid">
            <span>出价</span>
            <Input
              type="number"
              min={0.1}
              max={99999.99}
              step={0.01}
              value={projectBid}
              onChange={(_, data) => {
                setProjectBid(data.value);
                setPreview(null);
                setCreated(null);
              }}
            />
          </label>
          <Button
            appearance="secondary"
            className="is-active"
            onClick={openPlanScheduleDialog}
          >
            设置计划时段
          </Button>
          <Button
            appearance="secondary"
            className={regionTarget.length ? "is-active" : undefined}
            title={regionTarget.length ? `当前默认已选 ${regionTarget.length} 个省市` : undefined}
            onClick={() => {
              setRegionError(null);
              setShowRegionDialog(true);
            }}
          >
            设置推广地域
          </Button>
          <div className="build-mode-execution-choice">
            <span>执行时间</span>
            <div className="build-mode-execution-segment" role="group" aria-label="选择执行时间">
              <button
                type="button"
                className={executionMode === "immediate" ? "active" : ""}
                aria-pressed={executionMode === "immediate"}
                onClick={() => {
                  setExecutionMode("immediate");
                  setPreview(null);
                  setCreated(null);
                }}
              >
                立即搭建
              </button>
              <button
                type="button"
                className={executionMode === "scheduled" ? "active" : ""}
                aria-pressed={executionMode === "scheduled"}
                onClick={openExecutionScheduleDialog}
              >
                定时搭建
              </button>
            </div>
          </div>
          <Button
            appearance="primary"
            className="build-mode-submit"
            disabled={busy || !adBuildAllowed}
            onClick={() => void createQueue()}
          >
            {busy
              ? "正在执行…"
              : access === null
                ? "读取权限中…"
                : "立即执行"}
          </Button>
        </div>
        <div className="build-mode-search">
          <SearchField
            ariaLabel={mode === "specified_managers" ? "搜索账户管家" : "搜索空账户"}
            value={selectionSearch}
            onChange={(value) => {
              setSelectionSearch(value);
              setSelectionPage(1);
            }}
            placeholder={
              mode === "specified_managers"
                ? "搜索管家名称、登录名或名下账户"
                : "搜索账户名称、账户 ID 或管家"
            }
          />
          {selectionSearch && (
            <Button
              size="small"
              appearance="subtle"
              onClick={() => {
                setSelectionSearch("");
                setSelectionPage(1);
              }}
            >
              清空
            </Button>
          )}
        </div>
      </section>

      {access && !adBuildAllowed && (
        <PopupMessage intent="error">
          当前身份的投放搭建权限已停用，请联系管理员在“系统设置”中启用
        </PopupMessage>
      )}
      {access?.restricted && (
        <PopupMessage intent="info">
          当前数据范围可选择运营归属为“{access.operator_name}
          ”的账户；后台会在预检和创建任务时再次强制校验
        </PopupMessage>
      )}

      <section className="ad-build-layout">
        <div className="ad-build-main">
          {mode === "specified_accounts" && (
            <div className="ad-selection-picker ad-selection-picker--inline" aria-label="空账户列表">
                <div className="selection-list-head selection-list-head--accounts">
                  <span />
                  <SelectionColumnFilter
                    label="账户名称"
                    options={accountNameOptions}
                    selected={selectionColumnFilters.accountName}
                    onChange={(values) =>
                      updateSelectionColumnFilter("accountName", values)
                    }
                  />
                  <SelectionColumnFilter
                    label="账户 ID"
                    options={accountIdOptions}
                    selected={selectionColumnFilters.accountId}
                    onChange={(values) =>
                      updateSelectionColumnFilter("accountId", values)
                    }
                  />
                  <SelectionColumnFilter
                    label="账户管家"
                    options={accountManagerOptions}
                    selected={selectionColumnFilters.accountManager}
                    onChange={(values) =>
                      updateSelectionColumnFilter("accountManager", values)
                    }
                  />
                  <span>选择</span>
                </div>
                <div className="selection-search-list" role="list" aria-label="空账户列表">
                  {pagedEmptyAccounts.length ? (
                    pagedEmptyAccounts.map((account) => (
                      <label
                        className={`selection-row selection-row--accounts ${selectedAccountIds.has(account.baidu_account_id) ? "is-selected" : ""}`}
                        key={account.baidu_account_id}
                      >
                        <Checkbox
                          checked={selectedAccountIds.has(account.baidu_account_id)}
                          onChange={(_, data) => toggleAccount(account.baidu_account_id, data.checked === true)}
                        />
                        <strong>{account.login_name}</strong>
                        <span className="selection-account-id">{account.baidu_account_id}</span>
                        <span className="selection-manager-name">{managerDisplayNames.get(account.manager_login_name) || account.manager_login_name}</span>
                        <em>{selectedAccountIds.has(account.baidu_account_id) ? "已选择" : "选择"}</em>
                      </label>
                    ))
                  ) : (
                    <div className="ad-inline-empty">
                      {emptyAccounts.length ? "没有匹配的空账户，请更换关键词" : "当前没有账户状态为“空账户”的可用账户"}
                    </div>
                  )}
                </div>
            </div>
          )}

          {mode === "specified_managers" && (
            <div className="ad-selection-picker ad-selection-picker--inline" aria-label="账户管家列表">
                <div className="selection-list-head selection-list-head--managers">
                  <span />
                  <SelectionColumnFilter
                    label="账户管家"
                    options={managerNameOptions}
                    selected={selectionColumnFilters.managerName}
                    onChange={(values) =>
                      updateSelectionColumnFilter("managerName", values)
                    }
                  />
                  <SelectionColumnFilter
                    label="管家登录名"
                    options={managerLoginOptions}
                    selected={selectionColumnFilters.managerLogin}
                    onChange={(values) =>
                      updateSelectionColumnFilter("managerLogin", values)
                    }
                  />
                  <SelectionColumnFilter
                    label="空账户数"
                    options={managerAccountCountOptions}
                    selected={selectionColumnFilters.managerAccountCount}
                    onChange={(values) =>
                      updateSelectionColumnFilter("managerAccountCount", values)
                    }
                  />
                  <span>选择</span>
                </div>
                <div className="selection-search-list" role="list" aria-label="账户管家列表">
                  {pagedManagerRows.length ? (
                    pagedManagerRows.map((manager) => (
                      <label
                        className={`selection-row selection-row--managers ${selectedManagerLogins.has(manager.login) ? "is-selected" : ""}`}
                        key={manager.login}
                      >
                        <Checkbox
                          checked={selectedManagerLogins.has(manager.login)}
                          onChange={(_, data) => toggleManager(manager.login, data.checked === true)}
                        />
                        <strong>{manager.displayName}</strong>
                        <span className="selection-manager-login">{manager.login}</span>
                        <span className="selection-account-count">{manager.rows.length}</span>
                        <em>{selectedManagerLogins.has(manager.login) ? "已选择" : "选择"}</em>
                      </label>
                    ))
                  ) : (
                    <div className="ad-inline-empty">
                      {managerRows.length ? "没有匹配的账户管家，请更换关键词" : "当前没有管辖空账户的账户管家"}
                    </div>
                  )}
                </div>
            </div>
          )}

          {mode !== "random" && (
            <ViewportStickyPagination
              page={safeSelectionPage}
              totalPages={selectionTotalPages}
              total={selectionTotal}
              pageSize={selectionPageSize}
              ariaLabel={
                mode === "specified_managers"
                  ? "账户管家分页"
                  : "空账户分页"
              }
              onPageChange={setSelectionPage}
              onPageSizeChange={(size) => {
                setSelectionPageSize(size);
                setSelectionPage(1);
              }}
            />
          )}

          <RegionSettingsDialog
            open={showRegionDialog}
            catalog={regionCatalog}
            selectedIds={regionTarget}
            saving={regionSaving}
            error={regionError}
            onCancel={() => {
              setShowRegionDialog(false);
              setRegionError(null);
            }}
            onSave={(ids) => void saveRegionDefault(ids)}
          />

          <Dialog
            open={showPlanScheduleDialog}
            onOpenChange={(_, data) => {
              if (!data.open) cancelPlanScheduleDialog();
            }}
          >
            <DialogSurface className="standard-dialog ad-build-settings-dialog">
              <DialogBody>
                <DialogTitleWithSummary summary="蓝色格为启用时段，提交时后台自动反算为百度计划暂停时段">
                  设置计划时段
                </DialogTitleWithSummary>
                <DialogContent>
                  <WeeklyScheduleSelector
                    value={onlineSchedule}
                    ariaLabel="自动上线计划启用时段"
                    selectedLabel="启用时段"
                    unselectedLabel="暂停时段"
                    onChange={(next) => {
                      setOnlineSchedule(next);
                      setPreview(null);
                      setCreated(null);
                    }}
                  />
                </DialogContent>
                <DialogActions>
                  <Button appearance="secondary" onClick={cancelPlanScheduleDialog}>
                    取消
                  </Button>
                  <Button
                    appearance="primary"
                    disabled={!onlineSchedule.length}
                    onClick={() => {
                      setShowPlanScheduleDialog(false);
                      setPreview(null);
                      setCreated(null);
                    }}
                  >
                    确定
                  </Button>
                </DialogActions>
              </DialogBody>
            </DialogSurface>
          </Dialog>

          <Dialog
            open={showExecutionScheduleDialog}
            onOpenChange={(_, data) => {
              if (!data.open) cancelExecutionScheduleDialog();
            }}
          >
            <DialogSurface className="standard-dialog ad-build-schedule-dialog">
              <DialogBody>
                <DialogTitleWithSummary summary="选择执行日期和整点时间">
                  定时搭建
                </DialogTitleWithSummary>
                <DialogContent>
              <div className="schedule-node-builder">
                <section className="schedule-node-section">
                  <div className="schedule-node-head">
                    <div>
                      <strong>执行日期</strong>
                      {scheduleUnlimited && (
                        <small>从开始日期起每天继续，直到队列全部执行完</small>
                      )}
                    </div>
                    <label className="schedule-unlimited">
                      <Checkbox
                        checked={scheduleUnlimited}
                        onChange={(_, data) => {
                          const checked = data.checked === true;
                          setScheduleUnlimited(checked);
                          if (checked)
                            setScheduleDates((current) => [
                              current[0] || scheduleDateDraft,
                            ]);
                          setPreview(null);
                          setCreated(null);
                        }}
                      />
                      <span>不限日期</span>
                    </label>
                  </div>
                  {scheduleUnlimited ? (
                    <Field label="开始日期" required>
                      <Input
                        className="date-input-control"
                        type="date"
                        min={dateInput(0)}
                        aria-label="开始日期"
                        value={scheduleDates[0] || scheduleDateDraft}
                        onChange={(_, data) => {
                          setScheduleDateDraft(data.value);
                          setScheduleDates(data.value ? [data.value] : []);
                          setPreview(null);
                        }}
                      />
                    </Field>
                  ) : (
                    <>
                      <div className="schedule-add-row">
                        <label
                          className="schedule-add-label"
                          htmlFor="ad-build-schedule-date-draft"
                        >
                          添加执行日期
                        </label>
                        <Input
                          id="ad-build-schedule-date-draft"
                          className="date-input-control"
                          type="date"
                          min={dateInput(0)}
                          aria-label="添加执行日期"
                          value={scheduleDateDraft}
                          onChange={(_, data) =>
                            setScheduleDateDraft(data.value)
                          }
                        />
                        <Button
                          appearance="secondary"
                          disabled={
                            !scheduleDateDraft ||
                            scheduleDates.includes(scheduleDateDraft)
                          }
                          onClick={addScheduleDate}
                        >
                          添加日期
                        </Button>
                      </div>
                      <div
                        className="schedule-chip-list"
                        aria-label="已选执行日期"
                      >
                        {scheduleDates.map((value) => (
                          <button
                            type="button"
                            key={value}
                            onClick={() => {
                              setScheduleDates((current) =>
                                current.filter((item) => item !== value),
                              );
                              setPreview(null);
                              setCreated(null);
                            }}
                          >
                            <span>{value.replace(/-/g, "/")}</span>
                            <b aria-hidden="true">×</b>
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </section>
                <section className="schedule-node-section">
                  <div className="schedule-node-head">
                    <div>
                      <strong>执行时间（整点）</strong>
                      <small>当天已过时段自动作废，后续日期继续使用</small>
                    </div>
                  </div>
                  <div
                    className="schedule-hour-grid"
                    aria-label="选择执行时间（整点）"
                  >
                    {SCHEDULE_HOUR_OPTIONS.map((value, hour) => (
                      <button
                        type="button"
                        key={value}
                        className={
                          scheduleTimes.includes(value) ? "selected" : ""
                        }
                        aria-pressed={scheduleTimes.includes(value)}
                        onClick={() => toggleScheduleTime(value)}
                      >
                        {hour}点
                      </button>
                    ))}
                  </div>
                  <small className="schedule-hour-summary">
                    已选：
                    {scheduleTimes.length ? scheduleTimes.join("、") : "无"}
                  </small>
                </section>
              </div>
                </DialogContent>
                <DialogActions>
                  <Button appearance="secondary" onClick={cancelExecutionScheduleDialog}>
                    取消
                  </Button>
                  <Button
                    appearance="primary"
                    disabled={!scheduleDates.length || !scheduleTimes.length}
                    onClick={() => {
                      setExecutionMode("scheduled");
                      setShowExecutionScheduleDialog(false);
                      setPreview(null);
                      setCreated(null);
                    }}
                  >
                    确定
                  </Button>
                </DialogActions>
              </DialogBody>
            </DialogSurface>
          </Dialog>

          {error && <PopupMessage intent="error">{error}</PopupMessage>}
          {created && (
            <PopupMessage
              intent={created.writes_enabled ? "success" : "warning"}
            >
              已创建 {created.account_count} 个账户、{created.batch_count}{" "}
              个批次的任务队列；
              {created.writes_enabled
                ? "任务已进入执行队列"
                : "百度写入关闭，任务会安全等待"}
            </PopupMessage>
          )}

          {preview && (
            <section className="panel ad-preview-panel">
              <div className="ad-preview-summary">
                <div>
                  <span className="eyebrow">账户预检结果</span>
                  <h2>
                    {preview.can_submit ? "队列可以创建" : "需要先修正配置"}
                  </h2>
                  <small>{preview.material_plan.description}</small>
                </div>
                <span>
                  <small>搭建模式</small>
                  <strong>
                    {preview.keyword_mode === "full" ? "全量" : "优选"}
                  </strong>
                </span>
                <span>
                  <small>选择账户</small>
                  <strong>{preview.selected_count}</strong>
                </span>
                <span>
                  <small>执行批次</small>
                  <strong>{preview.batch_count}</strong>
                </span>
                <span>
                  <small>每账户关键词</small>
                  <strong>
                    {preview.material_plan.per_account_keyword_count}
                  </strong>
                </span>
                <span>
                  <small>物料计划</small>
                  <strong>{preview.material_plan.campaign_count}</strong>
                </span>
                <span>
                  <small>每账户创意</small>
                  <strong>{preview.creative_count_per_account}</strong>
                </span>
              </div>
              {preview.errors.map((message) => (
                <PopupMessage key={message} intent="error">
                  {message}
                </PopupMessage>
              ))}
              {preview.warnings.map((message) => (
                <PopupMessage key={message} intent="warning">
                  {message}
                </PopupMessage>
              ))}
              {Object.keys(preview.subject_allocation).length > 0 && (
                <div className="subject-allocation">
                  <strong>主体分配</strong>
                  {Object.entries(preview.subject_allocation).map(
                    ([subject, count]) => (
                      <span key={subject}>
                        {subject}
                        <b>{count}</b>
                      </span>
                    ),
                  )}
                </div>
              )}
              <div className="ad-batch-list">
                {preview.batches.map((batch) => (
                  <article key={batch.number}>
                    <span>{String(batch.number).padStart(2, "0")}</span>
                    <div>
                      <strong>
                        第 {batch.number} 批 · {batch.account_count} 个账户
                      </strong>
                      <small>{formatDateTime(batch.scheduled_at)}</small>
                    </div>
                    <p>
                      {batch.account_names.slice(0, 4).join("、")}
                      {batch.account_names.length > 4
                        ? ` 等 ${batch.account_names.length} 个`
                        : ""}
                    </p>
                  </article>
                ))}
              </div>
              <div className="ad-account-preview">
                <div className="ad-account-preview-head">
                  <span>账户 / 主体</span>
                  <span>账户状态</span>
                  <span>页面配置</span>
                  <span>关键词 URL</span>
                  <span>预检</span>
                </div>
                {preview.accounts.slice(0, 30).map((item) => (
                  <div className="ad-account-preview-row" key={item.account_id}>
                    <span>
                      <strong>{item.login_name}</strong>
                      <small>
                        {item.account_subject || "未设置主体"} ·{" "}
                        {item.account_id}
                      </small>
                    </span>
                    <span>{item.account_status || "未设置"}</span>
                    <span>
                      <strong>{item.page_type || "缺失"}</strong>
                      <small>{item.promotion_page || "推广页面缺失"}</small>
                    </span>
                    <span>
                      {item.account_type === "二跳账户"
                        ? "逐词 UTF-8 转码"
                        : "不传关键词 URL"}
                    </span>
                    <span>
                      {item.issues.length ? (
                        <Badge appearance="tint" color="danger">
                          {item.issues.join("、")}
                        </Badge>
                      ) : (
                        <Badge appearance="tint" color="success">
                          通过
                        </Badge>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>

      </section>
    </>
  );
}

const creativeSegmentMeta: Array<{
  type: CreativeSegmentType;
  label: string;
  limit: string;
}> = [
  {
    type: "title",
    label: "创意标题",
    limit: "9–50 百度字节",
  },
  {
    type: "description1",
    label: "创意描述1",
    limit: "9–80 百度字节",
  },
  {
    type: "description2",
    label: "创意描述2",
    limit: "0–80 百度字节",
  },
];

function CreativeCenterPage({ project }: { project: Project }) {
  const [data, setData] = useState<CreativeCenter | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [addType, setAddType] = useState<CreativeSegmentType | null>(null);
  const [addText, setAddText] = useState("");
  const [busy, setBusy] = useState(false);
  const [segmentBusyId, setSegmentBusyId] = useState<string | null>(null);
  const [creativeView, setCreativeView] = useState<"segments" | "blacklist">(
    "segments",
  );
  const [blacklistPage, setBlacklistPage] = useState(1);
  const [blacklistPageSize, setBlacklistPageSize] = useState(20);

  const load = async (signal?: AbortSignal) => {
    const result = await apiGet<CreativeCenter>(
      `/projects/${project.id}/creative-center`,
      signal,
    );
    setData(result);
  };
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setFeedback(null);
    load(controller.signal)
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error ? reason.message : "读取创意中心失败",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [project.id]);

  const addContents = [
    ...new Set(
      addText
        .split(/\r?\n/)
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  ];
  const cleanCreativeInput = () => {
    setAddText(
      addText
        .split(/\r?\n/)
        .map((line) =>
          line.replace(/[<>_「」［］〈〉【】\[\]‘’“”；＋，－？＿\s]/g, ""),
        )
        .join("\n"),
    );
    setError(null);
  };
  const submitSegments = async () => {
    if (!addType || !addContents.length) return;
    setBusy(true);
    setError(null);
    setFeedback(null);
    try {
      const result = await apiPost<{
        created_count: number;
        already_count: number;
      }>(`/projects/${project.id}/creative-segments/bulk`, {
        segment_type: addType,
        contents: addContents,
      });
      setAddType(null);
      setAddText("");
      setFeedback(
        `创意已更新：新增 ${result.created_count} 条，跳过已有 ${result.already_count} 条`,
      );
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "添加创意失败");
    } finally {
      setBusy(false);
    }
  };
  const toggleSegment = async (
    type: CreativeSegmentType,
    id: string,
    isBlacklisted: boolean,
  ) => {
    setSegmentBusyId(id);
    setError(null);
    setFeedback(null);
    try {
      await apiPatch(
        `/projects/${project.id}/creative-segments/${id}/blacklist`,
        {
          blacklisted: !isBlacklisted,
          reason: isBlacklisted
            ? null
            : `人工停用${creativeSegmentMeta.find((item) => item.type === type)?.label || "创意"}`,
        },
      );
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新创意状态失败");
    } finally {
      setSegmentBusyId(null);
    }
  };
  const syncReviews = async () => {
    setBusy(true);
    setError(null);
    setFeedback(null);
    try {
      const result = await apiPost<{ task_id: string }>(
        `/projects/${project.id}/creative-reviews/sync`,
        {},
      );
      setFeedback(
        `审核状态同步任务已提交（${result.task_id.slice(0, 8)}），执行结果可在任务中心查看`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交审核同步失败");
    } finally {
      setBusy(false);
    }
  };

  const blacklistTotal = data?.tracked_combinations.length || 0;
  const blacklistPageCount = Math.max(
    1,
    Math.ceil(blacklistTotal / blacklistPageSize),
  );
  const blacklistSafePage = Math.min(blacklistPage, blacklistPageCount);
  const pagedTrackedCombinations =
    data?.tracked_combinations.slice(
      (blacklistSafePage - 1) * blacklistPageSize,
      blacklistSafePage * blacklistPageSize,
    ) || [];

  return (
    <>
      {error && <PopupMessage intent="error">{error}</PopupMessage>}
      {feedback && <PopupMessage intent="success">{feedback}</PopupMessage>}
      {loading || !data ? (
        <Skeleton className="loading">
          <SkeletonItem className="table-skeleton" />
        </Skeleton>
      ) : (
        <>
          <div className="creative-toolbar">
            <nav
              className="creative-view-tabs"
              role="tablist"
              aria-label="创意内容视图"
            >
              <button
                id="creative-segments-tab"
                type="button"
                role="tab"
                aria-selected={creativeView === "segments"}
                aria-controls="creative-segments-panel"
                className={creativeView === "segments" ? "active" : ""}
                onClick={() => setCreativeView("segments")}
                onKeyDown={(event) =>
                  moveHorizontalTab(
                    event,
                    ["segments", "blacklist"],
                    creativeView,
                    setCreativeView,
                  )
                }
              >
                创意标题描述
              </button>
              <button
                id="creative-blacklist-tab"
                type="button"
                role="tab"
                aria-selected={creativeView === "blacklist"}
                aria-controls="creative-blacklist-panel"
                className={creativeView === "blacklist" ? "active" : ""}
                onClick={() => setCreativeView("blacklist")}
                onKeyDown={(event) =>
                  moveHorizontalTab(
                    event,
                    ["segments", "blacklist"],
                    creativeView,
                    setCreativeView,
                  )
                }
              >
                创意黑名单
              </button>
            </nav>
            <div className="creative-facts" aria-label="创意统计">
              <span>
                <small>可用标题</small>
                <strong>{data.segment_counts.title}</strong>
              </span>
              <span>
                <small>可用描述1</small>
                <strong>{data.segment_counts.description1}</strong>
              </span>
              <span>
                <small>可用描述2</small>
                <strong>
                  {data.segment_counts.description2}
                  <i>＋空值</i>
                </strong>
              </span>
              <span>
                <small>可用组合</small>
                <strong>
                  {data.available_combination_count.toLocaleString("zh-CN")}
                </strong>
              </span>
              <span>
                <small>已登记组合</small>
                <strong>
                  {data.registered_combination_count.toLocaleString("zh-CN")}
                </strong>
              </span>
              <span>
                <small>组合黑名单</small>
                <strong>
                  {data.blacklisted_combination_count.toLocaleString("zh-CN")}
                </strong>
              </span>
            </div>
            <Button
              className="creative-sync-button"
              appearance="secondary"
              disabled={busy}
              onClick={() => void syncReviews()}
            >
              同步审核状态
            </Button>
          </div>
          <div
            id="creative-segments-panel"
            className="creative-segment-view"
            role="tabpanel"
            aria-labelledby="creative-segments-tab"
            hidden={creativeView !== "segments"}
          >
            <div className="creative-segment-grid">
              {creativeSegmentMeta.map((meta) => {
                const rows = data.segments[meta.type];
                return (
                  <section
                    className="panel creative-segment-card"
                    key={meta.type}
                  >
                  <div className="panel-head">
                    <div>
                      <h2>{meta.label}</h2>
                      <p>{meta.limit}</p>
                    </div>
                    <Button
                      size="small"
                      appearance="secondary"
                      onClick={() => {
                        setAddType(meta.type);
                        setAddText("");
                        setError(null);
                      }}
                    >
                      添加
                    </Button>
                  </div>
                  <div className="creative-segment-table-head" role="row">
                    <span role="columnheader">文案</span>
                    <span role="columnheader">二跳拒审</span>
                    <span role="columnheader">操作</span>
                  </div>
                  <div className="creative-segment-list">
                    {rows.length ? (
                      rows.map((row) => {
                        const permanentlyBlacklisted =
                          row.rejection_count >=
                          data.segment_rejection_threshold;
                        return (
                          <div
                            className={row.is_blacklisted ? "disabled" : ""}
                            key={row.id}
                          >
                            <span className="creative-segment-content">
                              <b>{row.content}</b>
                            </span>
                            <span className="creative-segment-rejection">
                              {row.rejection_count} /{" "}
                              {data.segment_rejection_threshold}
                            </span>
                            {permanentlyBlacklisted ? (
                              <Badge appearance="tint" color="danger">
                                原料黑名单
                              </Badge>
                            ) : (
                              <Button
                                size="small"
                                appearance="subtle"
                                disabled={segmentBusyId === row.id}
                                onClick={() =>
                                  void toggleSegment(
                                    meta.type,
                                    row.id,
                                    row.is_blacklisted,
                                  )
                                }
                              >
                                {segmentBusyId === row.id
                                  ? "处理中…"
                                  : row.is_blacklisted
                                    ? "恢复"
                                    : "停用"}
                              </Button>
                            )}
                          </div>
                        );
                      })
                    ) : (
                      <div className="creative-empty">尚未添加{meta.label}</div>
                    )}
                  </div>
                  </section>
                );
              })}
            </div>
          </div>
          <section
            id="creative-blacklist-panel"
            className="creative-blacklist-view"
            role="tabpanel"
            aria-labelledby="creative-blacklist-tab"
            hidden={creativeView !== "blacklist"}
          >
            <section className="panel creative-policy-panel">
              <div>
                <span className="eyebrow">审核治理</span>
                <h2>一跳允许重投，二跳累计拒绝才封禁组合</h2>
                <p>
                  系统每15分钟查询已登记的百度创意状态；所有黑名单组合在后续随机选择中都会被排除
                </p>
              </div>
              <ol>
                <li>
                  <b>一跳账户</b>
                  <span>
                    <code>mainReason = "3"</code>{" "}
                    表示审核不通过：删除该百度创意，再随机补齐到50条；原组合和三段原料都不累计黑名单次数，允许以后再次提交
                  </span>
                </li>
                <li>
                  <b>二跳组合</b>
                  <span>
                    <code>mainReason = "3"</code>{" "}
                    同样表示审核不通过：单次拒绝仍可再次提交；同一组合累计{" "}
                    {data.second_hop_rejection_threshold}{" "}
                    次拒绝后进入组合黑名单，之后禁止再次提交
                  </span>
                </li>
                <li>
                  <b>二跳原料</b>
                  <span>
                    每次拒审给组合中的标题、描述1和非空描述2各累计1次；任一原料累计{" "}
                    {data.segment_rejection_threshold}{" "}
                    次后永久进入原料黑名单，所有包含它的组合都停止使用
                  </span>
                </li>
              </ol>
            </section>
            <section className="panel creative-review-panel">
              {data.tracked_combinations.length ? (
                <div className="creative-combination-scroll">
                  <table className="creative-combination-table">
                    <thead>
                      <tr>
                        <th className="table-cell--start">创意标题</th>
                        <th className="table-cell--start">创意描述1</th>
                        <th className="table-cell--start">创意描述2</th>
                        <th className="table-cell--end table-cell--number">二跳拒绝次数</th>
                        <th className="table-cell--center">状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pagedTrackedCombinations.map((row) => (
                        <tr key={row.id}>
                          <td className="table-cell--start">{row.title}</td>
                          <td className="table-cell--start">{row.description1}</td>
                          <td className="table-cell--start">{row.description2 || "空值"}</td>
                          <td className="table-cell--end table-cell--number">{row.rejection_count}</td>
                          <td className="table-cell--center">
                            <Badge
                              appearance="tint"
                              color={row.is_blacklisted ? "danger" : "warning"}
                            >
                              {row.is_blacklisted
                                ? "黑名单 · 禁止再提交"
                                : "继续观察"}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="creative-empty wide">
                  当前没有被二跳账户多次拒绝的组合
                </div>
              )}
              {blacklistTotal > 0 ? (
                <ViewportStickyPagination
                  page={blacklistSafePage}
                  totalPages={blacklistPageCount}
                  total={blacklistTotal}
                  pageSize={blacklistPageSize}
                  ariaLabel="创意黑名单分页"
                  onPageChange={setBlacklistPage}
                  onPageSizeChange={(size) => {
                    setBlacklistPage(1);
                    setBlacklistPageSize(size);
                  }}
                />
              ) : null}
            </section>
          </section>
        </>
      )}
      <Dialog
        open={addType !== null}
        onOpenChange={(_, dialogData) => {
          if (!busy && !dialogData.open) setAddType(null);
        }}
      >
        <DialogSurface className="creative-add-dialog">
          <DialogBody>
            <DialogTitleWithSummary summary="按项目和创意分段去重，并校验百度创意规则">
              添加{creativeSegmentMeta.find((item) => item.type === addType)?.label}
            </DialogTitleWithSummary>
            <DialogContent>
              <p className="dialog-description">
                每行输入一条；系统按项目和分段类型去重，并按百度创意字节长度及特殊符号规则校验
              </p>
              <Field
                className="creative-add-field"
                required
                hint={`已识别 ${addContents.length} 条唯一内容`}
              >
                <Textarea
                  aria-label="创意内容"
                  rows={12}
                  resize="vertical"
                  value={addText}
                  onChange={(_, value) => setAddText(value.value)}
                  placeholder="每行输入一条创意"
                />
              </Field>
              <div className="creative-clean-row">
                <span>百度基础创意不允许空格、【】、，；？等字符</span>
                <Button
                  size="small"
                  appearance="secondary"
                  disabled={busy || !addText.trim()}
                  onClick={cleanCreativeInput}
                >
                  按百度规则清理特殊符号
                </Button>
              </div>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                disabled={busy}
                onClick={() => setAddType(null)}
              >
                取消
              </Button>
              <Button
                appearance="primary"
                disabled={busy || !addContents.length}
                onClick={() => void submitSegments()}
              >
                {busy ? "保存中…" : `添加 ${addContents.length} 条`}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function MaterialsPage({ project }: { project: Project }) {
  const [materialKeywords, setMaterialKeywords] = useState<
    MaterialKeywordRow[]
  >([]);
  const [materialKeywordTotal, setMaterialKeywordTotal] = useState(0);
  const [materialPage, setMaterialPage] = useState(1);
  const [materialPageSize, setMaterialPageSize] = useState(20);
  const [materialSearchInput, setMaterialSearchInput] = useState("");
  const [materialSearch, setMaterialSearch] = useState("");
  const [materialLoading, setMaterialLoading] = useState(true);
  const [materialLoadError, setMaterialLoadError] = useState<string | null>(
    null,
  );
  const materialTotalPages = Math.max(
    1,
    Math.ceil(materialKeywordTotal / materialPageSize),
  );
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRules, setShowRules] = useState(false);
  const [rules, setRules] = useState<KeywordTierRules | null>(null);
  const [ruleBusy, setRuleBusy] = useState(false);
  const [ruleFeedback, setRuleFeedback] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState<KeywordTierDryRun | null>(null);
  const [showRiskConfirm, setShowRiskConfirm] = useState(false);
  const [materialCampaignFilters, setMaterialCampaignFilters] = useState<string[]>([]);
  const [materialKeywordFilter, setMaterialKeywordFilter] = useState("");
  const [materialStatusFilters, setMaterialStatusFilters] = useState<string[]>([]);
  const [materialFacets, setMaterialFacets] = useState<MaterialKeywordFacets>({
    campaign_names: [],
  });
  const [selectedYear, setSelectedYear] = useState(() =>
    new Date().getFullYear(),
  );
  const [availableYears, setAvailableYears] = useState<number[]>([]);
  const [blacklistBusyId, setBlacklistBusyId] = useState<string | null>(null);
  const [showManualBlacklist, setShowManualBlacklist] = useState(false);
  const [manualBlacklistText, setManualBlacklistText] = useState("");
  const [manualBlacklistBusy, setManualBlacklistBusy] = useState(false);
  const [manualBlacklistFeedback, setManualBlacklistFeedback] = useState<
    string | null
  >(null);
  const [negativeKeywordDialog, setNegativeKeywordDialog] = useState<
    "add" | "list" | null
  >(null);
  const [negativeKeywordLibrary, setNegativeKeywordLibrary] =
    useState<NegativeKeywordLibrary | null>(null);
  const [negativeKeywordText, setNegativeKeywordText] = useState("");
  const [negativeKeywordBusy, setNegativeKeywordBusy] = useState(false);
  const [negativeKeywordFeedback, setNegativeKeywordFeedback] = useState<
    string | null
  >(null);
  const [negativeKeywordSearch, setNegativeKeywordSearch] = useState("");
  const [negativeKeywordPage, setNegativeKeywordPage] = useState(1);
  const [negativeKeywordPageSize, setNegativeKeywordPageSize] = useState(20);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const ruleSnapshotRef = useRef<KeywordTierRules | null>(null);
  const ruleDialogContentRef = useRef<HTMLDivElement>(null);
  const applyMaterialKeywordPage = (result: MaterialKeywordPage) => {
    setMaterialKeywords(result.items);
    setMaterialKeywordTotal(result.total);
    setAvailableYears(result.available_years);
    if (
      result.available_years.length > 0 &&
      !result.available_years.includes(selectedYear)
    ) {
      setSelectedYear(Math.max(...result.available_years));
    }
    setMaterialPage((current) =>
      Math.min(
        current,
        Math.max(1, Math.ceil(result.total / materialPageSize)),
      ),
    );
  };
  const materialKeywordQuery = () => {
    const query = new URLSearchParams({
      page: String(materialPage),
      page_size: String(materialPageSize),
      year: String(selectedYear),
    });
    if (materialSearch) query.set("search", materialSearch);
    if (materialKeywordFilter) query.set("keyword_search", materialKeywordFilter);
    materialCampaignFilters.forEach((value) => query.append("campaign_names", value));
    materialStatusFilters.forEach((value) => query.append("blacklist_statuses", value));
    return `/projects/${project.id}/material-keywords?${query.toString()}`;
  };
  const loadMaterialFacets = (signal?: AbortSignal) =>
    apiGet<MaterialKeywordFacets>(
      `/projects/${project.id}/material-keywords/facets`,
      signal,
    ).then((result) =>
      setMaterialFacets({ campaign_names: result.campaign_names || [] }),
    );
  const loadMaterialKeywords = () =>
    apiGet<MaterialKeywordPage>(materialKeywordQuery()).then(
      applyMaterialKeywordPage,
    );
  const refreshMaterialKeywords = async () => {
    setMaterialLoading(true);
    setMaterialLoadError(null);
    try {
      await loadMaterialKeywords();
    } catch (reason) {
      setMaterialLoadError(
        reason instanceof Error ? reason.message : "读取物料明细失败",
      );
    } finally {
      setMaterialLoading(false);
    }
  };
  const loadNegativeKeywords = (signal?: AbortSignal) =>
    apiGet<NegativeKeywordLibrary>(
      `/projects/${project.id}/negative-keywords`,
      signal,
    ).then(setNegativeKeywordLibrary);
  useEffect(() => {
    const controller = new AbortController();
    setMaterialCampaignFilters([]);
    setMaterialKeywordFilter("");
    setMaterialStatusFilters([]);
    setMaterialFacets({ campaign_names: [] });
    setPreview(null);
    setSaved(false);
    setError(null);
    setManualBlacklistFeedback(null);
    setRules(null);
    setDryRun(null);
    setRuleFeedback(null);
    apiGet<KeywordTierRules>(
      `/projects/${project.id}/preferences/keyword_tiers`,
      controller.signal,
    )
      .then(setRules)
      .catch((reason) => {
        if (!controller.signal.aborted)
          setRuleFeedback(
            reason instanceof Error ? reason.message : "读取分级规则失败",
          );
      });
    loadMaterialFacets(controller.signal).catch(() => undefined);
    return () => controller.abort();
  }, [project.id]);
  useEffect(() => {
    const controller = new AbortController();
    setMaterialLoading(true);
    setMaterialLoadError(null);
    setMaterialKeywords([]);
    apiGet<MaterialKeywordPage>(materialKeywordQuery(), controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) applyMaterialKeywordPage(result);
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setMaterialLoadError(
            reason instanceof Error ? reason.message : "读取物料明细失败",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setMaterialLoading(false);
      });
    return () => controller.abort();
  }, [
    project.id,
    materialCampaignFilters,
    materialKeywordFilter,
    materialStatusFilters,
    selectedYear,
    materialPage,
    materialPageSize,
    materialSearch,
  ]);
  useEffect(() => {
    const controller = new AbortController();
    setNegativeKeywordLibrary(null);
    setNegativeKeywordFeedback(null);
    setNegativeKeywordText("");
    loadNegativeKeywords(controller.signal).catch((reason) => {
      if (!controller.signal.aborted)
        setError(reason instanceof Error ? reason.message : "读取项目否词失败");
    });
    return () => controller.abort();
  }, [project.id]);
  useEffect(() => {
    if (!showRules) return;
    const frame = window.requestAnimationFrame(() => {
      const content = ruleDialogContentRef.current;
      if (!content) return;
      content.scrollTop = 0;
      content.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [showRules]);
  const upload = async (file: File) => {
    setBusy(true);
    setError(null);
    setPreview(null);
    setSaved(false);
    try {
      const result = await apiUpload<{
        saved: boolean;
        preview: ImportPreview;
      }>(`/projects/${project.id}/materials/import`, file);
      setPreview(result.preview);
      setSaved(result.saved);
      if (!result.saved)
        setError(
          "文件校验未通过，未保存为正式物料版本；请根据校验问题修正后重试",
        );
      else {
        try {
          await Promise.all([loadMaterialKeywords(), loadMaterialFacets()]);
        } catch (reason) {
          setError(
            reason instanceof Error
              ? `导入已保存，但刷新物料明细失败：${reason.message}`
              : "导入已保存，但刷新物料明细失败",
          );
        }
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入失败");
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };
  const updateRule = (
    key: keyof KeywordTierRules,
    value: string | boolean | number,
  ) => {
    if (rules) setRules({ ...rules, [key]: value });
    setDryRun(null);
    setRuleFeedback(null);
    setShowRiskConfirm(false);
  };
  const openRuleDialog = () => {
    if (!rules) return;
    ruleSnapshotRef.current = { ...rules };
    setDryRun(null);
    setRuleFeedback(null);
    setShowRiskConfirm(false);
    setShowRules(true);
  };
  const closeRuleDialog = () => {
    if (ruleBusy) return;
    if (ruleSnapshotRef.current) setRules({ ...ruleSnapshotRef.current });
    setDryRun(null);
    setRuleFeedback(null);
    setShowRiskConfirm(false);
    setShowRules(false);
  };
  const saveRules = async () => {
    if (!rules) return;
    setRuleBusy(true);
    setRuleFeedback(null);
    try {
      const savedRules = await apiPatch<KeywordTierRules>(
        `/projects/${project.id}/preferences/keyword_tiers`,
        { value: rules },
      );
      setRules(savedRules);
      ruleSnapshotRef.current = { ...savedRules };
      setRuleFeedback("分级规则已保存");
    } catch (reason) {
      setRuleFeedback(
        reason instanceof Error ? reason.message : "保存分级规则失败",
      );
    } finally {
      setRuleBusy(false);
    }
  };
  const previewRules = async () => {
    setRuleBusy(true);
    setRuleFeedback(null);
    setDryRun(null);
    setShowRiskConfirm(false);
    try {
      const result = await apiPost<KeywordTierDryRun>(
        `/projects/${project.id}/keyword-tier-rules/dry-run`,
        { rules },
      );
      setDryRun(result);
      setRuleFeedback(
        "试算完成，不修改物料；确认后才会自动调整计划级别和风险词黑名单",
      );
    } catch (reason) {
      setRuleFeedback(
        reason instanceof Error ? reason.message : "分级试算失败",
      );
    } finally {
      setRuleBusy(false);
    }
  };
  const applyTierAdjustments = async () => {
    if (!rules || !dryRun) return;
    setRuleBusy(true);
    setRuleFeedback(null);
    try {
      const savedRules = await apiPatch<KeywordTierRules>(
        `/projects/${project.id}/preferences/keyword_tiers`,
        { value: rules },
      );
      const result = await apiPost<{
        changed_count: number;
        upgrade_count: number;
        downgrade_count: number;
        blacklisted_count: number;
        cost_high_count: number;
        empty_spend_count: number;
      }>(`/projects/${project.id}/keyword-tier-rules/apply`, {
        rules: savedRules,
      });
      setRules(savedRules);
      ruleSnapshotRef.current = { ...savedRules };
      setDryRun(null);
      setShowRiskConfirm(false);
      setRuleFeedback(
        `自动调整完成：共变动 ${result.changed_count} 个，升级 ${result.upgrade_count} 个，降级 ${result.downgrade_count} 个；其中 ${result.blacklisted_count} 个风险词进入黑名单`,
      );
      await loadMaterialKeywords();
    } catch (reason) {
      setShowRiskConfirm(false);
      setRuleFeedback(
        reason instanceof Error ? reason.message : "自动调整关键词计划级别失败",
      );
    } finally {
      setRuleBusy(false);
    }
  };
  const toggleBlacklist = async (item: MaterialKeywordRow) => {
    setBlacklistBusyId(item.id);
    setError(null);
    try {
      await apiPatch(
        `/projects/${project.id}/material-keywords/${item.id}/blacklist`,
        {
          blacklisted: !item.is_blacklisted,
          reason: item.is_blacklisted ? null : "人工加入黑名单",
        },
      );
      await loadMaterialKeywords();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "更新关键词黑名单失败",
      );
    } finally {
      setBlacklistBusyId(null);
    }
  };
  const manualBlacklistKeywords = [
    ...new Set(
      manualBlacklistText
        .split(/[\r\n,，]+/)
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  ];
  const addManualBlacklist = async () => {
    if (!manualBlacklistKeywords.length) return;
    setManualBlacklistBusy(true);
    setError(null);
    setManualBlacklistFeedback(null);
    try {
      const result = await apiPost<{
        input_count: number;
        created_count: number;
        updated_count: number;
        already_count: number;
      }>(`/projects/${project.id}/material-keywords/blacklist/bulk`, {
        keywords: manualBlacklistKeywords,
        reason: null,
      });
      setShowManualBlacklist(false);
      setManualBlacklistText("");
      setManualBlacklistFeedback(
        `黑名单已更新：新增 ${result.created_count} 个，拉黑已有物料 ${result.updated_count} 个，跳过已在黑名单 ${result.already_count} 个`,
      );
      const showingOnlyBlacklisted =
        materialStatusFilters.length === 1 &&
        materialStatusFilters[0] === "blacklisted";
      if (showingOnlyBlacklisted) await loadMaterialKeywords();
      else {
        setMaterialPage(1);
        setMaterialStatusFilters(["blacklisted"]);
      }
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "添加关键词黑名单失败",
      );
    } finally {
      setManualBlacklistBusy(false);
    }
  };
  const parsedNegativeKeywords = [
    ...new Set(
      negativeKeywordText
        .split(/[\r\n,，]+/)
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  ];
  const addNegativeKeywords = async (matchType: NegativeKeywordMatchType) => {
    if (!parsedNegativeKeywords.length) return;
    setNegativeKeywordBusy(true);
    setError(null);
    setNegativeKeywordFeedback(null);
    try {
      const result = await apiPost<{
        created_count: number;
        duplicate_count: number;
      }>(`/projects/${project.id}/negative-keywords/bulk`, {
        match_type: matchType,
        keywords: parsedNegativeKeywords,
      });
      setNegativeKeywordText("");
      setNegativeKeywordFeedback(
        `已新增 ${result.created_count} 个，跳过重复 ${result.duplicate_count} 个；后续新建计划会读取当前数据库否词`,
      );
      await loadNegativeKeywords();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "添加否词失败");
    } finally {
      setNegativeKeywordBusy(false);
    }
  };
  const deleteNegativeKeyword = async (id: string) => {
    setNegativeKeywordBusy(true);
    setError(null);
    setNegativeKeywordFeedback(null);
    try {
      await apiDelete(`/projects/${project.id}/negative-keywords/${id}`);
      setNegativeKeywordFeedback("否词已删除；之后创建的计划不再使用该词");
      await loadNegativeKeywords();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除否词失败");
    } finally {
      setNegativeKeywordBusy(false);
    }
  };
  const filteredNegativeKeywords = (negativeKeywordLibrary?.items || []).filter(
    (item) =>
      !negativeKeywordSearch.trim() ||
      item.keyword_text
        .toLocaleLowerCase()
        .includes(negativeKeywordSearch.trim().toLocaleLowerCase()),
  );
  const negativeKeywordPageCount = Math.max(
    1,
    Math.ceil(filteredNegativeKeywords.length / negativeKeywordPageSize),
  );
  const negativeKeywordSafePage = Math.min(
    negativeKeywordPage,
    negativeKeywordPageCount,
  );
  const pagedNegativeKeywords = filteredNegativeKeywords.slice(
    (negativeKeywordSafePage - 1) * negativeKeywordPageSize,
    negativeKeywordSafePage * negativeKeywordPageSize,
  );
  const displayMetric = (value: string | number | null) =>
    value === null ? "—" : String(value);
  return (
    <>
      <Dialog
        open={showManualBlacklist}
        onOpenChange={(_, data) => {
          if (!manualBlacklistBusy) setShowManualBlacklist(data.open);
        }}
      >
        <DialogSurface className="keyword-blacklist-dialog">
          <DialogBody>
            <DialogTitleWithSummary summary="黑名单关键词不会进入后续物料投放">添加关键词黑名单</DialogTitleWithSummary>
            <DialogContent>
              <div className="dialog-form">
                <Textarea
                  aria-label="关键词"
                  resize="vertical"
                  rows={10}
                  value={manualBlacklistText}
                  onChange={(_, data) => setManualBlacklistText(data.value)}
                  placeholder={"减肥药\n快速瘦身\n关键词三"}
                />
              </div>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                disabled={manualBlacklistBusy}
                onClick={() => setShowManualBlacklist(false)}
              >
                取消
              </Button>
              <Button
                appearance="primary"
                disabled={
                  manualBlacklistBusy || manualBlacklistKeywords.length === 0
                }
                onClick={() => void addManualBlacklist()}
              >
                {manualBlacklistBusy
                  ? "添加中…"
                  : `添加 ${manualBlacklistKeywords.length} 个关键词`}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog
        open={negativeKeywordDialog === "add"}
        onOpenChange={(_, data) => {
          if (!negativeKeywordBusy && !data.open) setNegativeKeywordDialog(null);
        }}
      >
        <DialogSurface className="keyword-blacklist-dialog negative-keyword-add-dialog">
          <DialogBody>
            <DialogTitle>添加否词</DialogTitle>
            <DialogContent>
              <div className="dialog-form">
                <Textarea
                  aria-label="否词"
                  resize="vertical"
                  rows={10}
                  value={negativeKeywordText}
                  onChange={(_, data) => setNegativeKeywordText(data.value)}
                  placeholder={"每行输入一个否词\n也支持逗号分隔"}
                />
              </div>
              {negativeKeywordFeedback && (
                <PopupMessage intent="success">
                  {negativeKeywordFeedback}
                </PopupMessage>
              )}
            </DialogContent>
            <DialogActions>
              <Button
                appearance="secondary"
                disabled={negativeKeywordBusy}
                onClick={() => setNegativeKeywordDialog(null)}
              >
                取消
              </Button>
              <Button
                appearance="secondary"
                disabled={
                  negativeKeywordBusy || parsedNegativeKeywords.length === 0
                }
                onClick={() => void addNegativeKeywords("phrase")}
              >
                添加短语否词
              </Button>
              <Button
                appearance="primary"
                disabled={
                  negativeKeywordBusy || parsedNegativeKeywords.length === 0
                }
                onClick={() => void addNegativeKeywords("exact")}
              >
                添加精确否词
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      <Dialog
        open={negativeKeywordDialog === "list"}
        onOpenChange={(_, data) => {
          if (!negativeKeywordBusy && !data.open) setNegativeKeywordDialog(null);
        }}
      >
        <DialogSurface className="custom-id-dialog negative-keyword-list-dialog">
          <DialogBody>
            <DialogTitleWithSummary summary="查询当前项目已保存的否词">
              否词名单
            </DialogTitleWithSummary>
            <DialogContent>
              <section className="custom-id-list-panel negative-keyword-list-panel">
                <div className="custom-id-list-head">
                  <div className="custom-id-list-summary">
                    <span>已有否词</span>
                    <span>
                      {negativeKeywordLibrary
                        ? `共 ${filteredNegativeKeywords.length} 条`
                        : "正在读取"}
                    </span>
                  </div>
                  <SearchField
                    ariaLabel="搜索否词"
                    value={negativeKeywordSearch}
                    onChange={(value) => {
                      setNegativeKeywordSearch(value);
                      setNegativeKeywordPage(1);
                    }}
                    placeholder="搜索否词"
                  />
                </div>
                {negativeKeywordFeedback && (
                  <PopupMessage intent="success">
                    {negativeKeywordFeedback}
                  </PopupMessage>
                )}
                {pagedNegativeKeywords.length ? (
                  <div className="custom-id-table-scroll">
                    <table className="custom-id-table negative-keyword-table">
                      <thead>
                        <tr>
                          <th className="table-cell--start">否词</th>
                          <th className="table-cell--center">类型</th>
                          <th className="table-cell--center">来源</th>
                          <th className="table-cell--center table-cell--date">添加时间</th>
                          <th className="table-cell--center">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pagedNegativeKeywords.map((item) => (
                          <tr key={item.id}>
                            <td className="table-cell--start">{item.keyword_text}</td>
                            <td className="table-cell--center">
                              {item.match_type === "phrase" ? "短语否词" : "精确否词"}
                            </td>
                            <td className="table-cell--center">
                              {item.source === "reference_template" ? "模板复制" : "人工添加"}
                            </td>
                            <td className="table-cell--center table-cell--date">
                              {formatDateTime(item.created_at)}
                            </td>
                            <td className="table-cell--center">
                              <Button
                                appearance="subtle"
                                size="small"
                                disabled={negativeKeywordBusy}
                                onClick={() => void deleteNegativeKeyword(item.id)}
                              >
                                删除
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="custom-id-empty">
                    {negativeKeywordSearch.trim()
                      ? "没有匹配的否词"
                      : "当前项目还没有否词"}
                  </div>
                )}
                {filteredNegativeKeywords.length ? (
                  <ViewportStickyPagination
                    contained
                    page={negativeKeywordSafePage}
                    totalPages={negativeKeywordPageCount}
                    total={filteredNegativeKeywords.length}
                    pageSize={negativeKeywordPageSize}
                    loading={negativeKeywordBusy}
                    ariaLabel="否词名单分页"
                    onPageChange={setNegativeKeywordPage}
                    onPageSizeChange={(size) => {
                      setNegativeKeywordPage(1);
                      setNegativeKeywordPageSize(size);
                    }}
                  />
                ) : null}
              </section>
            </DialogContent>
          </DialogBody>
        </DialogSurface>
      </Dialog>
      {rules && (
        <Dialog
          open={showRules}
          onOpenChange={(_, data) => {
            if (!data.open) closeRuleDialog();
          }}
        >
          <DialogSurface className="keyword-rule-dialog">
            <DialogBody>
              <DialogTitleWithSummary summary="统计当前项目全部账户、全部历史计划的累计数据；关键词可以升级，也可以因累计成本变差而降级">关键词分级规则</DialogTitleWithSummary>
              <DialogContent
                ref={ruleDialogContentRef}
                tabIndex={-1}
                className="keyword-rule-dialog-content"
              >
                <div className="keyword-rule-intro">
                  <div>
                    <span className="eyebrow">按顺序命中一个结果</span>
                  </div>
                </div>

                <section className="keyword-rule-section">
                  <div className="keyword-rule-section-title">
                    <div className="keyword-rule-heading-line">
                      <h3>已经产生加粉</h3>
                      <p>从 A 开始依次判断，命中后不再继续判断</p>
                    </div>
                  </div>
                  <div className="keyword-rule-table-wrap">
                    <table className="keyword-rule-table">
                      <thead>
                        <tr>
                          <th className="table-cell--center">结果</th>
                          <th className="table-cell--start">前提</th>
                          <th className="table-cell--start">累计消费与成本条件</th>
                          <th className="table-cell--start">含义</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td className="table-cell--center">
                            <b className="rule-tier tier-a">A</b>
                          </td>
                          <td className="table-cell--start">加粉数 ≥ 1</td>
                          <td className="table-cell--start">
                            <code>消费 ÷ 加粉数 ≤ ¥{rules.a_add_cost_max}</code>
                          </td>
                          <td className="table-cell--start">A成本，实际加粉成本达标</td>
                        </tr>
                        <tr>
                          <td className="table-cell--center">
                            <b className="rule-tier tier-b">B</b>
                          </td>
                          <td className="table-cell--start">加粉数 ≥ 1，未命中 A</td>
                          <td className="table-cell--start">
                            <code>
                              消费 ÷（加粉数 + 1）&lt; ¥
                              {rules.b_next_add_cost_max}
                            </code>
                          </td>
                          <td className="table-cell--start">B机会，再增加 1 个粉即可接近目标</td>
                        </tr>
                        <tr>
                          <td className="table-cell--center">
                            <b className="rule-tier tier-c">C</b>
                          </td>
                          <td className="table-cell--start">加粉数 ≥ 1，未命中 A/B</td>
                          <td className="table-cell--start">
                            <code>
                              消费 ÷（加粉数 × {rules.c_add_growth_factor}）&lt;
                              ¥{rules.c_projected_cost_max}
                            </code>
                          </td>
                          <td className="table-cell--start">C成本较高，仍有优化空间</td>
                        </tr>
                        <tr>
                          <td className="table-cell--center">
                            <b className="rule-tier tier-risk">高</b>
                          </td>
                          <td className="table-cell--start">加粉数 ≥ 1，未命中 A/B/C</td>
                          <td className="table-cell--start">实际成本和推算成本均超过上述标准</td>
                          <td className="table-cell--start">成本高，确认执行后直接进入黑名单</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </section>

                <section className="keyword-rule-section">
                  <div className="keyword-rule-section-title">
                    <div className="keyword-rule-heading-line">
                      <h3>尚未产生加粉</h3>
                      <p>只按累计消费分段，复制数不影响 D/E 分级</p>
                    </div>
                  </div>
                  <div className="keyword-rule-table-wrap">
                    <table className="keyword-rule-table">
                      <thead>
                        <tr>
                          <th className="table-cell--center">结果</th>
                          <th className="table-cell--start">前提</th>
                          <th className="table-cell--start">累计消费条件</th>
                          <th className="table-cell--start">含义</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td className="table-cell--center">
                            <b className="rule-tier tier-risk">空</b>
                          </td>
                          <td className="table-cell--start">加粉数 = 0</td>
                          <td className="table-cell--start">
                            <code>消费 ≥ ¥{rules.empty_spend_min}</code>
                          </td>
                          <td className="table-cell--start">空耗，确认执行后直接进入黑名单</td>
                        </tr>
                        <tr>
                          <td className="table-cell--center">
                            <b className="rule-tier tier-d">D</b>
                          </td>
                          <td className="table-cell--start">加粉数 = 0</td>
                          <td className="table-cell--start">
                            <code>
                              ¥{rules.d_spend_min} ≤ 消费 &lt; ¥
                              {rules.empty_spend_min}
                            </code>
                          </td>
                          <td className="table-cell--start">D消耗不足，不区分复制数</td>
                        </tr>
                        <tr>
                          <td className="table-cell--center">
                            <b className="rule-tier tier-e">E</b>
                          </td>
                          <td className="table-cell--start">加粉数 = 0</td>
                          <td className="table-cell--start">
                            <code>¥0 &lt; 消费 &lt; ¥{rules.d_spend_min}</code>
                          </td>
                          <td className="table-cell--start">E消耗很小，不区分复制数</td>
                        </tr>
                        <tr>
                          <td className="table-cell--center">
                            <b className="rule-tier tier-f">F</b>
                          </td>
                          <td className="table-cell--start">加粉数 = 0</td>
                          <td className="table-cell--start">
                            <code>消费 = ¥0</code>
                          </td>
                          <td className="table-cell--start">F拓展；完全缺少同步数据时保持原级</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </section>

                <section className="keyword-rule-settings">
                  <div className="keyword-rule-heading-line">
                    <h3>调整判定参数</h3>
                    <p>
                      修改下列数字后，表格条件会同步变化；D最低消费必须小于空耗起点
                    </p>
                  </div>
                  <div className="keyword-rule-grid">
                    {keywordTierRuleFields.map((field) => (
                      <Field
                        key={field.key}
                        label={field.label}
                        hint={`${field.description} 单位：${field.suffix}`}
                      >
                        <Input
                          type="number"
                          min={field.min}
                          step={field.step}
                          value={rules[field.key]}
                          onChange={(_, data) =>
                            updateRule(field.key, data.value)
                          }
                        />
                      </Field>
                    ))}
                  </div>
                </section>
                <div className="keyword-rule-note">
                  <strong>执行规则</strong>
                  <span>
                    试算不改数据；确认自动调整后，A-F
                    关键词会升降到对应计划级别，成本高和空耗直接进入本项目黑名单；整个过程只更新本地物料，不调用百度
                  </span>
                </div>
                {ruleFeedback && (
                  <div className="keyword-rule-feedback">{ruleFeedback}</div>
                )}
                {dryRun && (
                  <div className="keyword-rule-result">
                    <span>
                      关键词总数
                      <strong>{dryRun.total.toLocaleString("zh-CN")}</strong>
                    </span>
                    <span>
                      建议调整
                      <strong>
                        {dryRun.change_count.toLocaleString("zh-CN")}
                      </strong>
                    </span>
                    <span>
                      升级
                      <strong>
                        {dryRun.upgrade_count.toLocaleString("zh-CN")}
                      </strong>
                    </span>
                    <span>
                      降级
                      <strong>
                        {dryRun.downgrade_count.toLocaleString("zh-CN")}
                      </strong>
                    </span>
                    <span>
                      风险词
                      <strong>
                        {dryRun.risk_count.toLocaleString("zh-CN")}
                      </strong>
                    </span>
                    <span>
                      黑名单
                      <strong>
                        {dryRun.blacklisted_count.toLocaleString("zh-CN")}
                      </strong>
                    </span>
                  </div>
                )}
              </DialogContent>
              <DialogActions>
                <Button
                  appearance="secondary"
                  disabled={ruleBusy}
                  onClick={closeRuleDialog}
                >
                  取消
                </Button>
                <Button
                  appearance="secondary"
                  disabled={ruleBusy}
                  onClick={() => void previewRules()}
                >
                  试算当前参数
                </Button>
                <Button
                  appearance="primary"
                  disabled={ruleBusy}
                  onClick={() => void saveRules()}
                >
                  {ruleBusy ? "处理中…" : "保存规则"}
                </Button>
                {dryRun &&
                  (dryRun.change_count > 0 || dryRun.risk_count > 0) && (
                    <Button
                      appearance="primary"
                      disabled={ruleBusy}
                      onClick={() => setShowRiskConfirm(true)}
                    >
                      自动调整计划级别
                    </Button>
                  )}
              </DialogActions>
            </DialogBody>
          </DialogSurface>
        </Dialog>
      )}
      {rules && (
        <Dialog
          open={showRiskConfirm}
          onOpenChange={(_, data) => {
            if (!ruleBusy) setShowRiskConfirm(data.open);
          }}
        >
          <DialogSurface className="keyword-risk-confirm-dialog">
            <DialogBody>
              <DialogTitleWithSummary summary="仅更新本地物料；确认后按当前规则调整关键词级别">确认自动调整关键词计划级别</DialogTitleWithSummary>
              <DialogContent>
                <p className="dialog-description">
                  将按历史总数据和当前规则，把关键词调整到对应 A-F
                  计划级别；成本高和空耗会进入黑名单；预计调整{" "}
                  {dryRun?.change_count.toLocaleString("zh-CN") || 0}{" "}
                  个，其中风险词{" "}
                  {dryRun?.risk_count.toLocaleString("zh-CN") || 0}{" "}
                  个；只更新本地物料，不调用百度
                </p>
              </DialogContent>
              <DialogActions>
                <Button
                  appearance="secondary"
                  disabled={ruleBusy}
                  onClick={() => setShowRiskConfirm(false)}
                >
                  取消
                </Button>
                <Button
                  appearance="primary"
                  disabled={ruleBusy}
                  onClick={() => void applyTierAdjustments()}
                >
                  {ruleBusy ? "执行中…" : "确认自动调整"}
                </Button>
              </DialogActions>
            </DialogBody>
          </DialogSurface>
        </Dialog>
      )}
      {saved && preview && (
        <PopupMessage intent="success">
          追加完成：文件共 {preview.row_count} 行，新增 {preview.valid_count}{" "}
          个唯一关键词，跳过 {preview.skip_count} 个已存在或重复关键词
        </PopupMessage>
      )}
      {manualBlacklistFeedback && (
        <PopupMessage intent="success">{manualBlacklistFeedback}</PopupMessage>
      )}
      {error && <PopupMessage intent="error">{error}</PopupMessage>}
      {preview && (
        <section className="import-result">
          <div>
            <span>
              总行数<strong>{preview.row_count}</strong>
            </span>
            <span>
              有效<strong>{preview.valid_count}</strong>
            </span>
            <span>
              无效<strong>{preview.invalid_count}</strong>
            </span>
            <span>
              跳过<strong>{preview.skip_count}</strong>
            </span>
          </div>
          {preview.errors.length > 0 && (
            <details>
              <summary>查看前 {preview.errors.length} 条校验问题</summary>
              {preview.errors.map((item) => (
                <p key={`${item.row}-${item.message}`}>
                  第 {item.row} 行：{item.message}
                </p>
              ))}
            </details>
          )}
        </section>
      )}
      <section className="panel material-keyword-panel">
        <div className="panel-head material-keyword-toolbar">
          <div className="material-table-tools">
            <SearchField
              value={materialSearchInput}
              onChange={setMaterialSearchInput}
              onSearch={() => {
                setMaterialPage(1);
                setMaterialSearch(materialSearchInput.trim());
              }}
              onClear={() => {
                setMaterialSearchInput("");
                setMaterialPage(1);
                setMaterialSearch("");
              }}
              placeholder="搜索计划或关键词"
            />
            <label className="material-year-filter">
              <span>年份</span>
              <select
                value={selectedYear}
                disabled={materialLoading}
                onChange={(event) => {
                  setMaterialPage(1);
                  setSelectedYear(Number(event.target.value));
                }}
              >
                {Array.from(new Set([selectedYear, ...availableYears]))
                  .sort((a, b) => b - a)
                  .map((year) => (
                    <option key={year} value={year}>
                      {year}年
                    </option>
                  ))}
              </select>
            </label>
          </div>
          <div className="material-action-tools">
            <input
              ref={fileInputRef}
              className="material-file-input"
              type="file"
              hidden
              accept=".xlsx,.xlsm"
              disabled={busy}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
              }}
            />
            <Button
              size="small"
              appearance="secondary"
              onClick={() => setShowManualBlacklist(true)}
            >
              添加关键词黑名单
            </Button>
            <Button
              size="small"
              appearance="secondary"
              onClick={() => {
                setNegativeKeywordDialog("add");
                setNegativeKeywordFeedback(null);
              }}
            >
              添加否词
            </Button>
            <Button
              size="small"
              appearance="secondary"
              onClick={() => {
                setNegativeKeywordDialog("list");
                setNegativeKeywordFeedback(null);
              }}
            >
              否词名单
            </Button>
            <Button
              size="small"
              appearance="secondary"
              disabled={!rules}
              onClick={openRuleDialog}
            >
              分级规则
            </Button>
            <Button
              size="small"
              appearance="primary"
              disabled={busy}
              onClick={() => fileInputRef.current?.click()}
            >
              {busy ? "正在导入…" : "导入关键词物料"}
            </Button>
          </div>
        </div>
        {materialLoading ? (
          <div className="material-load-state" role="status">
            正在加载物料明细…
          </div>
        ) : materialLoadError ? (
          <PopupMessage intent="error">
            {materialLoadError}；请刷新页面或切换页码重试
          </PopupMessage>
        ) : materialKeywords.length ? (
          <div className="material-keyword-table-scroll">
            <table className="material-keyword-table">
              <thead>
                <tr>
                  <th className="table-cell--start">
                    <SelectionColumnFilter
                      label="计划"
                      options={materialFacets.campaign_names.map(
                        (value): SelectionColumnOption => [value, value],
                      )}
                      selected={materialCampaignFilters}
                      onChange={(values) => {
                        setMaterialPage(1);
                        setMaterialCampaignFilters(values);
                      }}
                    />
                  </th>
                  <th className="table-cell--start">
                    <TextColumnFilter
                      label="关键词"
                      value={materialKeywordFilter}
                      onChange={(value) => {
                        setMaterialPage(1);
                        setMaterialKeywordFilter(value);
                      }}
                    />
                  </th>
                  <th className="table-cell--end table-cell--number">展现</th>
                  <th className="table-cell--end table-cell--number">点击</th>
                  <th className="table-cell--end table-cell--number">消费</th>
                  <th className="table-cell--end table-cell--number">UV</th>
                  <th className="table-cell--end table-cell--number">复制</th>
                  <th className="table-cell--end table-cell--number">加粉</th>
                  <th className="table-cell--end table-cell--number">CPC</th>
                  <th className="table-cell--end table-cell--number">UV成本</th>
                  <th className="table-cell--end table-cell--number">复制成本</th>
                  <th className="table-cell--end table-cell--number">加粉成本</th>
                  <th className="table-cell--center">
                    <SelectionColumnFilter
                      label="状态"
                      options={
                        [
                          ["normal", "正常"],
                          ["blacklisted", "黑名单"],
                        ] as SelectionColumnOption[]
                      }
                      selected={materialStatusFilters}
                      onChange={(values) => {
                        setMaterialPage(1);
                        setMaterialStatusFilters(values);
                      }}
                    />
                  </th>
                  <th className="table-cell--center">操作</th>
                </tr>
              </thead>
              <tbody>
                {materialKeywords.map((item) => (
                  <tr
                    className={item.is_blacklisted ? "is-blacklisted" : ""}
                    key={item.id}
                  >
                    <td className="table-cell--start" title={item.campaign_name}>{item.campaign_name}</td>
                    <td className="table-cell--start" title={item.keyword_text}>{item.keyword_text}</td>
                    <td className="table-cell--end table-cell--number">{displayMetric(item.impressions)}</td>
                    <td className="table-cell--end table-cell--number">{displayMetric(item.clicks)}</td>
                    <td className="table-cell--end table-cell--number">{displayMetric(item.spend)}</td>
                    <td className="table-cell--end table-cell--number">{displayMetric(item.uv)}</td>
                    <td className="table-cell--end table-cell--number">{displayMetric(item.copies)}</td>
                    <td className="table-cell--end table-cell--number">{displayMetric(item.adds)}</td>
                    <td className="table-cell--end table-cell--number">{displayMetric(item.cpc)}</td>
                    <td className="table-cell--end table-cell--number">{displayMetric(item.uv_cost)}</td>
                    <td className="table-cell--end table-cell--number">{displayMetric(item.copy_cost)}</td>
                    <td className="table-cell--end table-cell--number">{displayMetric(item.add_cost)}</td>
                    <td className="table-cell--center">{item.is_blacklisted ? "黑名单" : "正常"}</td>
                    <td className="table-cell--center">
                      <Button
                        size="small"
                        appearance="subtle"
                        disabled={blacklistBusyId === item.id}
                        onClick={() => void toggleBlacklist(item)}
                      >
                        {item.is_blacklisted ? "移出" : "拉黑"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title={
              materialStatusFilters.length === 1 &&
              materialStatusFilters[0] === "blacklisted"
                ? "黑名单为空"
                : "尚无物料明细"
            }
            text={
              materialStatusFilters.length === 1 &&
              materialStatusFilters[0] === "blacklisted"
                ? "当前没有被拉黑的关键词"
                : "导入包含计划、关键词的 Excel 后，物料会以表格形式显示在这里"
            }
          />
        )}
        <ViewportStickyPagination
          page={materialPage}
          totalPages={materialTotalPages}
          total={materialKeywordTotal}
          pageSize={materialPageSize}
          loading={materialLoading}
          ariaLabel="物料分页"
          onPageChange={setMaterialPage}
          onPageSizeChange={(size) => {
            setMaterialPage(1);
            setMaterialPageSize(size);
          }}
        />
      </section>
    </>
  );
}

function AutomationStrategyPage({
  project,
  tasks,
  section,
}: {
  project: Project;
  tasks: TaskRow[];
  section: StrategySection;
}) {
  return (
    <section className="strategy-hub">
      <StrategyCenter
        embedded
        project={project}
        requestedAction={
          section === "refresh" || section === "runtime"
            ? "loop-check"
            : undefined
        }
        renderRecords={(action) => (
          <ExecutionRecordsPage
            key={action}
            project={project}
            initialTasks={tasks}
            strategyScope={action}
          />
        )}
        renderGlobal={(action: GlobalJudgmentAction) => (
          <section
            className="strategy-form-section realtime-closure-stack"
            aria-label={`${action === "account-status" ? "账户状态" : action === "cost-judgment" ? "成本判断" : "实时闭环"}设置`}
          >
            {action === "account-status" ? (
              <AccountJudgmentSettings project={project} view="account-status" />
            ) : action === "cost-judgment" ? (
              <AccountJudgmentSettings project={project} view="cost-judgment" />
            ) : (
              <>
                <ProjectRefreshSettings project={project} />
                <ProjectOperationsPage
                  view="loop-check"
                  project={project}
                  embedded
                />
              </>
            )}
          </section>
        )}
      />
    </section>
  );
}

function AccountJudgmentSettings({
  project,
  view,
}: {
  project: Project;
  view: "account-status" | "cost-judgment";
}) {
  const [value, setValue] = useState<CostJudgmentPreference | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ intent: "success" | "error"; text: string } | null>(null);
  useEffect(() => {
    setValue(null);
    setFeedback(null);
    if (view === "account-status") return;
    apiGet<CostJudgmentPreference>(`/projects/${project.id}/preferences/account_judgment`)
      .then(setValue)
      .catch(reason => setFeedback({ intent: "error", text: reason instanceof Error ? reason.message : "读取判定设置失败" }));
  }, [project.id, view]);
  const save = async () => {
    if (!value) return;
    setBusy(true);
    setFeedback(null);
    try {
      const saved = await apiPatch<CostJudgmentPreference>(`/projects/${project.id}/preferences/account_judgment`, { value });
      setValue(saved);
      setFeedback({ intent: "success", text: "成本判断设置已保存" });
    } catch (reason) {
      setFeedback({ intent: "error", text: reason instanceof Error ? reason.message : "保存失败" });
    } finally {
      setBusy(false);
    }
  };
  if (view === "account-status") return (
    <section className="panel settings-section account-judgment-settings">
      <div className="settings-section-head">
        <div><h2>账户状态</h2><p>根据账户、计划、历史展现与自动上线分配统一判定；已淘汰为最终态</p></div>
      </div>
      <div className="judgment-settings-single">
        <section className="judgment-rule-panel">
          <div className="judgment-rule-title"><h3>判定规则</h3><span>前端只展示后台统一结果</span></div>
          <div className="judgment-rule-list">
            {[
              ["未通过审核", "userStat = 4"], ["被禁用", "userStat = 7"], ["计划全停", "存在计划且全部暂停"],
              ["预算不足", "存在计划且 userStat = 11"], ["上线", "存在计划且不属于以上状态"],
              ["已淘汰", "无计划，且有淘汰事实或历史展现 > 0"], ["待上线", "无计划、无历史展现、有有效自动上线分配"],
              ["空账户", "无计划、无历史展现、无有效自动上线分配"],
            ].map(([name, description]) => <div key={name}><strong>{name}</strong><span>{description}</span></div>)}
          </div>
        </section>
      </div>
    </section>
  );
  if (!value) return feedback ? <PopupMessage intent={feedback.intent}>{feedback.text}</PopupMessage> : <LoadingView />;
  const mode = value.mode;
  const standard = value[mode];
  const conversionName = mode === "copy_cash" ? "复制" : "加粉";
  const setStandard = (key: "cold_start_spend_limit" | "cost_limit", next: string) =>
    setValue({ ...value, [mode]: { ...standard, [key]: next } });
  return (
    <section className="panel settings-section account-judgment-settings">
      <div className="settings-section-head">
        <div><h2>成本判断</h2><p>使用累计数据与最近 7 天数据；加粉现金成本和复制现金成本分别保存独立标准</p></div>
        <Button appearance="primary" disabled={busy} onClick={() => void save()}>{busy ? "保存中…" : "保存设置"}</Button>
      </div>
      {feedback ? <PopupMessage intent={feedback.intent}>{feedback.text}</PopupMessage> : null}
      <div className="judgment-settings-single">
        <section className="judgment-rule-panel cost-judgment-panel">
          <div className="judgment-rule-title"><h3>判定标准</h3><span>两套标准独立保存</span></div>
          <div className="cost-mode-switch" role="group" aria-label="成本判断方式">
            <button type="button" className={mode === "add_cash" ? "active" : ""} onClick={() => setValue({ ...value, mode: "add_cash" })}>加粉现金成本判定</button>
            <button type="button" className={mode === "copy_cash" ? "active" : ""} onClick={() => setValue({ ...value, mode: "copy_cash" })}>复制现金成本判定</button>
          </div>
          <div className="cost-standard-fields">
            <Field label="冷启动累计消耗线" hint={`累计消耗达到此值且没有${conversionName}时判为“空耗”`}>
              <Input type="number" min="0" max="1000000" step="0.01" value={standard.cold_start_spend_limit} contentAfter="元" onChange={(_, data) => setStandard("cold_start_spend_limit", data.value)} />
            </Field>
            <Field label={`${conversionName}现金成本合格线`} hint="累计成本优先；累计合格后再判断最近 7 天成本">
              <Input type="number" min="0" max="1000000" step="0.01" value={standard.cost_limit} contentAfter="元" onChange={(_, data) => setStandard("cost_limit", data.value)} />
            </Field>
          </div>
          <div className="cost-rule-summary">
            <span><b>冷启动期</b>累计消耗低于消耗线，且无{conversionName}</span>
            <span><b>空耗</b>累计消耗达到消耗线，且无{conversionName}</span>
            <span><b>成本高</b>累计现金成本高于合格线</span>
            <span><b>成本上涨</b>累计合格，且近 7 天成本超线，或无转化空耗超过消耗线</span>
            <span><b>成本合格</b>累计与近 7 天成本均合格，且近 7 天无超线空耗</span>
          </div>
        </section>
      </div>
    </section>
  );
}

function ProjectRefreshSettings({ project }: { project: Project }) {
  const [value, setValue] = useState<SettingsPreference | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{
    intent: "success" | "error";
    text: string;
  } | null>(null);
  useEffect(() => {
    setValue(null);
    apiGet<SettingsPreference>(`/projects/${project.id}/preferences/settings`)
      .then((result) => {
        setValue(result);
        setUiTimeZone(result.timezone);
      })
      .catch((reason) =>
        setFeedback({
          intent: "error",
          text:
            reason instanceof Error ? reason.message : "读取项目刷新设置失败",
        }),
      );
  }, [project.id]);
  const save = async () => {
    if (!value) return;
    setBusy(true);
    setFeedback(null);
    try {
      const saved = await apiPatch<SettingsPreference>(
        `/projects/${project.id}/preferences/settings`,
        { value },
      );
      setValue(saved);
      setUiTimeZone(saved.timezone);
      setFeedback({ intent: "success", text: "项目刷新设置已保存" });
    } catch (reason) {
      setFeedback({
        intent: "error",
        text: reason instanceof Error ? reason.message : "保存失败",
      });
    } finally {
      setBusy(false);
    }
  };
  if (!value)
    return feedback ? (
      <PopupMessage intent={feedback.intent}>{feedback.text}</PopupMessage>
    ) : (
      <LoadingView />
    );
  return (
    <section className="panel settings-section project-refresh-settings">
      <div className="settings-section-head">
        <div>
          <h2>项目数据刷新</h2>
          <p>
            该周期覆盖账户、百度报表、好多粉、预算、创意和归因等闭环数据，不属于某一个报表页面
          </p>
        </div>
        <Button
          appearance="primary"
          disabled={busy}
          onClick={() => void save()}
        >
          {busy ? "保存中…" : "保存设置"}
        </Button>
      </div>
      {feedback && (
        <PopupMessage intent={feedback.intent}>{feedback.text}</PopupMessage>
      )}
      <div className="settings-form-grid">
        <Field
          label="项目闭环刷新周期（分钟）"
          hint="默认 60 分钟，允许 15–1440 分钟"
        >
          <Input
            type="number"
            min={15}
            max={1440}
            value={String(value.report_refresh_minutes)}
            onChange={(_, data) =>
              setValue({
                ...value,
                report_refresh_minutes: Number(data.value) || 60,
              })
            }
          />
        </Field>
        <Field label="页面时区">
          <select
            value={value.timezone}
            onChange={(event) =>
              setValue({ ...value, timezone: event.target.value })
            }
          >
            <option value="Asia/Shanghai">北京时间（Asia/Shanghai）</option>
            <option value="UTC">UTC</option>
          </select>
        </Field>
      </div>
      <label className="setting-row">
        <Checkbox
          checked={value.automation_guard}
          onChange={(_, data) =>
            setValue({ ...value, automation_guard: data.checked === true })
          }
        />
        <span>
          <strong>自动化数据保护闸</strong>
          <small>数据缺失、归因异常或水位滞后时阻止自动写入百度</small>
        </span>
      </label>
    </section>
  );
}

function ReferenceTemplatePanel({ project }: { project: Project }) {
  const [template, setTemplate] = useState<ReferenceTemplate | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () =>
    apiGet<ReferenceTemplate | null>(
      `/projects/${project.id}/reference-template`,
    )
      .then(setTemplate)
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "读取参考模板失败"),
      )
      .finally(() => setLoading(false));
  useEffect(() => {
    setLoading(true);
    setError(null);
    void load();
  }, [project.id]);
  useEffect(() => {
    if (!taskId) return;
    const timer = window.setInterval(() => {
      apiGet<{ status: string; last_error?: string | null }>(`/projects/${project.id}/tasks/${taskId}`)
        .then((task) => {
          if (task.status === "succeeded") {
            window.clearInterval(timer);
            setTaskId(null);
            setSyncing(false);
            void load();
          }
          if (task.status === "failed" || task.status === "blocked") {
            window.clearInterval(timer);
            setTaskId(null);
            setSyncing(false);
            setError(task.last_error || "参考模板同步失败");
          }
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [project.id, taskId]);
  const sync = async () => {
    setSyncing(true);
    setError(null);
    try {
      const result = await apiPost<{ task_id: string }>(
        `/projects/${project.id}/reference-template/sync`,
        {},
      );
      setTaskId(result.task_id);
    } catch (reason) {
      setSyncing(false);
      setError(reason instanceof Error ? reason.message : "提交同步失败");
    }
  };
  const ocpcProject = template?.template_data.ocpc_projects[0];
  const ocpcBid = ocpcProject?.ocpc_bid;
  const audienceCount =
    template?.template_data.audiences.definitions.length || 0;
  return (
    <section className="panel reference-template-panel">
      <div className="panel-head">
        <div>
          <h2>参考账户设置模板</h2>
          <p>
            从百度账户 86459649
            只读提取可复用设置；不复制其项目、计划、单元、关键词或创意对象
          </p>
        </div>
        <div className="reference-template-actions">
          {template && (
            <Badge
              appearance="tint"
              color={
                template.analysis.status === "matched" ? "success" : "warning"
              }
            >
              v{template.version} ·{" "}
              {template.analysis.status === "matched"
                ? "检查通过"
                : `${template.analysis.issue_count} 项待复核`}
            </Badge>
          )}
          <Button
            appearance="secondary"
            disabled={syncing}
            onClick={() => void sync()}
          >
            {syncing ? "正在读取百度…" : template ? "重新提取设置" : "提取设置"}
          </Button>
        </div>
      </div>
      {error && <PopupMessage intent="error">{error}</PopupMessage>}
      {loading ? (
        <div className="reference-template-empty">正在读取模板状态…</div>
      ) : !template ? (
        <div className="reference-template-empty">
          尚未固化真实模板；投放预检会保持阻断，直到同步成功
        </div>
      ) : (
        <>
          <div className="reference-hierarchy relationship-only">
            <span>
              <small>父级</small>
              <strong>oCPC项目</strong>
            </span>
            <i>→</i>
            <span>
              <small>下级</small>
              <strong>计划</strong>
            </span>
            <i>→</i>
            <span>
              <small>下级</small>
              <strong>单元</strong>
            </span>
            <i>→</i>
            <div className="reference-hierarchy-branches">
              <span>
                <small>单元下</small>
                <strong>关键词</strong>
              </span>
              <span>
                <small>单元下</small>
                <strong>创意</strong>
              </span>
            </div>
          </div>
          <p className="reference-hierarchy-note">
            这里只说明百度对象的父子关系，不代表已把 86459649 的对象导入本项目
          </p>
          <div className="reference-template-facts">
            <span>
              oCPC目标出价
              <strong>{ocpcBid == null ? "—" : `¥${ocpcBid}`}</strong>
            </span>
            <span>
              单元出价
              <strong>
                {template.template_data.adgroup.max_price == null
                  ? "—"
                  : `¥${template.template_data.adgroup.max_price}`}
              </strong>
            </span>
            <span>
              推广地域
              <strong>
                {template.template_data.account_region.region_target.length}{" "}
                个地域ID
              </strong>
            </span>
            <span>
              短语 / 精确否定词
              <strong>
                {template.template_data.campaign.negative_words.length} /{" "}
                {template.template_data.campaign.exact_negative_words.length}
              </strong>
            </span>
            <span>
              人群设置模板<strong>{audienceCount} 套</strong>
            </span>
            <span>
              固化时间<strong>{formatDateTime(template.captured_at)}</strong>
            </span>
          </div>
          {template.analysis.issues.length > 0 && (
            <div className="reference-issues">
              {template.analysis.issues.slice(0, 6).map((issue) => (
                <div key={`${issue.code}-${issue.title}`}>
                  <Badge
                    appearance="tint"
                    color={issue.severity === "error" ? "danger" : "warning"}
                  >
                    {issue.severity === "error" ? "阻断" : "复核"}
                  </Badge>
                  <span>
                    <strong>{issue.title}</strong>
                    <small>{issue.detail}</small>
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function EmptyState({ title, text }: { title: string; text?: string }) {
  const materialColumns = [
    "计划",
    "关键词",
    "展现",
    "点击",
    "消费",
    "UV",
    "复制",
    "加粉",
    "CPC",
    "UV成本",
    "复制成本",
    "加粉成本",
  ];
  return (
    <>
      {title === "尚无物料明细" && (
        <div className="material-keyword-table-scroll">
          <table className="material-keyword-table">
            <thead>
              <tr>
                {materialColumns.map((column, index) => (
                  <th className={index < 2 ? "table-cell--start" : index < 12 ? "table-cell--end table-cell--number" : "table-cell--center"} key={column}>{column}</th>
                ))}
              </tr>
            </thead>
          </table>
        </div>
      )}
      <div className="empty-state">
        <strong>{title}</strong>
        {text && <p>{text}</p>}
      </div>
    </>
  );
}
function formatNumber(value: unknown) {
  return Number(value || 0).toLocaleString("zh-CN");
}
function formatDateTime(value?: string | null) {
  return value
    ? new Intl.DateTimeFormat("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: getUiTimeZone(),
      }).format(new Date(value))
    : "暂无";
}
function dateInput(daysAgo: number) {
  const value = new Date();
  value.setDate(value.getDate() - daysAgo);
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
function validateCaptureDateRange(dateFrom: string, dateTo: string) {
  if (!dateFrom || !dateTo) return "请选择完整的开始日期和结束日期";
  const start = new Date(`${dateFrom}T00:00:00Z`);
  const end = new Date(`${dateTo}T00:00:00Z`);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()))
    return "日期格式无效，请重新选择";
  if (start > end) return "开始日期不能晚于结束日期";
  if ((end.getTime() - start.getTime()) / 86400000 + 1 > 31)
    return "单次抓取最多选择 31 天";
  if (end > new Date(`${dateInput(0)}T00:00:00Z`))
    return "结束日期不能晚于今天";
  return null;
}
function captureStatusColor(
  value: string,
): "success" | "danger" | "warning" | "informative" {
  return value === "succeeded"
    ? "success"
    : value === "failed"
      ? "danger"
      : value === "blocked"
        ? "warning"
        : "informative";
}
function statusText(value: string) {
  return (
    (
      {
        queued: "已排队",
        pending: "等待中",
        ready: "等待执行",
        scheduled: "等待计划时间",
        running: "执行中",
        succeeded: "已完成",
        failed: "失败",
        blocked: "已阻塞",
        waiting_writes: "等待开启百度写入",
        cancelled: "已取消",
        superseded: "已由新任务替代",
        partial: "部分完成",
      } as Record<string, string>
    )[value] || value
  );
}

export default App;
