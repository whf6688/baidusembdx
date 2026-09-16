import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .creatives import CREATIVE_COUNT_PER_ACCOUNT, validate_segment_content
from .models import AccountType, KeywordTier
from .regions import MIGRATED_DEFAULT_REGION_TARGET


class Envelope(BaseModel):
    request_id: str
    status: str = "ok"
    data: Any = None
    error: dict[str, Any] | None = None
    data_at: datetime | None = None
    snapshot_watermark: datetime | None = None


class WebLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class SystemOwnerCredentialUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._@-]+$")
    password: str | None = Field(default=None, min_length=8, max_length=256)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_owner_username(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class MetricValue(BaseModel):
    value: Decimal | int | None
    change: Decimal | None = None


class DashboardSummary(BaseModel):
    spend: MetricValue
    impressions: MetricValue
    clicks: MetricValue
    uv: MetricValue
    copies: MetricValue
    adds: MetricValue
    cpc: MetricValue
    uv_cost: MetricValue
    add_cost: MetricValue
    add_rate: MetricValue
    active_accounts: int
    alert_count: int
    data_freshness: dict[str, Any]


class ProjectCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[a-z][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=100)

    @field_validator("code", "name", mode="before")
    @classmethod
    def strip_project_text(cls, value: str) -> str:
        return value.strip()


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_project_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class HduofenCaptureRequest(BaseModel):
    date_from: date
    date_to: date


class FinanceProfitInputItem(BaseModel):
    report_date: date
    reported_spend: Decimal = Field(ge=Decimal("0"), le=Decimal("999999999.99"), decimal_places=2)


class FinanceProfitUpdate(BaseModel):
    operator_name: str | None = Field(default=None, max_length=30)
    rows: list[FinanceProfitInputItem] = Field(min_length=1, max_length=366)

    @field_validator("operator_name", mode="before")
    @classmethod
    def normalize_finance_operator(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    @model_validator(mode="after")
    def unique_finance_dates(self):
        dates = [row.report_date for row in self.rows]
        if len(dates) != len(set(dates)):
            raise ValueError("利润报表同一日期不能重复提交")
        return self


class ManagerCreate(BaseModel):
    login_name: str = Field(min_length=1, max_length=150)
    display_name: str | None = Field(default=None, max_length=150)
    rebate_rate: Decimal | None = Field(default=None, ge=0, le=100)
    recharge_account: str | None = Field(default=None, max_length=200)

    @field_validator("login_name", "display_name", "recharge_account", mode="before")
    @classmethod
    def strip_manager_text(cls, value: str | None) -> str | None:
        if not isinstance(value, str):
            return value
        return value.strip() or None


class ManagerStatusUpdate(BaseModel):
    is_active: bool


class ManagerSettingsUpdate(BaseModel):
    rebate_rate: Decimal | None = Field(default=None, ge=0, le=100)
    balance_warning_threshold: Decimal | None = Field(default=None, ge=0, le=999999999999)

    @model_validator(mode="after")
    def require_setting(self):
        if not self.model_fields_set.intersection({"rebate_rate", "balance_warning_threshold"}):
            raise ValueError("请至少提交一项管家设置")
        return self


class AccountDraftCreate(BaseModel):
    login_name: str = Field(min_length=1, max_length=150)
    manager_id: uuid.UUID | None = None
    account_type: str = Field(default="二跳账户", max_length=30)
    landing_url_template: str | None = Field(default=None, max_length=2000)

    @field_validator("login_name", "account_type", "landing_url_template", mode="before")
    @classmethod
    def strip_draft_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("landing_url_template")
    @classmethod
    def validate_landing_url(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("落地页地址必须以 http:// 或 https:// 开头")
        return value


class AccountUpdate(BaseModel):
    landing_url_template: str | None = Field(default=None, max_length=2000)

    @field_validator("landing_url_template", mode="before")
    @classmethod
    def strip_account_url(cls, value: str | None) -> str | None:
        if not isinstance(value, str):
            return value
        value = value.strip()
        return value or None

    @field_validator("landing_url_template")
    @classmethod
    def validate_account_url(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("落地页地址必须以 http:// 或 https:// 开头")
        return value


class AccountBatchSettings(BaseModel):
    selectors: list[str] = Field(default_factory=list, max_length=1000)
    account_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)
    account_type: AccountType | None = None
    operator_name: str | None = Field(default=None, max_length=30)
    page_type: Literal["科普账户", "软文账户"] | None = None
    promotion_page: Literal["科普基木鱼", "科普全文", "精华帖", "中医论坛", "中医秘方", "快瘦汤"] | None = None
    promotion_link: str | None = Field(default=None, max_length=2000)
    rebate_rate: Decimal | None = Field(default=None, ge=0, le=100)
    recharge_account: str | None = Field(default=None, max_length=200)
    lifecycle_stage: Literal["自动判断", "空账户", "测试期", "已淘汰", "应退款", "退户"] | None = None

    @field_validator("selectors", mode="before")
    @classmethod
    def normalize_selectors(cls, value: list[str]) -> list[str]:
        if not isinstance(value, list):
            return value
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

    @field_validator("account_ids", mode="before")
    @classmethod
    def normalize_account_ids(cls, value):
        return list(dict.fromkeys(value or []))

    @model_validator(mode="after")
    def validate_account_selection(self):
        if bool(self.selectors) == bool(self.account_ids):
            raise ValueError("selectors 和 account_ids 必须且只能提供一种账户选择方式")
        return self

    @field_validator("operator_name")
    @classmethod
    def validate_operator(cls, value: str | None) -> str | None:
        if value is not None and value not in {"王康", "王聪"}:
            raise ValueError("运营只能选择王康或王聪")
        return value

    @field_validator("page_type", "promotion_page", "promotion_link", "recharge_account", mode="before")
    @classmethod
    def strip_batch_text(cls, value: str | None) -> str | None:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator("promotion_link")
    @classmethod
    def validate_promotion_link(cls, value: str | None) -> str | None:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("推广链接必须以 http:// 或 https:// 开头")
        return value


class CampaignSettingsScopeRequest(BaseModel):
    account_type: AccountType | None = None
    page_type: Literal["科普账户", "软文账户"] | None = None
    account_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)

    @field_validator("account_ids", mode="before")
    @classmethod
    def normalize_campaign_account_ids(cls, value):
        return list(dict.fromkeys(value or []))


class HduofenCustomIdCreate(BaseModel):
    account: str = Field(min_length=1, max_length=200)
    custom_id: str = Field(min_length=1, max_length=120)

    @field_validator("account", "custom_id")
    @classmethod
    def strip_custom_id_fields(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("账户和自定义ID不能为空")
        return cleaned

    @field_validator("custom_id")
    @classmethod
    def validate_custom_id(cls, value: str) -> str:
        if any(character.isspace() or character in "?&#=" for character in value):
            raise ValueError("自定义ID不能包含空格或 ?、&、#、= 等URL分隔符")
        return value


class HduofenCustomIdBatchCreate(BaseModel):
    mappings: list[HduofenCustomIdCreate] = Field(min_length=1, max_length=500)


class CampaignOnlineWindow(BaseModel):
    weekDay: int = Field(ge=1, le=7)
    startHour: int = Field(ge=0, le=23)
    endHour: int = Field(ge=1, le=24)

    @model_validator(mode="after")
    def validate_window(self):
        if self.startHour >= self.endHour:
            raise ValueError("单个启用时段的结束时间必须晚于开始时间")
        return self


class CampaignBatchUpdateRequest(CampaignSettingsScopeRequest):
    action: Literal["schedule", "pause"]
    online_schedule: list[CampaignOnlineWindow] | None = Field(default=None, max_length=84)
    online_weekdays: list[int] = Field(
        default_factory=lambda: [1, 2, 3, 4, 5, 6, 7],
        min_length=1,
        max_length=7,
    )
    online_start_hour: int = Field(default=8, ge=0, le=23)
    online_end_hour: int = Field(default=24, ge=1, le=24)
    pause: bool | None = None

    @model_validator(mode="after")
    def validate_campaign_batch_update(self):
        if len(set(self.online_weekdays)) != len(self.online_weekdays):
            raise ValueError("上线星期不能重复")
        if any(day < 1 or day > 7 for day in self.online_weekdays):
            raise ValueError("上线星期必须是 1 到 7")
        if self.action == "schedule" and self.online_schedule is not None:
            if not self.online_schedule:
                raise ValueError("请至少选择一个启用时段")
            hours_by_day: dict[int, set[int]] = {}
            windows_by_day: dict[int, int] = {}
            for window in self.online_schedule:
                windows_by_day[window.weekDay] = windows_by_day.get(window.weekDay, 0) + 1
                if windows_by_day[window.weekDay] > 12:
                    raise ValueError("每天最多设置 12 个启用区间")
                occupied = hours_by_day.setdefault(window.weekDay, set())
                window_hours = set(range(window.startHour, window.endHour))
                if occupied & window_hours:
                    raise ValueError("同一天的启用时段不能重叠")
                occupied.update(window_hours)
        elif self.action == "schedule" and self.online_start_hour == self.online_end_hour:
            raise ValueError("上线开始和结束时间不能相同；结束早于开始时按次日计算")
        if self.action == "pause" and self.pause is None:
            raise ValueError("暂停/开启操作必须选择目标状态")
        return self


class PreferenceUpdate(BaseModel):
    value: dict[str, Any]


class KeywordTierRuleConfig(BaseModel):
    a_add_cost_max: Decimal = Field(default=Decimal("110"), gt=0, le=10000)
    b_next_add_cost_max: Decimal = Field(default=Decimal("100"), gt=0, le=10000)
    c_add_growth_factor: Decimal = Field(default=Decimal("1.2"), gt=1, le=10)
    c_projected_cost_max: Decimal = Field(default=Decimal("120"), gt=0, le=10000)
    empty_spend_min: Decimal = Field(default=Decimal("70"), gt=0, le=1000000)
    d_spend_min: Decimal = Field(default=Decimal("10"), ge=0, le=1000000)

    @model_validator(mode="after")
    def validate_spend_bands(self):
        if self.d_spend_min >= self.empty_spend_min:
            raise ValueError("D级最低消费必须小于空耗阈值")
        return self


class KeywordTierDryRunRequest(BaseModel):
    rules: KeywordTierRuleConfig | None = None


class StrategyDraftUpdate(BaseModel):
    config: dict[str, Any]
    expected_revision: int = Field(ge=1)


class StrategyPublishRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    evaluation_id: uuid.UUID


class StrategyRestoreDraftRequest(BaseModel):
    version_id: uuid.UUID
    expected_revision: int = Field(ge=1)


class KeywordBlacklistUpdate(BaseModel):
    blacklisted: bool
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class ManualKeywordBlacklistCreate(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=5000)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            keyword = value.strip()
            if not keyword:
                continue
            if len(keyword) > 500:
                raise ValueError("单个关键词不能超过500个字符")
            key = keyword.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(keyword)
        if not normalized:
            raise ValueError("请至少输入一个关键词")
        return normalized

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class NegativeKeywordBulkCreate(BaseModel):
    match_type: Literal["phrase", "exact"]
    keywords: list[str] = Field(min_length=1, max_length=5000)

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            keyword = str(value or "").strip()
            if not keyword:
                continue
            if len(keyword) > 500:
                raise ValueError("单个否词不能超过500个字符")
            key = keyword.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(keyword)
        if not normalized:
            raise ValueError("请至少输入一个否词")
        return normalized


class NegativeKeywordTemplateCopy(BaseModel):
    template_id: uuid.UUID
    fingerprint: str = Field(min_length=64, max_length=64)


class CreativeSegmentBulkCreate(BaseModel):
    segment_type: Literal["title", "description1", "description2"]
    contents: list[str] = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def normalize_and_validate_contents(self):
        normalized: list[str] = []
        seen: set[str] = set()
        errors: list[str] = []
        for index, value in enumerate(self.contents, start=1):
            try:
                content = validate_segment_content(self.segment_type, value)
            except ValueError as exc:
                preview = str(value or "").strip()[:18]
                errors.append(f"第{index}行“{preview}”：{exc}")
                continue
            key = content.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(content)
        if errors:
            visible = errors[:8]
            suffix = f"；另有{len(errors) - len(visible)}行未通过" if len(errors) > len(visible) else ""
            raise ValueError("；".join(visible) + suffix)
        if not normalized:
            raise ValueError("请至少输入一条创意")
        self.contents = normalized
        return self


class CreativeBlacklistUpdate(BaseModel):
    blacklisted: bool
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None


class CreativeCombinationPreviewRequest(BaseModel):
    seed: str = Field(default="preview", min_length=1, max_length=100)
    limit: int = Field(default=CREATIVE_COUNT_PER_ACCOUNT, ge=1, le=CREATIVE_COUNT_PER_ACCOUNT)

    @field_validator("seed", mode="before")
    @classmethod
    def normalize_seed(cls, value: str) -> str:
        return str(value or "preview").strip() or "preview"


class CreativeAssignmentBind(BaseModel):
    baidu_creative_id: int = Field(gt=0)
    creative_payload: dict[str, Any] = Field(default_factory=dict)


class OperationCreate(BaseModel):
    operation_type: str
    target_account_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=120)
    payload: dict[str, Any]


class OperationView(BaseModel):
    id: uuid.UUID
    operation_type: str
    target_account_id: int
    status: str
    requested_by: str
    confirmed_by: str | None
    preflight_result: dict[str, Any]
    created_at: datetime


class ImportPreview(BaseModel):
    filename: str
    sha256: str
    row_count: int
    valid_count: int
    invalid_count: int
    create_count: int
    update_count: int
    skip_count: int
    errors: list[dict[str, Any]]
    unit_chunks: list[dict[str, Any]]
    target_accounts: list[dict[str, Any]] = Field(default_factory=list)


class TaskView(BaseModel):
    id: uuid.UUID
    status: str
    current_node: str
    progress: int
    retry_count: int
    last_error: str | None
    result: dict[str, Any]
    heartbeat_at: datetime | None


class TieredKeywordInput(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    tier: KeywordTier


class KeywordPlanConfigInput(BaseModel):
    a_unit_count: int = Field(default=5, ge=1, le=20)
    unit_capacity: int = Field(default=5000, ge=1, le=5000)
    batch_number: int = Field(default=1, ge=1)


class AdBuildPlanRepeatItem(BaseModel):
    campaign_name: str = Field(min_length=1, max_length=200)
    repeat_count: int = Field(default=1, ge=1, le=20)


class AdBuildPlanSettingsUpdate(BaseModel):
    plans: list[AdBuildPlanRepeatItem] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_unique_campaign_names(self):
        names = [item.campaign_name.strip() for item in self.plans]
        if len(names) != len(set(names)):
            raise ValueError("计划名称不能重复")
        return self


class KeywordPlanRequest(BaseModel):
    project_id: uuid.UUID
    campaign_name: str = Field(min_length=1, max_length=200)
    account_ids: list[int] = Field(min_length=1)
    keywords: list[TieredKeywordInput] = Field(min_length=3)
    config: KeywordPlanConfigInput = Field(default_factory=KeywordPlanConfigInput)


class AdBuildPreviewRequest(BaseModel):
    project_id: uuid.UUID
    keyword_mode: Literal["preferred", "full"] = "preferred"
    selection_mode: Literal["specified_accounts", "specified_managers", "multi_subjects", "specified_subjects", "random"]
    account_selectors: list[str] = Field(default_factory=list, max_length=5000)
    manager_login_names: list[str] = Field(default_factory=list, max_length=500)
    subject_names: list[str] = Field(default_factory=list, max_length=500)
    quantity: int | None = Field(default=None, ge=1, le=10000)
    selection_seed: str = Field(default="default", min_length=1, max_length=80)
    execution_mode: Literal["immediate", "scheduled"] = "immediate"
    scheduled_at: datetime | None = None
    scheduled_dates: list[date] = Field(default_factory=list, max_length=366)
    scheduled_times: list[time] = Field(default_factory=list, max_length=24)
    schedule_unlimited: bool = False
    batch_size: int = Field(default=10, ge=1, le=1000)
    batch_interval_minutes: int = Field(default=60, ge=1, le=1440)
    project_bid: Decimal = Field(default=Decimal("258.88"), ge=Decimal("0.1"), le=Decimal("99999.99"), decimal_places=2)
    online_schedule_enabled: bool = False
    online_schedule: list[CampaignOnlineWindow] | None = Field(default=None, max_length=84)
    online_weekdays: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7], min_length=1, max_length=7)
    online_start_hour: int = Field(default=8, ge=0, le=23)
    online_end_hour: int = Field(default=24, ge=1, le=24)
    region_target: list[int] = Field(
        default_factory=lambda: list(MIGRATED_DEFAULT_REGION_TARGET),
        min_length=1,
        max_length=500,
    )
    geo_location_status: Literal[0, 1] = 1

    @field_validator("account_selectors", "manager_login_names", "subject_names", mode="after")
    @classmethod
    def clean_string_lists(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))

    @field_validator("selection_seed", mode="before")
    @classmethod
    def clean_seed(cls, value: str) -> str:
        return str(value or "default").strip() or "default"

    @field_validator("scheduled_dates", mode="after")
    @classmethod
    def clean_scheduled_dates(cls, values: list[date]) -> list[date]:
        return sorted(set(values))

    @field_validator("scheduled_times", mode="after")
    @classmethod
    def clean_scheduled_times(cls, values: list[time]) -> list[time]:
        if any(value.minute or value.second or value.microsecond for value in values):
            raise ValueError("执行时间仅支持整点")
        normalized = [value.replace(minute=0, second=0, microsecond=0, tzinfo=None) for value in values]
        return sorted(set(normalized))

    @field_validator("region_target", mode="after")
    @classmethod
    def clean_region_target(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("推广地域ID必须是正整数")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_mode_inputs(self):
        if self.selection_mode == "specified_accounts" and not self.account_selectors:
            raise ValueError("指定账户模式必须至少选择一个账户")
        if self.selection_mode == "specified_managers" and not self.manager_login_names:
            raise ValueError("指定管家模式必须至少选择一个账户管家")
        if self.selection_mode == "multi_subjects" and self.quantity is None:
            raise ValueError("当前模式必须填写新建数量")
        if self.selection_mode == "specified_subjects" and not self.subject_names:
            raise ValueError("指定主体模式必须选择至少一个账号主体")
        if self.execution_mode == "scheduled":
            uses_execution_nodes = bool(self.scheduled_dates or self.scheduled_times or self.schedule_unlimited)
            if uses_execution_nodes:
                if not self.scheduled_dates or not self.scheduled_times:
                    raise ValueError("定时新建必须选择执行日期和至少一个执行时间")
                if self.schedule_unlimited and len(self.scheduled_dates) != 1:
                    raise ValueError("不限日期模式只保留一个开始日期")
            else:
                if self.scheduled_at is None:
                    raise ValueError("定时新建必须选择首次执行日期和时间")
                if self.scheduled_at.tzinfo is None or self.scheduled_at.utcoffset() is None:
                    raise ValueError("定时时间必须包含时区")
        if len(set(self.online_weekdays)) != len(self.online_weekdays) or any(day < 1 or day > 7 for day in self.online_weekdays):
            raise ValueError("上线星期必须是 1 到 7 且不能重复")
        if self.online_schedule_enabled and self.online_schedule is not None:
            if not self.online_schedule:
                raise ValueError("请至少选择一个计划启用时段")
            hours_by_day: dict[int, set[int]] = {}
            windows_by_day: dict[int, int] = {}
            for window in self.online_schedule:
                windows_by_day[window.weekDay] = windows_by_day.get(window.weekDay, 0) + 1
                if windows_by_day[window.weekDay] > 12:
                    raise ValueError("每天最多设置 12 个启用区间")
                occupied = hours_by_day.setdefault(window.weekDay, set())
                window_hours = set(range(window.startHour, window.endHour))
                if occupied & window_hours:
                    raise ValueError("同一天的启用时段不能重叠")
                occupied.update(window_hours)
        elif self.online_schedule_enabled and self.online_start_hour == self.online_end_hour:
            raise ValueError("上线开始和结束时间不能相同；结束早于开始时按次日计算")
        return self


class AdBuildCreateRequest(AdBuildPreviewRequest):
    selected_account_ids: list[int] = Field(min_length=1, max_length=10000)
    selection_fingerprint: str = Field(min_length=64, max_length=64)
    material_fingerprint: str = Field(min_length=64, max_length=64)
    negative_keyword_fingerprint: str = Field(min_length=64, max_length=64)
    build_rule_version: str = Field(min_length=1, max_length=80)


class AdBuildAccessUpdate(BaseModel):
    can_build_ads: bool = True
    is_active: bool = True


PermissionLevel = Literal["hidden", "view", "manage"]


class ProjectMemberCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._@-]+$")
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(min_length=1, max_length=100)
    operator_name: str = Field(min_length=1, max_length=30)
    supervisor_id: uuid.UUID | None = None
    data_scope: Literal["self", "team", "project"] = "self"
    permissions: dict[str, PermissionLevel] = Field(default_factory=dict)

    @field_validator("username", "display_name", "operator_name", mode="before")
    @classmethod
    def strip_member_text(cls, value: str) -> str:
        return value.strip()


class ProjectMemberUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._@-]+$")
    password: str | None = Field(default=None, min_length=8, max_length=256)
    display_name: str = Field(min_length=1, max_length=100)
    operator_name: str = Field(min_length=1, max_length=30)
    supervisor_id: uuid.UUID | None = None
    data_scope: Literal["self", "team", "project"]
    permissions: dict[str, PermissionLevel]
    is_active: bool
    version: int = Field(ge=1)

    @field_validator("username", "display_name", "operator_name", mode="before")
    @classmethod
    def strip_updated_member_text(cls, value: str) -> str:
        return value.strip()
