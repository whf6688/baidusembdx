import { expect, test } from '@playwright/test'

test.beforeEach(async ({ context }) => {
  const sessionToken = process.env.TEST_SESSION_TOKEN
  if (sessionToken) {
    await context.addCookies([
      {
        name: 'search_console_session',
        value: sessionToken,
        domain: 'localhost',
        path: '/',
      },
    ])
  }
})


test('automatic build exposes the project province/city default in a tall dual-pane dialog', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/jfsem?page=delivery', { waitUntil: 'networkidle' })

  const scheduleButton = page.getByRole('button', { name: '设置计划时段' })
  const regionButton = page.getByRole('button', { name: '设置推广地域' })
  await expect(scheduleButton).toBeVisible()
  await expect(regionButton).toBeVisible()

  const actionButtons = page.locator('.build-mode-execution-tools > button')
  await expect(actionButtons.nth(0)).toHaveText('设置计划时段')
  await expect(actionButtons.nth(1)).toHaveText('设置推广地域')

  await regionButton.click()
  const dialog = page.getByRole('dialog', { name: /设置推广地域/ })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('省级地域', { exact: true })).toBeVisible()
  await expect(dialog.getByText('已选 106', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: '取消' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: '保存为默认' })).toBeVisible()

  const box = await dialog.boundingBox()
  expect(box).not.toBeNull()
  expect(box!.width).toBeGreaterThan(900)
  expect(box!.height).toBeGreaterThan(680)
  expect(box!.x).toBeGreaterThanOrEqual(0)
  expect(box!.y).toBeGreaterThanOrEqual(0)
  expect(box!.x + box!.width).toBeLessThanOrEqual(1440)
  expect(box!.y + box!.height).toBeLessThanOrEqual(900)
  const provinceList = dialog.getByRole('listbox', { name: '省级地域' })
  const provinceButtons = provinceList.getByRole('option')
  await expect(provinceButtons).toHaveCount(34)
  const firstProvinceBox = await provinceButtons.nth(0).boundingBox()
  const secondProvinceBox = await provinceButtons.nth(1).boundingBox()
  const thirdProvinceBox = await provinceButtons.nth(2).boundingBox()
  expect(Math.abs(firstProvinceBox!.y - secondProvinceBox!.y)).toBeLessThan(2)
  expect(thirdProvinceBox!.y).toBeGreaterThan(firstProvinceBox!.y)
  await expect(dialog.getByText(/^\d+ 市$/)).toHaveCount(0)
  await expect(dialog.getByLabel('已选省市')).toHaveCount(0)

  await provinceList.getByRole('button', { name: '广东' }).click()
  const cityList = dialog.getByRole('group', { name: '广东市级地域' })
  const allProvinceCheckbox = cityList.getByRole('checkbox', { name: /全省/ })
  await expect(allProvinceCheckbox).toBeVisible()
  await expect(cityList.getByRole('checkbox', { name: '广州' })).toBeVisible()
  expect(await allProvinceCheckbox.evaluate((element) => (element as HTMLInputElement).indeterminate)).toBe(true)
  await allProvinceCheckbox.check()
  await expect(cityList.getByRole('checkbox', { name: '广州' })).toBeChecked()
  await expect(cityList.getByRole('checkbox', { name: '深圳' })).toBeChecked()
  await cityList.getByRole('checkbox', { name: '广州' }).uncheck()
  expect(await allProvinceCheckbox.evaluate((element) => (element as HTMLInputElement).indeterminate)).toBe(true)
  await expect(cityList.getByRole('checkbox', { name: '深圳' })).toBeChecked()
  await dialog.getByRole('searchbox', { name: '搜索市级地域' }).fill('深圳')
  await expect(cityList.getByRole('checkbox', { name: '深圳' })).toBeVisible()

  const overflowState = await dialog.evaluate(() => {
    const provinces = document.querySelector('.region-province-list') as HTMLElement
    const cities = document.querySelector('.region-city-list') as HTMLElement
    return {
      provinceOverflowY: getComputedStyle(provinces).overflowY,
      provinceFits: provinces.scrollHeight <= provinces.clientHeight,
      cityOverflowY: getComputedStyle(cities).overflowY,
      cityFits: cities.scrollHeight <= cities.clientHeight,
    }
  })
  expect(overflowState.provinceOverflowY).toBe('visible')
  expect(overflowState.provinceFits).toBe(true)
  expect(overflowState.cityOverflowY).toBe('visible')
  expect(overflowState.cityFits).toBe(true)

  await dialog.getByRole('searchbox', { name: '搜索市级地域' }).fill('')
  await dialog.screenshot({
    path: 'artifacts/ui-audit/latest/dialogs/auto-launch-regions.png',
    animations: 'disabled',
  })
  await dialog.getByRole('button', { name: '取消' }).click()
  await expect(dialog).toBeHidden()
})


test('workflow help owns the hierarchy and strategies no longer expose a reference-template tab', async ({ page }) => {
  await page.goto('/jfsem?page=delivery', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: '搭建流程说明' }).click()
  const workflowDialog = page.getByRole('dialog', { name: /搭建流程说明/ })
  await expect(workflowDialog).toContainText('oCPC项目')
  await expect(workflowDialog).toContainText('计划')
  await expect(workflowDialog).toContainText('单元')
  await expect(workflowDialog).toContainText('关键词')
  await expect(workflowDialog).toContainText('创意')
  await expect(workflowDialog).toContainText('运行时不依赖任何参考账户')

  await page.goto('/jfsem?page=strategies', { waitUntil: 'networkidle' })
  await expect(page.getByRole('tab', { name: /参考模板/ })).toHaveCount(0)

  const strategyNavigation = page.getByRole('navigation', { name: '自动策略规则' })
  await expect(strategyNavigation).toBeVisible()
  await expect(strategyNavigation.getByText('实时调整', { exact: true })).toBeVisible()
  await expect(strategyNavigation.getByText('周期调整', { exact: true })).toBeVisible()
  await expect(strategyNavigation.getByText('全局判定', { exact: true })).toBeVisible()
  await expect(strategyNavigation.getByRole('button')).toHaveText([
    '搭建设置',
    '预算追加',
    '预算重置',
    '账户淘汰',
    '实时闭环',
  ])
  await expect(page.getByRole('tablist', { name: '自动策略设置分区' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '关键词分级' })).toHaveCount(0)

  const releaseBar = page.locator('.strategy-release-bar')
  await expect(releaseBar.getByRole('heading', { name: '自动策略' })).toBeVisible()
  await expect(releaseBar).toContainText('线上版本')
  await expect(releaseBar.getByRole('button', { name: '发布规则' })).toBeVisible()
  await expect(page.locator('.strategy-header')).toHaveCount(0)

  const budgetWorkspace = page.getByRole('region', { name: '预算追加工作区' })
  const budgetTabs = budgetWorkspace.getByRole('tablist', { name: '预算追加内容' })
  await expect(budgetTabs.getByRole('tab')).toHaveText(['规则设置', '执行记录', '效果复盘'])
  await expect(budgetWorkspace.getByRole('combobox', { name: '执行模式' })).toHaveValue('自动执行')
  await expect(budgetWorkspace.getByRole('combobox', { name: '执行周期' })).toHaveValue('每小时评估')
  await expect(budgetWorkspace.getByRole('button', { name: '编辑规则' })).toBeVisible()
  const triggerConditions = budgetWorkspace.locator('.budget-trigger-conditions')
  const roundAmounts = budgetWorkspace.locator('.budget-round-amounts')
  await expect(triggerConditions.getByRole('heading', { name: '触发条件' })).toBeVisible()
  const triggerHeadingBox = await triggerConditions.getByRole('heading', { name: '触发条件' }).boundingBox()
  const triggerDescriptionBox = await triggerConditions.getByText('以下条件同时满足时，进入下一轮预算追加').boundingBox()
  expect(triggerHeadingBox).not.toBeNull()
  expect(triggerDescriptionBox).not.toBeNull()
  expect(Math.abs(triggerHeadingBox!.y - triggerDescriptionBox!.y)).toBeLessThanOrEqual(4)
  expect(triggerDescriptionBox!.x).toBeGreaterThan(triggerHeadingBox!.x + triggerHeadingBox!.width)
  await expect(triggerConditions.getByLabel('加粉成本上限')).toHaveValue('100.00')
  await expect(triggerConditions.getByLabel('预算利用率')).toHaveValue('80')
  await expect(budgetWorkspace.getByRole('heading', { name: '追加轮次' })).toBeVisible()
  const roundHeadingBox = await budgetWorkspace.getByRole('heading', { name: '追加轮次' }).boundingBox()
  const roundDescriptionBox = await budgetWorkspace.getByText('每轮直接填写追加金额；第 10 轮及以上沿用最后一档').boundingBox()
  expect(roundHeadingBox).not.toBeNull()
  expect(roundDescriptionBox).not.toBeNull()
  expect(Math.abs(roundHeadingBox!.y - roundDescriptionBox!.y)).toBeLessThanOrEqual(4)
  expect(roundDescriptionBox!.x).toBeGreaterThan(roundHeadingBox!.x + roundHeadingBox!.width)
  await expect(budgetWorkspace.getByLabel('第 1 轮追加金额')).toHaveValue('50.00')
  await expect(budgetWorkspace.getByLabel('第 10 轮及以上追加金额')).toHaveValue('50.00')
  const roundTable = roundAmounts.getByRole('table', { name: '追加轮次金额' })
  await expect(roundTable.getByRole('columnheader')).toHaveCount(10)
  await expect(roundTable.getByRole('row')).toHaveCount(2)
  const firstRoundBox = await budgetWorkspace.getByLabel('第 1 轮追加金额').boundingBox()
  const lastRoundBox = await budgetWorkspace.getByLabel('第 10 轮及以上追加金额').boundingBox()
  expect(firstRoundBox).not.toBeNull()
  expect(lastRoundBox).not.toBeNull()
  expect(firstRoundBox!.y).toBe(lastRoundBox!.y)
  expect(firstRoundBox!.x).toBeLessThan(lastRoundBox!.x)
  const inputFrame = await budgetWorkspace.getByLabel('第 1 轮追加金额').evaluate((input) => {
    const root = input.closest('.fui-Input')
    if (!(root instanceof HTMLElement)) throw new Error('Missing Fluent input frame')
    const style = getComputedStyle(root)
    return {
      widths: [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth],
      colors: [style.borderTopColor, style.borderRightColor, style.borderBottomColor, style.borderLeftColor],
      underline: getComputedStyle(root, '::after').display,
    }
  })
  expect(new Set(inputFrame.widths)).toEqual(new Set(['1px']))
  expect(new Set(inputFrame.colors).size).toBe(1)
  expect(inputFrame.underline).toBe('none')
  await expect(budgetWorkspace.getByText(/售价阶段/)).toHaveCount(0)
  await expect(budgetWorkspace.getByText(/倍数/)).toHaveCount(0)
  await expect(budgetWorkspace.getByText('规则参数', { exact: true })).toHaveCount(0)
  await expect(budgetWorkspace.getByText('编辑只会保存为草稿，必须经过试运行后才能发布', { exact: true })).toHaveCount(0)
  await expect(budgetWorkspace.getByRole('button', { name: '恢复当前内容' })).toHaveCount(0)
  const triggerBox = await triggerConditions.boundingBox()
  const roundsBox = await roundAmounts.boundingBox()
  expect(triggerBox).not.toBeNull()
  expect(roundsBox).not.toBeNull()
  expect(triggerBox!.y).toBeLessThan(roundsBox!.y)
  await expect(budgetWorkspace.getByText('执行时间', { exact: true })).toHaveCount(0)
  await expect(budgetWorkspace.getByRole('button', { name: '增加时间' })).toHaveCount(0)
  await expect(budgetWorkspace.getByText('时间按北京时间执行；默认设置与重构前完全一致', { exact: true })).toHaveCount(0)
  await expect(budgetWorkspace.getByRole('button', { name: '校验参数' })).toHaveCount(0)
  await expect(budgetWorkspace.getByRole('button', { name: '保存草稿' })).toHaveCount(0)
  await expect(budgetWorkspace.getByRole('button', { name: '试运行' })).toHaveCount(0)
  await expect(budgetWorkspace.getByRole('button', { name: '发布', exact: true })).toHaveCount(0)
  await page.screenshot({
    path: 'artifacts/ui-audit/latest/pages/automatic-strategies-policy.png',
    animations: 'disabled',
    fullPage: true,
  })
  await budgetWorkspace.getByRole('button', { name: '编辑规则' }).click()
  await expect(budgetWorkspace.getByRole('button', { name: '取消' })).toBeVisible()
  await expect(budgetWorkspace.getByRole('button', { name: '保存规则' })).toBeVisible()
  await expect(budgetWorkspace.getByRole('button', { name: '保存规则' })).toBeDisabled()
  await expect(releaseBar.getByRole('button', { name: '发布规则' })).toBeDisabled()
  await page.screenshot({
    path: 'artifacts/ui-audit/latest/pages/automatic-strategies-policy-edit.png',
    animations: 'disabled',
    fullPage: true,
  })
  await budgetWorkspace.getByRole('button', { name: '取消' }).click()
  await expect(budgetWorkspace.getByRole('button', { name: '编辑规则' })).toBeVisible()

  await strategyNavigation.getByRole('button', { name: '预算重置' }).click()
  const resetWorkspace = page.getByRole('region', { name: '预算重置工作区' })
  const resetTriggerConditions = resetWorkspace.locator('.budget-reset-rule')
  await expect(resetTriggerConditions.getByRole('heading', { name: '触发条件' })).toBeVisible()
  await expect(resetTriggerConditions).toContainText('账户已启用且未淘汰')
  await expect(resetTriggerConditions).toContainText('测试期')
  await expect(resetTriggerConditions).toContainText('预算快照在 60 分钟内')
  await expect(resetTriggerConditions).toContainText('当前日预算不等于填写金额')
  await expect(resetWorkspace.getByLabel('固定日预算')).toHaveValue('50.00')
  await page.screenshot({
    path: 'artifacts/ui-audit/latest/pages/automatic-strategies-budget-reset.png',
    animations: 'disabled',
    fullPage: true,
  })

  await strategyNavigation.getByRole('button', { name: '实时闭环' }).click()
  const workspace = page.getByRole('region', { name: '实时闭环工作区' })
  await expect(workspace.getByText('项目数据刷新', { exact: true })).toHaveCount(0)
  await expect(workspace.getByText('页面时区', { exact: true })).toHaveCount(0)
  await expect(workspace.getByText('项目闭环刷新周期（分钟）', { exact: true })).toBeVisible()
  await expect(workspace.getByText('运行与安全状态', { exact: true })).toHaveCount(0)
  await expect(workspace.getByText('闭环运行状态', { exact: true })).toHaveCount(0)
  await expect(workspace.getByText('规则评估', { exact: true })).toHaveCount(0)
  await page.screenshot({
    path: 'artifacts/ui-audit/latest/pages/automatic-strategies.png',
    animations: 'disabled',
    fullPage: true,
  })
})
