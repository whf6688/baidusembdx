import { expect, test } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

const shots = resolve(process.cwd(), '../docs/refactor/screenshots')
mkdirSync(shots, { recursive: true })

test.beforeEach(async ({ context }) => {
  const sessionToken = process.env.TEST_SESSION_TOKEN
  if (!sessionToken) return
  await context.addCookies([{
    name: 'search_console_session',
    value: sessionToken,
    url: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:8280',
    httpOnly: true,
    sameSite: 'Lax',
  }])
})

for (const width of [1366, 1440, 1920]) {
  test(`account workspace is usable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const remoteRequests: string[] = []
    page.on('request', request => {
      const url = new URL(request.url())
      if (!['localhost', '127.0.0.1'].includes(url.hostname)) remoteRequests.push(request.url())
    })
    await page.goto('/jfsem')
    await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible()
    await page.locator('.nav-item').filter({ hasText: '账户管理' }).click()
    await expect(page.getByRole('heading', { name: '账户管理' })).toBeVisible()
    await expect(page.getByRole('tablist', { name: '账户管家' })).toBeVisible()
    await expect(page.locator('.manager-management-table thead th')).toHaveText(['类型', '账户', '账户余额', '返点', '授权', '操作', '充值账户'])
    const managerTabs = page.locator('.manager-account-tabs [role="tab"]')
    expect(await managerTabs.count()).toBeGreaterThan(0)
    if (width === 1440) {
      await page.screenshot({ path: resolve(shots, 'account-managers-1440.png'), fullPage: true })
      await expect(page).toHaveScreenshot('account-management-1440.png', { fullPage: true, animations: 'disabled', maxDiffPixels: 120 })
    }
    if (await managerTabs.count() > 1) {
      await managerTabs.first().press('ArrowRight')
      await expect(managerTabs.nth(1)).toHaveAttribute('aria-selected', 'true')
      await managerTabs.nth(1).click()
      await expect(page.locator('.account-list-table')).toBeVisible()
      await expect(page.locator('.legacy-account-table')).toHaveCount(0)
    }
    await page.screenshot({ path: resolve(shots, `account-workspace-${width}.png`), fullPage: true })
    expect(remoteRequests).toEqual([])
  })
}

for (const width of [1280, 1366, 1440, 1920]) {
  test(`account list keeps the complete desktop workbench at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/jfsem?page=account-list')
    await expect(page.locator('.sidebar')).toHaveCSS('width', '168px')
    await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible()
    await expect(page.locator('.nav-label')).toHaveText(['项目与账户', '系统设置'])
    await expect(page.locator('.account-management-table-wrap')).toBeVisible()
    await expect(page.getByLabel('账户列表分页')).toBeVisible()
    const tableWidth = await page.locator('.account-page-operations .account-management-table-wrap').evaluate(element => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      overflowX: getComputedStyle(element).overflowX,
    }))
    expect(tableWidth.scrollWidth).toBeLessThanOrEqual(tableWidth.clientWidth + 1)
    expect(tableWidth.overflowX).toBe('hidden')
    const overviewWidth = await page.locator('.account-list-overview').evaluate(element => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
      overflowX: getComputedStyle(element).overflowX,
    }))
    expect(overviewWidth.scrollWidth).toBeLessThanOrEqual(overviewWidth.clientWidth + 1)
    expect(overviewWidth.overflowX).toBe('hidden')
    await expect(page).toHaveScreenshot(`account-list-${width}.png`, { fullPage: true, animations: 'disabled' })
  })
}

const desktopVisualRoutes = [
  ['accounts', '账户管理'],
  ['account-list', '账户列表'],
  ['delivery', '自动上线'],
  ['materials', '自动上线'],
  ['creatives', '自动上线'],
  ['records', '自动上线'],
  ['reports', '数据报表'],
  ['members', '成员管理'],
  ['strategies', '自动策略'],
] as const

for (const width of [1280, 1366, 1440, 1920]) {
  for (const [view, heading] of desktopVisualRoutes) {
    test(`desktop visual ${view} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      if (view === 'materials') {
        await page.route('**/api/v1/projects/*/material-keywords*', route => route.fulfill({ json: { status: 'ok', data: { items: [], total: 0, page: 1, page_size: 20, selected_year: 2026, available_years: [2026] } } }))
      }
      await page.goto(`/jfsem?page=${view}`)
      await expect(page.getByRole('heading', { name: heading }).first()).toBeVisible()
      await expect(page.locator('.topbar')).toHaveCount(0)
      await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible()
      await expect(page).toHaveScreenshot(`desktop-${view}-${width}.png`, {
        fullPage: false,
        animations: 'disabled',
        // 管家余额由后台实时读取；只容忍该动态数字的少量像素变化，其他页面仍要求像素级一致
        maxDiffPixels: view === 'accounts' ? 120 : 0,
      })
    })
  }
}

test('strategy workflow uses the toolbar publishing flow', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/jfsem')
  await page.locator('.nav-item').filter({ hasText: '自动策略' }).click()
  await expect(page.locator('.strategy-action-navigation[aria-label="自动策略规则"]')).toBeVisible()
  await expect(page.locator('.strategy-action-navigation button')).toHaveCount(5)
  await expect(page.getByRole('button', { name: '编辑规则' })).toBeVisible()
  await expect(page.getByRole('button', { name: '校验参数' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '保存草稿' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '试运行' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '发布', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '发布规则' })).toBeVisible()
  const strategyRule = (name: string) => page.locator('.strategy-action-navigation button').filter({ hasText: name }).first()
  await strategyRule('预算追加').click()
  await expect(strategyRule('预算追加')).toHaveAttribute('aria-current', 'page')
  await strategyRule('预算重置').click()
  await page.screenshot({ path: resolve(shots, 'strategy-center-1440.png'), fullPage: true })
  await expect(page).toHaveScreenshot('strategy-center-1440.png', { fullPage: true, animations: 'disabled' })
  await strategyRule('预算追加').click()
  await page.getByRole('tab', { name: '执行记录', exact: true }).click()
  await expect(page.locator('.strategy-scoped-records')).toBeVisible()
  await expect(page.locator('.strategy-scoped-records .execution-action-tabs')).toHaveCount(0)
  const headingControls = page.locator('.strategy-scoped-records .execution-heading-controls')
  await expect(headingControls.getByRole('group', { name: '执行状态筛选' })).toBeVisible()
  await expect(headingControls.getByRole('button', { name: '刷新状态' })).toBeVisible()
  await expect(headingControls.getByRole('searchbox', { name: '搜索执行记录' })).toBeVisible()
  const refreshBox = await headingControls.getByRole('button', { name: '刷新状态' }).boundingBox()
  const searchBox = await headingControls.getByRole('searchbox', { name: '搜索执行记录' }).boundingBox()
  expect(refreshBox).not.toBeNull()
  expect(searchBox).not.toBeNull()
  expect(searchBox!.x).toBeGreaterThan(refreshBox!.x)
  await page.screenshot({ path: resolve(shots, 'strategy-records-1440.png'), fullPage: true })
  await page.getByRole('tab', { name: '预算变更明细', exact: true }).click()
  await expect(page.locator('.strategy-results-only')).toBeVisible()
  await expect(page.locator('.strategy-results-only .budget-rule-panel')).toBeHidden()
  await strategyRule('实时闭环').click()
  await expect(page.locator('.loop-check-panel')).toBeVisible()
})

test('realtime closure uses the shared automatic-strategy rule layout', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/jfsem?page=strategies')
  await page.getByRole('button', { name: '实时闭环' }).click()

  const workspace = page.getByRole('region', { name: '实时闭环工作区' })
  await expect(workspace.getByRole('tab', { name: '规则设置' })).toHaveAttribute('aria-selected', 'true')
  await expect(workspace.getByRole('tab', { name: '闭环总览' })).toHaveCount(0)
  await expect(workspace.getByRole('combobox', { name: '执行模式' })).toHaveValue('自动判定')
  await expect(workspace.getByRole('combobox', { name: '执行周期' })).toHaveValue('实时闭环')

  const settings = workspace.getByRole('region', { name: '实时闭环规则设置' })
  await expect(settings.getByText('项目数据刷新', { exact: true })).toBeVisible()
  await expect(settings.getByText('运行与安全状态', { exact: true })).toHaveCount(0)
  await expect(settings.getByText('闭环运行状态', { exact: true })).toBeVisible()
  const refreshTitle = await settings.getByText('项目数据刷新', { exact: true }).boundingBox()
  const refreshSummary = await settings.getByText('该周期覆盖账户、百度报表、好多粉、预算、创意和归因等闭环数据，不属于某一个报表页面', { exact: true }).boundingBox()
  expect(refreshTitle).not.toBeNull()
  expect(refreshSummary).not.toBeNull()
  expect(Math.abs(refreshTitle!.y - refreshSummary!.y)).toBeLessThanOrEqual(4)
  const blocks = settings.locator(':scope > section')
  await expect(blocks).toHaveCount(3)
  const first = await blocks.nth(0).boundingBox()
  const second = await blocks.nth(1).boundingBox()
  const third = await blocks.nth(2).boundingBox()
  expect(first).not.toBeNull()
  expect(second).not.toBeNull()
  expect(third).not.toBeNull()
  expect(second!.y).toBeGreaterThan(first!.y + first!.height)
  expect(third!.y).toBeGreaterThan(second!.y + second!.height)
  const overflow = await settings.evaluate(element => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }))
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1)
  await page.screenshot({ path: resolve(shots, 'strategy-realtime-closure-1440.png'), fullPage: true })
  await expect(page).toHaveScreenshot('strategy-realtime-closure-1440.png', { fullPage: true, animations: 'disabled' })
})

test('execution record controls stay right aligned with search last', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/jfsem')
  await page.locator('.nav-item').filter({ hasText: '自动策略' }).click()
  await page.locator('.strategy-action-navigation button').filter({ hasText: '预算追加' }).first().click()
  await page.getByRole('tab', { name: '执行记录', exact: true }).click()
  const controls = page.locator('.strategy-scoped-records .execution-heading-controls')
  const filters = controls.getByRole('group', { name: '执行状态筛选' })
  const refresh = controls.getByRole('button', { name: '刷新状态' })
  const search = controls.getByRole('searchbox', { name: '搜索执行记录' })
  await expect(filters).toBeVisible()
  await expect(refresh).toBeVisible()
  await expect(search).toBeVisible()
  const filtersBox = await filters.boundingBox()
  const refreshBox = await refresh.boundingBox()
  const searchBox = await search.boundingBox()
  expect(filtersBox).not.toBeNull()
  expect(refreshBox).not.toBeNull()
  expect(searchBox).not.toBeNull()
  expect(refreshBox!.x).toBeGreaterThan(filtersBox!.x)
  expect(searchBox!.x).toBeGreaterThan(refreshBox!.x)
})

test('delivery account selection keeps four card choices', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/jfsem')
  await expect(page.locator('.nav-item').filter({ hasText: '物料中心' })).toHaveCount(0)
  await expect(page.locator('.nav-item').filter({ hasText: '创意中心' })).toHaveCount(0)
  await expect(page.locator('.nav-item').filter({ hasText: '投放搭建' })).toHaveCount(0)
  await page.locator('.nav-item').filter({ hasText: '自动上线' }).click()
  await expect(page.getByRole('heading', { name: '自动上线' })).toBeVisible()
  await expect(page.getByRole('tablist', { name: '自动上线功能' })).toBeVisible()
  await expect(page.getByRole('tablist', { name: '自动上线功能' }).getByRole('tab')).toHaveCount(4)
  await expect(page.getByRole('tab', { name: /自动搭建/ })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('tab', { name: /自动搭建/ }).press('ArrowRight')
  await expect(page.getByRole('tab', { name: /物料中心/ })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('tab', { name: /自动搭建/ }).click()
  await expect(page.getByRole('button', { name: /优选模式/ })).toHaveClass(/active/)
  await page.getByRole('button', { name: /全量模式/ }).click()
  await expect(page.getByRole('button', { name: /全量模式/ })).toHaveClass(/active/)
  await page.getByRole('tab', { name: /物料中心/ }).click()
  await expect(page.getByRole('tab', { name: /物料中心/ })).toHaveAttribute('aria-selected', 'true')
  await expect(page).toHaveURL(/page=materials/)
  await page.getByRole('button', { name: '添加否词', exact: true }).click()
  const addNegativeKeywordDialog = page.getByRole('dialog', { name: '添加否词' })
  await addNegativeKeywordDialog.getByRole('tab', { name: /短语否定关键词/ }).press('ArrowRight')
  await expect(addNegativeKeywordDialog.getByRole('tab', { name: /精确否定关键词/ })).toHaveAttribute('aria-selected', 'true')
  await expect(addNegativeKeywordDialog.locator('.negative-keyword-list-section')).toHaveCount(0)
  await addNegativeKeywordDialog.getByRole('button', { name: '取消' }).click()
  await page.getByRole('button', { name: '否词名单', exact: true }).click()
  const negativeKeywordListDialog = page.getByRole('dialog', { name: '否词名单' })
  await expect(negativeKeywordListDialog.locator('.negative-keyword-list-section')).toBeVisible()
  await expect(negativeKeywordListDialog.locator('textarea')).toHaveCount(0)
  await negativeKeywordListDialog.getByRole('button', { name: '关闭', exact: true }).last().click()
  await page.reload()
  await expect(page.getByRole('tab', { name: /物料中心/ })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('tab', { name: /创意中心/ }).click()
  await expect(page.getByLabel('创意统计')).toBeVisible()
  await expect(page.getByRole('button', { name: '同步审核状态' })).toBeVisible()
  await expect(page.getByRole('button', { name: '随机预览50组' })).toHaveCount(0)
  await page.getByRole('tab', { name: /自动搭建/ }).click()
  await expect(page.getByRole('tab', { name: /自动搭建/ })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByText('选择账户方式')).toBeVisible()
  const modeCards = page.locator('.ad-mode-list > button')
  await expect(modeCards).toHaveCount(4)
  await expect(page.getByText('指定账户新建', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('多主体新建', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('指定主体新建', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('随机新建', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: /指定账户新建/ }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('button', { name: '确定' })).toBeVisible()
  await expect(page.getByRole('button', { name: '取消' })).toBeVisible()
  await page.screenshot({ path: resolve(shots, 'delivery-account-mode-dialog-1440.png'), fullPage: true })
  await expect(page).toHaveScreenshot('delivery-account-mode-dialog-1440.png', { fullPage: true, animations: 'disabled' })
})

test('automatic launch records show one account per row and every workflow node', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  let cancelRequested = false
  const nodeDefinitions = [
    ['material_preflight', '物料预检'], ['account_settings', '账户设置'], ['campaigns', '计划'],
    ['adgroups', '单元'], ['ocpc', 'oCPC'], ['keywords', '关键词'], ['audiences', '人群'],
    ['creatives', '创意'], ['final_readback', '回读验证'],
  ]
  const failedNodes = nodeDefinitions.map(([key, label], index) => ({
    key, label, status: index < 3 ? 'succeeded' : index === 3 ? 'failed' : 'pending',
    message: index === 3 ? '单元创建失败：接口超时' : null,
  }))
  const pendingNodes = nodeDefinitions.map(([key, label]) => ({
    key, label, status: 'pending',
  }))
  await page.route('**/api/v1/projects/*/ad-builds', route => route.fulfill({ json: { status: 'ok', data: [{
    id: 'job-12345678', keyword_mode: 'full', selection_mode: 'specified_accounts', execution_mode: 'immediate', status: 'running',
    first_scheduled_at: '2026-09-14T00:00:00Z', batch_size: 1, batch_interval_minutes: 0,
    account_count: 2, batch_count: 1, workflow_version: 'v1', created_by: 'admin', created_at: '2026-09-14T00:00:00Z',
    batches: [{ id: 'batch-1', number: 1, scheduled_at: '2099-09-14T00:00:00Z', status: 'running', account_count: 2, accounts: [{
      account_id: 86459649, account_name: '异常测试账户', account_subject: '测试主体', manager_login_name: '测试管家', task_id: 'failed-task-1',
      status: 'failed', current_node: 'adgroups', progress: 35, last_error: '单元创建失败：接口超时', result_summary: '单元创建失败',
      updated_at: '2026-09-14T00:12:00Z', nodes: failedNodes,
    }, {
      account_id: 86459650, account_name: '待执行账户', account_subject: '测试主体', manager_login_name: '测试管家', task_id: 'pending-task-1',
      status: 'pending', current_node: 'queued', progress: 0, result_summary: '等待执行',
      updated_at: '2026-09-14T00:00:00Z', nodes: pendingNodes,
    }] }],
  }] } }))
  await page.route('**/api/v1/projects/*/tasks', route => route.fulfill({ json: { status: 'ok', data: [] } }))
  await page.route('**/api/v1/projects/*/tasks/pending-task-1/cancel', route => {
    cancelRequested = true
    return route.fulfill({ json: { status: 'ok', data: { id: 'pending-task-1', status: 'cancelled' } } })
  })
  await page.goto('/jfsem')
  await page.locator('.nav-item').filter({ hasText: '自动上线' }).click()
  await page.getByRole('tab', { name: /执行记录/ }).click()
  await expect(page.getByRole('button', { name: '全部 2' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: '进行中 0' })).toBeVisible()
  await expect(page.getByRole('button', { name: '等待 1' })).toBeVisible()
  await expect(page.getByRole('button', { name: '已完成 0' })).toBeVisible()
  await expect(page.getByRole('button', { name: '异常 1' })).toBeVisible()
  await expect(page.getByRole('button', { name: '刷新状态' })).toBeVisible()
  await expect(page.locator('.ad-build-record-table tbody tr')).toHaveCount(2)
  await expect(page.locator('.ad-build-record-table thead th')).toHaveText([
    '任务ID', '账户名称', '账户ID', '状态', '预定时间', '物料预检', '账户设置', '计划', '单元',
    'oCPC', '关键词', '人群', '创意', '回读验证', '执行结果', '执行完毕时间', '操作',
  ])
  await page.getByRole('button', { name: '已完成 0' }).click()
  await expect(page.locator('.ad-build-record-table tbody tr')).toHaveCount(1)
  await expect(page.locator('.ad-build-empty-cell')).toBeVisible()
  await page.getByRole('button', { name: '全部 2' }).click()
  await expect(page.locator('.ad-build-record-table')).toContainText('异常测试账户')
  await expect(page.locator('.ad-build-record-table tbody tr').first().locator('.execution-result-cell')).toHaveText('单元创建失败：接口超时')
  await expect(page.locator('.ad-build-record-table tbody tr').first().locator('.node-result-cell')).not.toContainText('接口超时')
  await expect(page.locator('.ad-build-record-table tbody tr').nth(1).locator('.status-cell')).toHaveText('等待')
  await expect(page.getByRole('button', { name: '取消任务' })).toBeVisible()
  await expect(page.getByRole('button', { name: '安全续跑' })).toBeVisible()
  await page.getByRole('button', { name: '取消任务' }).click()
  await expect(page.getByRole('dialog', { name: '取消任务' })).toBeVisible()
  await page.getByRole('button', { name: '确认取消' }).click()
  await expect.poll(() => cancelRequested).toBe(true)
  await expect(page.getByRole('dialog', { name: '取消任务' })).toHaveCount(0)
  await expect(page.getByLabel('自动上线执行记录分页')).toBeVisible()
  await expect(page.getByLabel('自动上线执行记录分页').getByLabel('每页条数')).toHaveValue('20')
  for (const label of ['物料预检', '账户设置', '计划', '单元', 'oCPC', '关键词', '人群', '创意', '回读验证']) {
    await expect(page.locator('.ad-build-record-table')).toContainText(label)
  }
  await expect(page.locator('.sidebar-session')).toBeVisible()
  await page.locator('.ad-build-record-table-wrap').evaluate(element => { element.scrollLeft = 0 })
  await page.screenshot({ path: resolve(shots, 'auto-launch-records-1440.png'), fullPage: true })
  await expect(page).toHaveScreenshot('auto-launch-records-1440.png', { fullPage: true, animations: 'disabled' })
})

test('materials, creatives and reminder detail keep the unified workspace structure', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.route('**/notifications**', route => route.fulfill({ json: { status: 'ok', data: {
    unread_count: 1,
    items: [{
      id: 'visual-notification-1', category: 'low_balance', severity: 'warning', title: '账户余额提醒',
      summary: '测试钱柜账户余额不足', body: '请为测试钱柜账户安排充值', payload: { cash_account: '测试钱柜账户', spend_7d: '800.00', adds_7d: 8, add_cost_7d: '100.00' },
      occurred_at: '2026-09-14T08:00:00Z', created_at: '2026-09-14T08:00:00Z', is_read: false,
    }],
  } } }))
  const materialRequests: string[] = []
  page.on('request', request => {
    if (request.url().includes('/material-keywords')) materialRequests.push(request.url())
  })
  await page.goto('/jfsem?page=materials')
  await expect(page.getByRole('heading', { name: '物料中心' })).toBeVisible()
  await expect(page.getByRole('tab', { name: /物料中心/ })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByPlaceholder('搜索计划或关键词')).toBeVisible()
  await expect(page.getByRole('button', { name: '刷新' }).last()).toBeVisible()
  await expect(page.getByLabel('物料分页')).toBeVisible()
  await expect(page).toHaveScreenshot('materials-1440.png', { fullPage: true, animations: 'disabled' })
  await page.getByPlaceholder('搜索计划或关键词').fill('测试关键词')
  await page.getByPlaceholder('搜索计划或关键词').press('Enter')
  await expect.poll(() => materialRequests.some(url => url.includes('search=%E6%B5%8B%E8%AF%95%E5%85%B3%E9%94%AE%E8%AF%8D'))).toBe(true)
  await page.getByRole('tab', { name: /创意中心/ }).click()
  await expect(page.getByLabel('创意统计')).toBeVisible()
  await expect(page.getByRole('button', { name: '同步审核状态' })).toBeVisible()
  await expect(page).toHaveScreenshot('creatives-1440.png', { fullPage: false, animations: 'disabled' })
  await page.getByRole('button', { name: /提醒/ }).click()
  await expect(page.locator('.notification-popover')).toBeVisible()
  await expect(page.getByRole('button', { name: '全部已读' })).toBeVisible()
  await expect(page).toHaveScreenshot('reminder-popover-1440.png', { fullPage: false, animations: 'disabled' })
})

test('project management is the root entry and project workspaces keep their own URL', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await expect(page.locator('.nav-label')).toHaveText(['项目与账户', '系统设置'])
  await expect(page.locator('.nav-item')).toHaveText(['账户管理', '账户列表', '自动上线', '数据报表', '自动策略', '成员管理'])
  await expect(page.locator('.nav-item.active')).toHaveCount(0)
  await expect(page.locator('.topbar')).toHaveCount(0)
  await expect(page.locator('.notification-trigger')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '首页' })).toBeVisible()
  const runtimeWidget = page.getByRole('region', { name: '运行与安全状态' })
  await expect(runtimeWidget.getByText('后台常驻列表', { exact: true })).toBeVisible()
  await expect(runtimeWidget.locator('.runtime-job-main strong')).toHaveText(['初始预算复位', '实时闭环', '账户余额/状态', '历史消耗补齐'])
  await expect(runtimeWidget.getByRole('button', { name: '刷新', exact: true })).toHaveCount(4)
  await expect(page.locator('.project-widget-table-row')).toHaveCount(1)
  await expect(page.locator('.project-widget-table-row').first()).toContainText('jfsem')
  await expect(page.locator('.project-widget-table-head > span')).toHaveText(['项目名称', '项目编码', '账户管家', '推广账户', '状态', '操作'])
  await expect(page.locator('.project-editor')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '新建项目' })).not.toHaveCSS('background-color', 'rgb(9, 105, 218)')
  const enterProject = page.getByRole('link', { name: '进入项目' }).first()
  const openInNewTab = page.getByRole('link', { name: '新标签打开' }).first()
  await expect(enterProject).toHaveAttribute('href', '/jfsem?page=account-list')
  await expect(openInNewTab).toHaveAttribute('href', '/jfsem?page=account-list')
  await expect(openInNewTab).toHaveAttribute('target', '_blank')
  await expect(page.locator('.project-row-actions .fui-Button')).toHaveCount(4)
  const projectActionBackgrounds = await page.locator('.project-row-actions .fui-Button').evaluateAll(buttons => buttons.map(button => getComputedStyle(button).backgroundColor))
  expect(projectActionBackgrounds).not.toContain('rgb(9, 105, 218)')
  const homeColumns = await page.locator('.home-dashboard-grid').evaluate(element => getComputedStyle(element).gridTemplateColumns.split(' ').length)
  expect(homeColumns).toBe(4)
  const gridWidth = await page.locator('.home-dashboard-grid').evaluate(element => element.getBoundingClientRect().width)
  const widgetWidth = await page.locator('.home-dashboard-widget').first().evaluate(element => element.getBoundingClientRect().width)
  const runtimeWidgetWidth = await runtimeWidget.evaluate(element => element.getBoundingClientRect().width)
  const codeSyncWidgetWidth = await page.getByRole('region', { name: '代码同步' }).evaluate(element => element.getBoundingClientRect().width)
  expect(widgetWidth).toBeGreaterThan(gridWidth * 0.49)
  expect(widgetWidth).toBeLessThan(gridWidth * 0.52)
  expect(runtimeWidgetWidth).toBeGreaterThan(gridWidth * 0.23)
  expect(runtimeWidgetWidth).toBeLessThan(gridWidth * 0.26)
  expect(codeSyncWidgetWidth).toBeGreaterThan(gridWidth * 0.23)
  expect(codeSyncWidgetWidth).toBeLessThan(gridWidth * 0.26)
  const balancedColumnWidths = await page.locator('.project-widget-table-head > span').evaluateAll(items => items.map(item => item.getBoundingClientRect().width))
  expect(balancedColumnWidths[0]).toBeGreaterThan(balancedColumnWidths[4])
  expect(balancedColumnWidths[5]).toBeGreaterThan(balancedColumnWidths[2])
  const widgetTitleBaseline = await page.getByRole('heading', { name: '项目管理' }).evaluate(element => element.getBoundingClientRect().top)
  const widgetDescriptionBaseline = await page.locator('.project-directory .home-dashboard-widget-head p').evaluate(element => element.getBoundingClientRect().top)
  expect(Math.abs(widgetTitleBaseline - widgetDescriptionBaseline)).toBeLessThanOrEqual(4)
  const projectItem = page.locator('.project-widget-table-row').first()
  await projectItem.hover()
  await expect(projectItem).toHaveCSS('background-color', 'rgb(221, 244, 255)')
  await page.getByRole('heading', { name: '首页' }).hover()
  await expect(projectItem).toHaveCSS('background-color', 'rgb(255, 255, 255)')
  const actionButtonTops = await page.locator('.project-row-actions .fui-Button').evaluateAll(buttons => buttons.map(button => button.getBoundingClientRect().top))
  expect(Math.max(...actionButtonTops) - Math.min(...actionButtonTops)).toBeLessThanOrEqual(1)
  const pagerBox = await page.getByLabel('项目管理分页').boundingBox()
  expect(pagerBox).not.toBeNull()
  expect(Math.abs((pagerBox?.y || 0) + (pagerBox?.height || 0) - 900)).toBeLessThanOrEqual(1)
  await expect(page.getByLabel('每页条数')).toBeVisible()
  await page.screenshot({ path: resolve(shots, 'project-management-1440.png'), fullPage: true })
  await expect(page).toHaveScreenshot('project-management-1440.png', { fullPage: true, animations: 'disabled' })
  await enterProject.click()
  await expect(page).toHaveURL(/\/jfsem\?page=account-list/)
  await expect(page.locator('.topbar')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /提醒/ })).toBeVisible()
  await expect(page.locator('.topbar-project-tabs')).toHaveCount(0)
  await expect(page.locator('.nav-label')).toHaveText(['项目与账户', '系统设置'])
  await expect(page.locator('.nav-item').filter({ hasText: '执行记录' })).toHaveCount(0)
  const settingsGroup = page.locator('.nav-group').filter({ has: page.locator('.nav-label', { hasText: '系统设置' }) })
  await expect(settingsGroup.locator('.nav-item')).toHaveText(['自动策略', '成员管理'])
  await expect(page.locator('.nav-item').filter({ hasText: '自动策略' })).toHaveCount(1)
  await expect(page.locator('.brand-mark')).toHaveText('百')
  await expect(page.locator('.sidebar')).toHaveCSS('width', '168px')
  await expect(page.getByRole('button', { name: /收起|展开/ })).toHaveCount(0)
  await page.locator('.nav-item').filter({ hasText: '成员管理' }).click()
  await expect(page.getByRole('heading', { name: '成员管理' })).toBeVisible()
  await expect(page.locator('.member-table-head')).toContainText('自动搭建范围')
  await expect(page.locator('.member-table-row')).toHaveCount(3)
  await expect(page.locator('.member-security-note')).toHaveCount(0)
  await expect(page).toHaveURL(/page=members/)
  await page.reload()
  await expect(page.getByRole('heading', { name: '成员管理' })).toBeVisible()
  await expect(page.locator('.nav-item').filter({ hasText: '成员管理' })).toHaveClass(/active/)
  await page.locator('.member-table-row').filter({ hasText: '王康' }).getByRole('button', { name: '设置' }).click()
  await expect(page.getByRole('dialog')).toContainText('允许自动搭建')
  await expect(page.getByRole('dialog')).toContainText('仍可登录并使用其他功能')
  await page.getByRole('dialog').getByRole('button', { name: '取消' }).click()
  await page.screenshot({ path: resolve(shots, 'member-management-1440.png'), fullPage: true })
  await expect(page).toHaveScreenshot('member-management-1440.png', { fullPage: true, animations: 'disabled' })
  await page.locator('.nav-item').filter({ hasText: '自动策略' }).click()
  await expect(page.locator('.strategy-hub-tabs button')).toHaveCount(4)
  await page.getByRole('tab', { name: /项目刷新/ }).click()
  await expect(page.getByText(/覆盖账户、百度报表、好多粉、预算、创意和归因/)).toBeVisible()
  await expect(page).toHaveURL(/page=strategies&section=refresh/)
  await page.reload()
  await expect(page.getByText(/覆盖账户、百度报表、好多粉、预算、创意和归因/)).toBeVisible()
  await page.screenshot({ path: resolve(shots, 'strategy-project-refresh-1440.png'), fullPage: true })
})

test('each automatic strategy shows only its own execution records', async ({ page }) => {
  const records = [
    ['budget_reset_automation', '重置专属账户'],
    ['budget_append_automation', '追加专属账户'],
    ['account_elimination_cycle', '淘汰专属账户'],
  ].map(([task_type, account_name], index) => ({
    id: `scope-task-${index}`, task_type, account_name, account_id: 12300 + index,
    status: 'succeeded', current_node: 'completed', progress: 100, retry_count: 0,
    created_at: '2026-09-14T00:00:00Z', updated_at: '2026-09-14T00:01:00Z',
  }))
  await page.route('**/api/v1/projects/*/tasks', route => route.fulfill({ json: { status: 'ok', data: records } }))
  await page.goto('/jfsem')
  await page.locator('.nav-item').filter({ hasText: '自动策略' }).click()
  for (const [label, account] of [['预算重置', '重置专属账户'], ['预算追加', '追加专属账户'], ['账户淘汰', '淘汰专属账户']]) {
    await page.locator('.strategy-action-navigation button').filter({ hasText: label }).first().click()
    await page.getByRole('tab', { name: '执行记录', exact: true }).click()
    const table = page.locator('.strategy-scoped-records .execution-records-table')
    await expect(table).toContainText(account)
    for (const other of records.filter(record => record.account_name !== account)) await expect(table).not.toContainText(other.account_name)
  }
})

test('report page keeps its existing data functions in the unified shell', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/jfsem?page=reports')
  await expect(page.locator('.nav-item').filter({ hasText: '数据报表' })).toHaveClass(/active/)
  await expect(page.getByText('今日', { exact: true }).first()).toBeVisible()
  await expect(page.locator('.report-overview')).toHaveCount(0)
  await expect(page.locator('.report-filter-bar .report-page-type-filter')).toHaveCount(2)
  await expect(page.getByLabel('账户日报分页')).toBeVisible()
  await expect(page.getByLabel('账户日报分页').getByLabel('每页条数')).toHaveValue('20')
  await page.screenshot({ path: resolve(shots, 'reports-1440.png'), fullPage: true })
  await expect(page).toHaveScreenshot('reports-1440.png', { fullPage: true, animations: 'disabled' })
})

for (const width of [600, 1280]) {
  test(`date range popover stays usable inside the viewport at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/jfsem?page=account-list')
    const trigger = page.getByRole('button', { name: /日期 \d{4}\/\d{2}\/\d{2} ~ \d{4}\/\d{2}\/\d{2}/ })
    await trigger.click()
    const dialog = page.getByRole('dialog', { name: '选择日期范围' })
    await expect(dialog).toBeVisible()
    const box = await dialog.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.x).toBeGreaterThanOrEqual(0)
    expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    await expect(dialog.locator('.date-calendar-month:visible')).toHaveCount(width <= 720 ? 1 : 2)
    await expect(page).toHaveScreenshot(`date-range-open-${width}.png`, { animations: 'disabled' })
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
    await expect(trigger).toBeFocused()
  })
}

test('scheduled delivery uses time controls while strategies use execution cycles', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/jfsem?page=delivery')
  await page.getByRole('button', { name: /定时新建 在选定日期/ }).click()
  await expect(page.locator('.date-input-control input[type="date"]')).toHaveCount(1)
  await expect(page.locator('.schedule-hour-grid button')).toHaveCount(24)
  await expect(page.locator('.schedule-hour-grid button.selected')).toHaveText(['9点', '15点', '19点'])
  await page.getByRole('button', { name: '10点', exact: true }).click()
  await expect(page.getByRole('button', { name: '10点', exact: true })).toHaveClass(/selected/)
  await expect(page.locator('.execution-panel')).toHaveScreenshot('scheduled-delivery-time-controls-1440.png', { animations: 'disabled' })

  await page.goto('/jfsem?page=strategies')
  await page.locator('.strategy-action-navigation button').filter({ hasText: '预算重置' }).first().click()
  await expect(page.getByRole('combobox', { name: '执行周期' })).toHaveValue('每日执行')
  await expect(page.getByText('执行时间', { exact: true })).toHaveCount(0)
  await expect(page.locator('.strategy-workspace')).toHaveScreenshot('strategy-time-control-1440.png', { animations: 'disabled' })
})

test('account list uses the compact account columns and expands cached campaigns locally', async ({ page }) => {
  const remoteRequests: string[] = []
  page.on('request', request => {
    const url = new URL(request.url())
    if (!['localhost', '127.0.0.1'].includes(url.hostname)) remoteRequests.push(request.url())
  })
  await page.setViewportSize({ width: 1920, height: 900 })
  await page.goto('/jfsem')
  await page.locator('.nav-item').filter({ hasText: '账户列表' }).click()
  await expect(page.getByRole('heading', { name: '账户列表' })).toBeVisible()
  await expect(page.getByText('账户状态、生命周期与投放数据')).toBeVisible()
  const headers = page.locator('.account-list-table > thead th')
  await expect(headers).toHaveText(['', '状态', '生命周期', '运营', '账户管家', '账户类型', '页面类型', '账户名称', '账户ID', '日预算', '展现', '点击', '消费↓', '加粉', 'CPM', 'CTR', '账户加粉成本', '现金加粉成本'])
  await expect(page.getByRole('button', { name: '筛选生命周期' })).toHaveCSS('opacity', '0')
  await headers.nth(2).hover()
  await expect(page.getByRole('button', { name: '筛选生命周期' })).toHaveCSS('opacity', '1')
  await page.getByRole('button', { name: '筛选生命周期' }).click()
  await expect(page.locator('.account-column-filter-popover')).toBeVisible()
  await expect(page.locator('.account-column-filter-row')).toHaveCount(0)
  await expect(page.getByRole('group', { name: '生命周期筛选' })).toBeVisible()
  await expect(page.getByPlaceholder('搜索生命周期')).toBeVisible()
  await page.getByRole('button', { name: '关闭生命周期筛选' }).click()
  await expect(page.locator('.account-list-overview')).toBeVisible()
  await expect(page.locator('.account-list-overview')).toContainText('现金加粉成本')
  const firstAccount = page.locator('.account-name-expand').first()
  if (await firstAccount.count()) {
    await firstAccount.click()
    await expect(page.locator('.account-campaign-panel')).toBeVisible()
    await expect(page.locator('.account-campaign-panel')).toContainText('同步计划缓存')
  }
  await page.screenshot({ path: resolve(shots, 'account-list-expanded-1920.png'), fullPage: true })
  await expect(page).toHaveScreenshot('account-list-expanded-1920.png', { fullPage: true, animations: 'disabled' })
  expect(remoteRequests).toEqual([])
})

test('table columns and standard pagination follow the shared alignment rules', async ({ page }) => {
  test.setTimeout(90000)
  await page.setViewportSize({ width: 1440, height: 900 })
  const alignment = async (selector: string) => page.locator(selector).first().evaluate(element => getComputedStyle(element).textAlign)
  await page.route('**/api/v1/projects/*/material-keywords*', route => route.fulfill({ json: { status: 'ok', data: { items: [{ id: 'material-1', campaign_name: '测试计划', keyword_text: '测试关键词', impressions: 100, clicks: 8, spend: '32.00', uv: 6, copies: 2, adds: 1, cpc: '4.00', uv_cost: '5.33', copy_cost: '16.00', add_cost: '32.00', is_blacklisted: false, blacklist_reason: null }], total: 1, page: 1, page_size: 20, selected_year: 2026, available_years: [2026] } } }))
  await page.route('**/api/v1/projects/*/reports/daily?*', route => route.fulfill({ json: { status: 'ok', data: { date_from: '2026-09-15', date_to: '2026-09-15', watermark: '2026-09-15T00:00:00Z', total: 1, page: 1, page_size: 20, total_pages: 1, search: '', page_type: '', page_types: [], operator_name: '', operator_names: [], has_unassigned_operator: false, sort_by: 'spend', sort_order: 'desc', summary: { spend: '32.00', impressions: 100, clicks: 8, uv: 6, copies: 2, adds: 1 }, rows: [{ date: '2026-09-15', account_id: 90579419, account_name: '测试账户', operator_name: '王康', balance: '500.00', impressions: 100, clicks: 8, spend: '32.00', cash_spend: '32.00', uv: 6, copies: 2, adds: 1, cpc: '4.00', uv_cost: '5.33', copy_cost: '16.00', add_cost: '32.00', cash_add_cost: '32.00' }] } } }))

  await page.goto('/')
  await expect(page.getByLabel('项目管理分页')).toBeVisible()
  expect(['start', 'left']).toContain(await alignment('.project-name-button'))
  expect(await alignment('.project-widget-table-head > :nth-child(3)')).toBe('center')
  expect(await alignment('.project-widget-table-head > :nth-child(5)')).toBe('center')

  await page.goto('/jfsem?page=accounts')
  await expect(page.getByLabel('账户管家分页')).toBeVisible()
  expect(await alignment('.manager-management-table th:nth-child(2)')).toBe('left')
  expect(await alignment('.manager-management-table th:nth-child(3)')).toBe('right')
  expect(await alignment('.manager-management-table th:nth-child(5)')).toBe('center')

  await page.goto('/jfsem?page=account-list')
  const pager = page.getByLabel('账户列表分页')
  await expect(pager).toBeVisible()
  expect(await alignment('.account-list-table th:nth-child(2)')).toBe('center')
  expect(await alignment('.account-list-table th:nth-child(9)')).toBe('left')
  expect(await alignment('.account-list-table th:nth-child(10)')).toBe('right')
  await expect(pager.getByLabel('每页条数')).toHaveCSS('height', '32px')
  await expect(pager.getByLabel('跳转页码')).toHaveCSS('height', '32px')
  await expect(pager.getByRole('button', { name: '上一页' })).toHaveCSS('height', '32px')
  await expect(pager.getByRole('navigation', { name: '分页操作' })).toContainText('每页')
  await expect(pager.getByRole('navigation', { name: '分页操作' })).toContainText('跳转')

  await page.goto('/jfsem?page=materials')
  await expect(page.getByLabel('物料分页')).toBeVisible()
  expect(await alignment('.material-keyword-table th:nth-child(1)')).toBe('left')
  expect(await alignment('.material-keyword-table th:nth-child(3)')).toBe('right')
  expect(await alignment('.material-keyword-table th:nth-child(13)')).toBe('center')

  await page.goto('/jfsem?page=reports')
  await expect(page.getByLabel('账户日报分页')).toBeVisible()
  expect(await alignment('.report-table .simple-table-head > :nth-child(2)')).toBe('left')
  expect(await alignment('.report-table .simple-table-head > :nth-child(4)')).toBe('right')

  await page.goto('/jfsem?page=members')
  await expect(page.getByLabel('成员管理分页')).toBeVisible()
  expect(await alignment('.member-table-head > :nth-child(1)')).toBe('left')
  expect(await alignment('.member-table-head > :nth-child(5)')).toBe('right')
  expect(await alignment('.member-table-head > :nth-child(7)')).toBe('center')
})
