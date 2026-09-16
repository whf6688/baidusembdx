export type Account = {
  id: string; project_id: string; manager_id?: string | null
  baidu_account_id: number; login_name: string; manager_login_name: string
  account_type: string; balance: string; balance_snapshot_at?: string | null; permission_status: string; is_active: boolean
  balance_alert?: boolean; cash_group_balance?: string | null; average_daily_spend_7d?: string | null
  balance_days_remaining?: string | null; balance_group_account_count?: number | null; balance_group_fresh?: boolean
  balance_metric_date_from?: string | null; balance_metric_date_to?: string | null
  account_subject?: string | null; lifecycle_stage?: string | null; account_status?: string | null; active_keyword_count: number
  lifecycle_override?: string | null; lifecycle_source?: 'automatic' | 'manual'
  lifetime_spend?: string | null; lifecycle_evaluated_at?: string | null; operator_name?: string | null
  eliminated_at?: string | null; elimination_reason?: string | null
  page_type?: string | null; promotion_page?: string | null; landing_url_template?: string | null
  rebate_rate?: string | null; recharge_account?: string | null; last_synced_at?: string | null
}
export type AccountManager = {
  id: string; project_id: string; baidu_user_id?: number | null; login_name: string
  display_name?: string | null; auth_status: string; is_active: boolean
  last_synced_at?: string | null; account_count: number
  balance?: string | null; balance_account_name?: string | null; balance_snapshot_at?: string | null
  rebate_rate?: string | null; balance_warning_threshold?: string | null; balance_warning_active?: boolean; recharge_account?: string | null
}
export type AlertRow = { id: string; type: string; severity: string; title: string; details: Record<string, unknown>; status: string; created_at: string }
export type TaskRow = {
  id: string; task_type: string; status: string; current_node: string; progress: number
  execution_action?: string | null
  retry_count: number; last_error?: string | null; result_summary?: string | null
  operation_id?: string | null; operation_type?: string | null
  account_name?: string | null; account_id?: number | null; manager_login_name?: string | null
  can_resume?: boolean; superseded?: boolean
  readback?: {
    campaign_count?: number; adgroup_count?: number; keyword_count?: number
    creative_count?: number; audience_count?: number
  } | null
  heartbeat_at?: string | null; created_at: string; updated_at?: string | null
}
export type NotificationItem = {
  id: string
  category: 'task_status' | 'refund_due' | 'low_balance' | string
  severity: 'info' | 'success' | 'warning' | 'error' | string
  title: string
  summary: string
  body: string
  payload: Record<string, unknown>
  occurred_at: string
  created_at: string
  is_read: boolean
}
export type NotificationFeed = { unread_count: number; items: NotificationItem[] }
export type Project = { id: string; code: string; name: string; enabled: boolean; manager_count: number; account_count: number }
export type CodeSyncStatus = {
  enabled: boolean
  running: boolean
  status: 'idle' | 'running' | 'success' | 'no_changes' | 'conflict' | 'failed'
  repository: string
  repository_url: string
  branch: string
  remote: string
  remote_verified: boolean
  target_branch: string
  next_run_at: string
  syncable_count: number
  excluded_count: number
  ahead_count: number
  behind_count: number
  last_commit?: string | null
  last_commit_message?: string | null
  last_finished_at?: string | null
  summary: string
  last_error?: string | null
  conflict_files: string[]
}
export type RuntimeJobKey = 'initial_budget_reset' | 'realtime_closure' | 'account_balance_status' | 'historical_spend_backfill'
export type RuntimeJobHealth = {
  key: RuntimeJobKey
  label: string
  status: 'normal' | 'running' | 'warning' | 'error' | 'waiting'
  status_text: string
  detail: string
  updated_at?: string | null
  can_refresh: boolean
}
export type RuntimeJobsHealth = {
  overall_status: 'normal' | 'running' | 'warning' | 'error' | 'waiting'
  jobs: RuntimeJobHealth[]
}
export type PermissionLevel = 'hidden' | 'view' | 'manage'
export type PermissionModule = 'account_management' | 'account_list' | 'auto_launch' | 'reports' | 'finance_reports' | 'member_management' | 'strategies'
export type NavigationPermissions = Record<PermissionModule, PermissionLevel>
export type ProjectAccess = {
  is_system_owner: boolean
  member_id: string | null
  permissions: NavigationPermissions
  data_scope: 'self' | 'team' | 'project'
  operator_names: string[] | null
  supervisor_id: string | null
  version: number
}

export type RechargeReconciliationRow = {
  date: string; account_name: string; account_id: number; manager_name: string
  type: '充值' | '退款'; movement_type: 'recharge' | 'refund'
  account_currency: string; rebate_rate: string | null; cash_amount: string; watermark: string | null
}
export type RechargeReconciliationReport = {
  rows: RechargeReconciliationRow[]
  summary: { account_currency: string; cash_amount: string }
  total: number; page: number; page_size: number; total_pages: number; watermark: string | null
}
export type ProfitReportRow = {
  date: string; project_name: string; operator_name: string | null
  reported_spend: string | null; conversions: number; reported_conversion_cost: string | null
  account_spend: string; cash_spend: string; cash_conversion_cost: string | null; profit: string | null
}
export type ProfitReport = {
  rows: ProfitReportRow[]
  summary: {
    reported_spend: string | null; conversions: number; reported_conversion_cost: string | null
    account_spend: string; cash_spend: string; cash_conversion_cost: string | null; profit: string | null
  }
  metric_mode: 'copy' | 'add'; operator_name: string | null; operator_names: string[]
  total: number; page: number; page_size: number; total_pages: number
}
export type ProjectMember = {
  id: string
  project_id: string
  username: string
  display_name: string
  operator_name: string | null
  supervisor_id: string | null
  supervisor_name: string | null
  data_scope: 'self' | 'team' | 'project'
  permissions: NavigationPermissions
  permission_count: number
  is_active: boolean
  is_system_owner: boolean
  version: number
  updated_by: string
  updated_at: string | null
}
export type ProjectMemberPage = {
  rows: ProjectMember[]
  total: number
  page: number
  page_size: number
  total_pages: number
  supervisors: Array<{ id: string; name: string }>
  summary: { total: number; enabled: number; supervisors: number; disabled: number }
}
export type KeywordPlanUnit = { name: string; purpose: string; tiers: string[]; keyword_count: number; keywords: string[] }
export type KeywordPlanAccount = {
  account_id: number; unit_count: number; active_unit_count: number
  keyword_instances: number; operation_keyword_instances: number
  abc_keyword_instances: number; def_keyword_instances: number
  abc_percent: number; def_percent: number; units: KeywordPlanUnit[]
}
export type KeywordPlanPreview = {
  strategy: string
  config: { a_unit_count: number; unit_capacity: number; batch_number: number }
  source_counts: Record<string, number>
  account_count: number
  batch: {
    number: number; total: number; mode: 'initial' | 'replace_def'; has_more: boolean; next_number: number | null
    abc_target_percent: number; def_target_percent: number; allocation_mode: 'stable_random'
    abc_instances_per_account: number; def_target_per_account: number; capacity: number
    selected: number; selected_keywords: number
    selected_counts: Record<string, number>; selected_instance_counts: Record<string, number>
    remaining: number; remaining_keywords: number
    total_def_keywords: number; total_def_instances: number; candidate_shortage: boolean
  }
  accounts: KeywordPlanAccount[]
}
export type AdBuildMode = 'specified_accounts' | 'specified_managers' | 'random' | 'multi_subjects' | 'specified_subjects'
export type KeywordBuildMode = 'preferred' | 'full'
export type AdBuildAccess = {
  id?: string; project_id?: string; username: string; display_name: string
  operator_name?: string | null; operator_names?: string[] | null; data_scope?: 'self' | 'team' | 'project'
  can_build_ads: boolean; is_active: boolean; restricted?: boolean
  eligible_account_count?: number; updated_by?: string; updated_at?: string
}
export type ReferenceTemplate = {
  id: string; project_id: string; source_account_id: number; source_login_name: string; manager_login_name: string
  version: number; status: string; captured_at: string; raw_data_path?: string | null; raw_sha256?: string | null; is_active: boolean; created_by: string
  hierarchy_counts: Record<string, number>
  template_data: {
    hierarchy_schema: { root: string; edges: Array<{ parent: string; child: string; relation: string }>; note: string }
    account_region: { region_target: number[]; geo_location_status?: number | null }
    campaign: { negative_words: string[]; exact_negative_words: string[] }
    adgroup: { max_price?: number | null; consistency: { max_price: { consistent: boolean; variant_count: number } } }
    ocpc_projects: Array<Record<string, unknown>>
    audiences: { definitions: Array<Record<string, unknown>>; binding: Record<string, unknown> }
  }
  analysis: {
    status: 'matched' | 'needs_review'; issue_count: number
    issues: Array<{ severity: 'error' | 'warning'; code: string; title: string; detail: string }>
    checks: Record<string, boolean | number>
  }
}
export type AdBuildAccount = {
  id: string; account_id: number; login_name: string; account_subject?: string | null
  account_status?: string | null; account_type: string; page_type?: string | null
  promotion_page?: string | null; promotion_link?: string | null; permission_status: string
  keyword_url_mode: 'none' | 'per_keyword_utf8_encoded'; keyword_landing_url?: string | null
  keyword_url_generation?: {
    scope: 'per_keyword'; encoding: 'utf-8'; keyword_parameter: 'keyword'; encoded_value_source: 'material_keywords.keyword_utf8_encoded'
    account_parameter: 'zhanghuid'; account_value_source: 'target_account_id'
    position_parameter: 'e_adposition'; position_macro: '{adposition}'; forbidden_parameter: 'kw_enc_utf8'
  } | null
  issues: string[]
}
export type BaiduRegionNode = {
  id: number
  name: string
  level: 'province' | 'city'
  children?: BaiduRegionNode[]
}
export type BaiduRegionCatalog = {
  version: string
  country: { id: number; name: string }
  source: { province_city_flat: string; province_city: string }
  selectable_count: number
  regions: BaiduRegionNode[]
}
export type AdBuildRegionPreference = {
  region_target: number[]
  geo_location_status: 0 | 1
  revision: number
  catalog_version: string
}
export type AdBuildPreview = {
  keyword_mode: KeywordBuildMode
  selection_mode: AdBuildMode; execution_mode: 'immediate' | 'scheduled'
  selection_fingerprint: string; material_fingerprint: string; negative_keyword_fingerprint: string; selected_account_ids: number[]
  material_plan: {
    mode: KeywordBuildMode; campaign_count: number; per_account_keyword_count: number; description: string
    campaigns: Array<{ name: string; keyword_count: number; unit_count: number }>
  }
  negative_keywords: { phrase_count: number; exact_count: number; runtime_source: 'project_postgresql' }
  selected_count: number; ready_count: number; blocked_count: number; permission_warning_count: number
  can_submit: boolean; errors: string[]; warnings: string[]; accounts: AdBuildAccount[]
  available_subjects: Array<{ name: string; empty_count: number; ready_count: number; blocked_count: number }>
  subject_allocation: Record<string, number>; material_keyword_count: number
  creative_count_per_account: number; creative_available_combination_count: number
  creative_blacklisted_combination_count: number
  creative_segment_counts: Record<'title' | 'description1' | 'description2', number>
  creative_pool_fingerprint: string
  build_settings: {
    project_bid: string; online_schedule_enabled: boolean; online_weekdays: number[]
    online_start_hour: number; online_end_hour: number
    online_schedule?: Array<{ weekDay: number; startHour: number; endHour: number }> | null
    plan_pause_schedule: Array<{ weekDay: number; startHour: number; endHour: number }>
    campaign_region_mode: 'unset'; account_region_update: 'account_promotion_region_list'
    region_target: number[]; region_count: number; geo_location_status: 0 | 1
  }
  batch_size: number; batch_interval_minutes: number; batch_count: number
  required_batch_count: number; scheduled_dates: string[]; scheduled_times: string[]
  schedule_unlimited: boolean; available_schedule_slot_count?: number | null; unused_schedule_slot_count?: number | null
  first_scheduled_at: string; estimated_completed_at: string
  batches: Array<{ number: number; scheduled_at: string; account_count: number; account_ids: number[]; account_names: string[] }>
  workflow_version: string
  workflow: Array<{ key: string; label: string; detail: string; applies_to: string }>
  access_scope: {
    username: string; restricted: boolean; operator_name: string | null; eligible_account_count: number
  }
  build_rule: {
    version: string; source: 'system_versioned_rules'; audience_count: number
    campaign_equipment_type: number; ocpc_conversion_types: number[]
  }
}
export type AdBuildJob = {
  id: string; keyword_mode: KeywordBuildMode; selection_mode: AdBuildMode; execution_mode: 'immediate' | 'scheduled'; status: string
  first_scheduled_at: string; batch_size: number; batch_interval_minutes: number
  account_count: number; batch_count: number; workflow_version: string; created_by: string; created_at: string
  account_status_counts?: Record<string, number>
  batches: Array<{
    id: string; number: number; scheduled_at: string; status: string; account_count: number
    accounts?: Array<{
      account_id?: number | null; account_name?: string | null; account_subject?: string | null
      manager_login_name?: string | null; operation_id?: string | null; task_id?: string | null
      status: string; current_node: string; progress: number; last_error?: string | null
      result_summary?: string | null; updated_at?: string | null
      nodes?: Array<{
        key: string; label: string; status: 'pending' | 'running' | 'succeeded' | 'failed'
        started_at?: string | null; completed_at?: string | null; duration_seconds?: number | null; message?: string | null
      }>
    }>
  }>
}
export type AdBuildCreateResult = {
  id: string; status: string; account_count: number; batch_count: number; operation_count: number; writes_enabled: boolean
  batches: Array<{ id: string; number: number; scheduled_at: string; status: string; account_count: number }>
}
export type ImportPreview = {
  filename: string; sha256: string; row_count: number; valid_count: number; invalid_count: number
  create_count: number; update_count: number; skip_count: number
  errors: Array<{ row: number; message: string }>
  unit_chunks: Array<{
    account_id?: number | null; login_name?: string; landing_url_template?: string
    campaign: string; keyword_count: number; unit_count: number
  }>
  target_accounts: Array<{
    account_id: number; login_name: string; landing_url_template: string
  }>
}
export type MaterialRow = {
  id: string; name: string; status: string; current_version: number; created_at: string
  latest?: { version: number; row_count: number; sha256: string; summary: ImportPreview; created_by: string; created_at: string } | null
}
export type MaterialKeywordRow = {
  id: string
  campaign_name: string
  keyword_text: string
  impressions: number | null
  clicks: number | null
  spend: string | null
  uv: number | null
  copies: number | null
  adds: number | null
  cpc: string | null
  uv_cost: string | null
  copy_cost: string | null
  add_cost: string | null
  is_blacklisted: boolean
  blacklist_reason: string | null
}
export type MaterialKeywordPage = {
  items: MaterialKeywordRow[]
  total: number
  page: number
  page_size: number
  selected_year: number | null
  available_years: number[]
}
export type MaterialKeywordFacets = {
  campaign_names: string[]
}
export type CreativeSegmentType = 'title' | 'description1' | 'description2'
export type CreativeSegmentRow = {
  id: string; content: string; is_blacklisted: boolean; rejection_count: number; blacklist_reason?: string | null; created_at: string
}
export type CreativeCombinationRow = {
  id: string; combination_hash: string; title: string; description1: string; description2: string
  is_blacklisted: boolean; rejection_count: number; blacklist_reason?: string | null; blacklisted_at?: string | null
}
export type CreativeCenter = {
  segment_counts: Record<CreativeSegmentType, number>
  total_combination_count: number; available_combination_count: number; registered_combination_count: number; blacklisted_combination_count: number
  fingerprint: string; creative_count_per_account: number; second_hop_rejection_threshold: number; segment_rejection_threshold: number
  segments: Record<CreativeSegmentType, CreativeSegmentRow[]>
  tracked_combinations: CreativeCombinationRow[]
  assignment_counts: Record<string, number>
}
export type CreativeCombinationPreview = {
  requested_count: number; selected_count: number
  items: Array<{ combination_hash: string; title: string; description1: string; description2: string }>
}
export type KeywordTierRules = {
  a_add_cost_max: string
  b_next_add_cost_max: string
  c_add_growth_factor: string
  c_projected_cost_max: string
  empty_spend_min: string
  d_spend_min: string
}
export type KeywordTierDryRun = {
  total: number
  evaluable_total: number
  change_count: number
  upgrade_count: number
  downgrade_count: number
  risk_count: number
  blacklisted_count: number
  current_counts: Record<string, number>
  evaluated_counts: Record<string, number>
  samples: Array<{
    keyword: string
    from_plan: string
    evaluated_plan: string
  }>
  rules: KeywordTierRules
}
export type DailyReportRow = {
    date: string; account_id: number; account_name: string; impressions: number; clicks: number
  balance?: string | null; balance_snapshot_at?: string | null
  cost_status: string; operator_name?: string | null; manager_id?: string | null
  manager_name?: string | null; account_type?: string | null
  page_type?: string | null; promotion_page?: string | null; promotion_link?: string | null
  rebate_rate?: string | null; recharge_account?: string | null
  spend: string; cash_spend?: string | null; uv: number; copies: number; adds: number
  cpc?: string | null; uv_cost?: string | null; copy_cost?: string | null
  add_cost?: string | null; cash_copy_cost?: string | null; cash_add_cost?: string | null; add_rate?: string | null
}
export type CostJudgmentPreference = {
  mode: 'add_cash' | 'copy_cash'
  add_cash: { cold_start_spend_limit: string; cost_limit: string }
  copy_cash: { cold_start_spend_limit: string; cost_limit: string }
}
export type DailyReport = {
  date_from: string; date_to: string; watermark?: string | null
  total: number; page: number; page_size: number; total_pages: number
  search: string; page_type: string; page_types: string[]
  manager_id: string; managers: Array<{ id: string; name: string }>
  account_type: string; account_types: string[]
  operator_name: string; operator_names: string[]; has_unassigned_operator: boolean
  account_names: string[]; cost_statuses: string[]; cost_judgment: CostJudgmentPreference
  sort_by: string; sort_order: 'asc' | 'desc'
  summary: { spend: string; cash_spend?: string | null; impressions: number; clicks: number; uv: number; copies: number; adds: number; cpc?: string | null; uv_cost?: string | null; copy_cost?: string | null; add_cost?: string | null; cash_copy_cost?: string | null; cash_add_cost?: string | null; add_rate?: string | null }
  comparison?: {
    date_from: string; date_to: string
    summary: { spend: string; cash_spend?: string | null; impressions: number; clicks: number; uv: number; copies: number; adds: number; cpc?: string | null; uv_cost?: string | null; copy_cost?: string | null; add_cost?: string | null; cash_add_cost?: string | null; add_rate?: string | null }
    trends: Record<string, { direction: 'up' | 'down' | 'flat' | 'muted'; percent: string | null }>
  }
  rows: DailyReportRow[]
}
export type TrackingPreference = {
  enabled: boolean; interval_minutes: number; attribution_window_hours: number
  runtime_enabled: boolean; credentials_configured: boolean; session_key_configured: boolean
}
export type TrackingCaptureCreateResult = {
  task_id: string; status: string; date_from: string; date_to: string
}
export type TrackingCaptureSource = {
  name: string; record_count: number; expected_count: number; complete: boolean
}
export type TrackingCaptureIngestion = {
  records?: number; account_matched?: number; unmatched_account?: number
  second_hop_missing_tracking_keyword?: number; uv?: number; copies?: number; adds?: number
  material_keywords_created?: number; tracking_keywords?: number; event_dates?: string[]
}
export type TrackingCaptureTask = {
  id: string; status: string; current_node: string; progress: number
  date_from: string; date_to: string; created_at: string; last_error?: string | null
  ingestion: TrackingCaptureIngestion
  captures: TrackingCaptureSource[]
}
export type TrackingUnmatchedItem = {
  id: string; source_type: string; event_date: string
  baidu_account_id?: number | null; tracking_keyword?: string | null; exclusion_reason?: string | null
}
export type TrackingUnmatched = {
  total: number; summary: Record<string, number>; items: TrackingUnmatchedItem[]
}
export type SettingsPreference = { report_refresh_minutes: number; timezone: string; automation_guard: boolean }
export type AuditEvent = {
  id: string; actor: string; action: string; target_type: string; target_id?: string | null
  summary: string; details: Record<string, unknown>; created_at: string
}
export type OperationsCenter = {
  loop_check: {
    interval_minutes: number; status: 'healthy' | 'waiting_data'
    baidu_watermark?: string | null; hduofen_watermark?: string | null
    budget_watermark?: string | null; creative_watermark?: string | null
    sources: Record<string, { status: string; snapshot_at?: string | null; fresh: boolean; message?: string | null }>
    next_action: string
  }
  budget_reset: {
    schedule: string; target_budget: string; scope: string; test_account_count: number
    candidate_count?: number | null; budget_snapshot_available: boolean
    budget_snapshot_status: 'ready' | 'partial' | 'stale' | 'missing'
    budget_snapshot_fresh_count: number; budget_snapshot_missing_count: number
    only_changed_accounts: boolean; writes_enabled: boolean
    history: OperationsHistory
  }
  budget_append: {
    interval_minutes: number; add_cost_limit: string; utilization_threshold: string
    round_amounts: Array<{ round: number; amount: string }>
    candidate_count?: number | null; budget_snapshot_available: boolean
    budget_snapshot_status: 'ready' | 'partial' | 'stale' | 'missing'
    budget_snapshot_fresh_count: number; budget_snapshot_missing_count: number
    marginal_recheck: boolean; writes_enabled: boolean
    history: OperationsHistory
  }
  eliminations: {
    total: number; page: number; page_size: number; total_pages: number
    rows: Array<{
      id: string; eliminated_at?: string | null; account_id: number; account_name: string
      spend: string; adds: number; add_cost?: string | null; recharge_account?: string | null
      reason?: string | null
    }>
  }
  filters: { date_from: string; date_to: string }
  blacklist: { account_count: number; regular_api_calls: string; final_archive: string }
}
export type OperationsHistory = {
  total: number; page: number; page_size: number; total_pages: number
  rows: Array<{
    id: string; created_at: string; account_id?: string | null; account_name: string
    before_budget?: string | null; after_budget?: string | null; status: string
    append_round?: number | null; append_amount?: string | null
  }>
}

export type NegativeKeywordMatchType = 'phrase' | 'exact'
export type NegativeKeywordItem = {
  id: string; project_id: string; match_type: NegativeKeywordMatchType; keyword_text: string
  source: 'manual' | 'reference_template'; reference_template_version_id?: string | null
  created_by: string; created_at: string
}
export type NegativeKeywordLibrary = {
  items: NegativeKeywordItem[]; counts: Record<NegativeKeywordMatchType, number>
  total: number; runtime_source: 'project_postgresql'
}
export type NegativeKeywordTemplatePreview = {
  template_id: string; template_version: number
  source_project_id: string; source_project_name: string
  source_scope: 'current_project' | 'latest_available'
  candidate_counts: Record<NegativeKeywordMatchType, number>; candidate_total: number
  new_counts: Record<NegativeKeywordMatchType, number>; new_total: number
  duplicate_counts: Record<NegativeKeywordMatchType, number>; duplicate_total: number
  fingerprint: string
  runtime_source_after_copy: 'project_postgresql'
}
export type AccountWorkspaceRow = {
  id: string; account_id: number; account_name: string; subject?: string | null
  account_status: string; cost_status: string; remote_status_code?: number | null
  manager_id?: string | null; manager_name: string; operator_name?: string | null; account_type: string
  page_type?: string | null; promotion_page?: string | null; promotion_link?: string | null
  rebate_rate?: string | null; cash_account?: string | null; spend: string; adds: number
  add_cost?: string | null; copy_cost?: string | null; cash_copy_cost?: string | null; cash_add_cost?: string | null; impressions: number; clicks: number; uv: number; copies: number
  cpm?: string | null; ctr?: string | null
  budget?: string | null; balance: string; balance_snapshot_at?: string | null
  permission_status: string; is_active: boolean; campaign_cache_status?: string | null
  campaign_cache_synced_at?: string | null; last_synced_at?: string | null; data_watermark?: string | null
}
export type AccountOcpcProjectRow = {
  id: string; ocpc_project_id: number; ocpc_project_name?: string | null; ocpc_bid?: string | null
  bid_type?: number | null; remote_status?: number | null; scope: Array<Record<string, unknown>>
  last_seen_at?: string | null
}
export type AccountOcpcProjectList = {
  account_id: string; account_name: string; cache_status?: string | null
  cache_synced_at?: string | null; rows: AccountOcpcProjectRow[]
}
export type AccountWorkspace = {
  date_from: string; date_to: string; rows: AccountWorkspaceRow[]; total: number
  page: number; page_size: number; total_pages: number
  summary: {
    account_count: number; spend: string; cash_spend?: string | null
    impressions: number; clicks: number; uv: number; copies: number; adds: number
    cpc?: string | null; uv_cost?: string | null; copy_cost?: string | null
    add_cost?: string | null; cash_copy_cost?: string | null; cash_add_cost?: string | null; add_rate?: string | null
  }
  comparison?: {
    date_from: string; date_to: string
    summary: {
      spend: string; cash_spend?: string | null; impressions: number; clicks: number; uv: number; copies: number; adds: number
      cpc?: string | null; uv_cost?: string | null; copy_cost?: string | null; add_cost?: string | null; cash_add_cost?: string | null; add_rate?: string | null
    }
    trends: Record<string, { direction: 'up' | 'down' | 'flat' | 'muted'; percent: string | null }>
  }
  account_status_counts: Record<string, number>; cost_status_counts: Record<string, number>
  cost_judgment: CostJudgmentPreference; watermark?: string | null
}
export type AccountWorkspaceFacets = {
  subjects: string[]; operators: string[]; account_types: string[]; page_types: string[]; account_names: string[]
  managers: Array<{ id: string; name: string }>
}
export type AccountManagementRow = {
  id: string; account_id: number; account_name: string
  manager_id?: string | null; manager_name?: string | null; operator_name?: string | null
  account_type: string; page_type?: string | null; promotion_page?: string | null
  promotion_link?: string | null; balance?: string | null
  balance_source_account_name?: string | null; balance_snapshot_at?: string | null
  rebate_rate?: string | null; remote_status_code?: number | null
  remote_status_text: string; remote_status_at?: string | null
  authorization_status: string; is_active: boolean
}
export type AccountManagement = {
  rows: AccountManagementRow[]; total: number; page: number; page_size: number; total_pages: number
}
export type StrategyRoundAmount = { round: number; amount: string }
export type StrategyConfigValue = string | string[] | number | StrategyRoundAmount[]
export type StrategyVersion = {
  id: string; version: number; status: 'draft' | 'published'; base_version_id?: string | null
  draft_revision: number; config: Record<string, StrategyConfigValue>
  config_hash: string; created_by: string; published_by?: string | null
  created_at: string; published_at?: string | null
}
export type StrategyPolicy = {
  key: 'budget_reset' | 'budget_append' | 'elimination' | 'keyword_tiers'
  revision: number; active: StrategyVersion; draft?: StrategyVersion | null
}
export type StrategyEvaluation = {
  id: string; config_hash: string; created_at: string
  result: { candidate_count: number; evaluated_count?: number; sample_account_ids?: number[]; action: string }
}
export type AdBuildPlanSettingItem = {
  campaign_name: string
  keyword_count: number
  repeat_count: number
  is_configured: boolean
}
export type AdBuildPlanSettings = {
  items: AdBuildPlanSettingItem[]
  plan_count: number
  has_draft: boolean
  has_published: boolean
  updated_by?: string | null
  updated_at?: string | null
}
