# UI 全面整改本地验证记录

## 范围

- 仅验证本地前端与本地后端测试环境
- 未运行发布脚本；未连接线上服务器；未迁移数据库；未执行百度写入任务
- 当前项目地址使用 `/{projectCode}?page={pageCode}`；项目首页使用 `/`

## 已验证的工作台入口

| 页面或状态 | 验证方式 |
| --- | --- |
| 项目管理首页 | 路由、项目进入、新标签入口、无提醒入口、截图断言 |
| 账户管理 | 管家页签、账户页签、键盘切换、表头、截图断言 |
| 账户列表 | 指标列、计划展开、横向数据区、截图断言 |
| 自动搭建 | 四种账户选择、优选和全量模式、设置弹窗、截图断言 |
| 物料中心 | 年份、黑名单、项目内搜索、刷新、分页、截图断言 |
| 自动上线执行记录 | 逐账户节点、进度、分页、截图断言 |
| 数据报表 | 日期筛选、账户日报分页、截图断言 |
| 成员管理 | 三个成员、范围设置弹窗、本地身份切换入口、截图断言 |
| 自动策略 | 左侧规则列表、草稿、校验、试运行、发布、回退入口、截图断言 |
| 提醒 | 标题右侧入口、摘要、详情、全部已读 |

## 自动化结果

- 前端交互与视觉回归：51 项通过
- 前端类型检查：通过
- 前端生产构建：通过
- 后端测试：233 项通过

视觉基线位于 `frontend/e2e/local-refactor.spec.ts-snapshots`

## 新样式层

- `frontend/src/ui/tokens.ts`：跨页面语义令牌
- `frontend/src/ui/foundations.css`：字体、焦点、减少动效和基础重置
- `frontend/src/ui/components.css`：可复用的工具栏、数据面板和弹窗尺寸
- `frontend/src/components/AppShell.tsx`：项目首页与工作台共用的侧栏导航壳
- `frontend/src/components/PageHeader.tsx`：统一页面标题和标题右侧操作区
- `frontend/src/components/NotificationCenter.tsx`：标题右侧提醒摘要、详情和全部已读
- `frontend/src/features/accounts/feature.css`：账户概览、层级计划展开和账户状态
- `frontend/src/features/auto-launch/feature.css`：自动上线页签、账户选择、双栏工作区和执行区
- `frontend/src/features/reports/feature.css`：报表工具栏、横向数据表和数字对齐
- `frontend/src/features/reports/ReportsPage.tsx`：报表查询、筛选、导出与固定分页
- `frontend/src/features/members/MembersPage.tsx`：成员范围、权限设置与本地调试身份
- `frontend/src/features/projects/feature.css`：项目管理表与标准项目编辑弹窗

## 样式门禁

- 入口只加载令牌、基础层、公共组件层、设计系统层和功能层
- `styles.css` 与 `ecom-ui.css` 已移入 `frontend/src/legacy-archive`，不参与构建或运行
- 活动样式中的 `!important` 为 0
- 活动样式中的硬编码颜色为 0；颜色只定义在 `frontend/src/ui/tokens.ts`
- 顶部工具栏已从应用 DOM 移除；提醒位于项目页标题右侧
- 页面主标题只保留页面身份；说明、成功反馈和风险说明不再作为标题下方摘要占用页面空间
- 当前可访问页面不保留装饰性图标；仅搜索、日期与翻月等直接操作保留必要标识
- 不再保留旧自动化中心、监测中心、审计中心或旧系统设置页面的不可达实现

## 本轮验证结果

- Playwright 功能与视觉回归：51 项通过；包含项目管理、账户管理、账户列表、自动上线、物料中心、创意中心、执行记录、报表、成员管理、自动策略和提醒入口
- 项目工作台的九个一级工作区均已在 1280、1366、1440、1920 宽度完成视口快照断言；1280 宽度保持完整侧栏，小于 1280 才自动收起
- 前端类型检查与生产构建：通过
- 后端回归：233 项通过
- 未运行一键发布；未改动线上服务器、线上数据库、OAuth、Token 或百度端账户
