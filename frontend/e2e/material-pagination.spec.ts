import { expect, test } from '@playwright/test'

test('materials paginate, reset filters and distinguish loading from empty', async ({ page }) => {
  let releaseLoad!: () => void
  const firstLoadGate = new Promise<void>(resolve => { releaseLoad = resolve })
  await page.route('**/api/v1/projects/*/material-keywords/facets', route => route.fulfill({
    json: { status: 'ok', data: { campaign_names: ['A成本', 'B机会'] } },
  }))
  await page.route('**/api/v1/projects/*/material-keywords?*', async route => {
    const query = new URL(route.request().url()).searchParams
    const current = Number(query.get('page'))
    const size = Number(query.get('page_size'))
    const total = query.getAll('blacklist_statuses').join(',') === 'blacklisted' ? 0 : 205
    await firstLoadGate
    await route.fulfill({ json: { status: 'ok', data: {
      total, page: current, page_size: size, available_years: [2026, 2025], selected_year: null,
      items: Array.from({ length: Math.max(0, Math.min(size, total - (current - 1) * size)) }, (_, index) => ({
        id: String((current - 1) * size + index + 1), campaign_name: 'A成本',
        keyword_text: `分页验证词-${(current - 1) * size + index + 1}`, is_blacklisted: false,
      })),
    } } })
  })
  await page.goto('/jfsem')
  await page.locator('.nav-item').filter({ hasText: '自动上线' }).click()
  await page.getByRole('tab', { name: /物料中心/ }).click()
  await expect(page.locator('.material-year-filter')).not.toContainText('总计')
  await expect(page.getByText('正在加载物料明细…')).toBeVisible()
  await expect(page.getByText('尚无物料明细', { exact: true })).toHaveCount(0)
  releaseLoad()
  const pager = page.locator('.viewport-sticky-pagination')
  const rows = page.locator('.material-keyword-table tbody tr')
  await expect(rows).toHaveCount(20)
  await expect(pager.getByRole('button', { name: '上一页' })).toBeDisabled()
  await pager.getByRole('button', { name: '下一页' }).click()
  await expect(rows.first()).toContainText('分页验证词-21')
  await pager.getByLabel('跳转页码').fill('11')
  await pager.getByLabel('跳转页码').press('Enter')
  await expect(rows).toHaveCount(5)
  await expect(pager.getByRole('button', { name: '下一页' })).toBeDisabled()
  await pager.getByLabel('跳转页码').fill('2')
  await pager.getByLabel('跳转页码').press('Enter')
  await expect(rows.first()).toContainText('分页验证词-21')
  await expect(pager).toContainText('/ 11 页')
  await pager.getByRole('button', { name: '下一页' }).click()
  await expect(rows.first()).toContainText('分页验证词-41')
  await page.locator('.material-year-filter select').selectOption('2025')
  await expect(pager).toContainText('/ 11 页')
  await expect(rows.first()).toContainText('分页验证词-1')
  await page.getByRole('button', { name: '筛选状态' }).click()
  const statusFilter = page.locator('.account-column-filter-menu').filter({ hasText: '状态筛选' })
  await statusFilter.getByText('正常', { exact: true }).click()
  await statusFilter.getByRole('button', { name: '应用' }).click()
  await expect(page.getByText('黑名单为空', { exact: true })).toBeVisible()
  await expect(pager).toContainText('显示 0–0，共 0 条')
  await expect(pager.getByRole('button', { name: '下一页' })).toBeDisabled()
})

test('material headers filter plans, keywords and status across the full result set', async ({ page }) => {
  const requestedUrls: string[] = []
  await page.route('**/api/v1/projects/*/material-keywords/facets', route => route.fulfill({
    json: { status: 'ok', data: { campaign_names: ['A成本', 'B机会'] } },
  }))
  await page.route('**/api/v1/projects/*/material-keywords?*', route => {
    requestedUrls.push(route.request().url())
    return route.fulfill({ json: { status: 'ok', data: {
      total: 1, page: 1, page_size: 20, available_years: [2026], selected_year: 2026,
      items: [{ id: '1', campaign_name: 'A成本', keyword_text: '轻断食', is_blacklisted: false }],
    } } })
  })
  await page.goto('/jfsem?page=materials', { waitUntil: 'networkidle' })

  await page.getByRole('button', { name: '筛选计划' }).click()
  const campaignFilter = page.locator('.account-column-filter-menu').filter({ hasText: '计划筛选' })
  await campaignFilter.getByText('B机会', { exact: true }).click()
  await campaignFilter.getByRole('button', { name: '应用' }).click()
  await expect.poll(() => requestedUrls.at(-1) || '').toContain('campaign_names=A%E6%88%90%E6%9C%AC')

  await page.getByRole('button', { name: '筛选关键词' }).click()
  const keywordFilter = page.locator('.material-text-column-filter')
  await keywordFilter.getByRole('searchbox', { name: '搜索关键词' }).fill('轻断食')
  await keywordFilter.getByRole('button', { name: '应用' }).click()
  await expect.poll(() => requestedUrls.at(-1) || '').toContain('keyword_search=%E8%BD%BB%E6%96%AD%E9%A3%9F')

  await page.getByRole('button', { name: '筛选状态' }).click()
  const statusFilter = page.locator('.account-column-filter-menu').filter({ hasText: '状态筛选' })
  await statusFilter.getByText('黑名单', { exact: true }).click()
  await statusFilter.getByRole('button', { name: '应用' }).click()
  await expect.poll(() => requestedUrls.at(-1) || '').toContain('blacklist_statuses=normal')
  expect(new URL(requestedUrls.at(-1)!).searchParams.get('page')).toBe('1')
})

test('material request errors are not presented as missing data', async ({ page }) => {
  await page.route('**/api/v1/projects/*/material-keywords?*', route => route.fulfill({
    status: 503, json: { status: 'error', error: { message: '物料查询暂时不可用' } },
  }))
  await page.goto('/jfsem')
  await page.locator('.nav-item').filter({ hasText: '自动上线' }).click()
  await page.getByRole('tab', { name: /物料中心/ }).click()
  const popup = page.locator('.popup-message').filter({ hasText: '物料查询暂时不可用' })
  await expect(popup).toBeVisible()
  await popup.getByRole('button', { name: '关闭提示' }).click()
  await expect(popup).toHaveCount(0)
  await expect(page.getByText('尚无物料明细', { exact: true })).toHaveCount(0)
})

test('manual keyword blacklist dialog only keeps the keyword input', async ({ page }) => {
  await page.route('**/api/v1/projects/*/material-keywords/facets', route => route.fulfill({
    json: { status: 'ok', data: { campaign_names: [] } },
  }))
  await page.route('**/api/v1/projects/*/material-keywords?*', route => route.fulfill({
    json: { status: 'ok', data: {
      total: 0, page: 1, page_size: 20, available_years: [2026], selected_year: 2026, items: [],
    } },
  }))
  await page.goto('/jfsem?page=materials', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: '添加关键词黑名单', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('textbox', { name: '关键词' })).toBeVisible()
  await expect(dialog.getByText('每行输入一个关键词，也支持逗号分隔；已有物料会直接拉黑；尚未导入的词会保存为黑名单占位，后续导入时自动跳过', { exact: true })).toHaveCount(0)
  await expect(dialog.getByText('黑名单关键词', { exact: true })).toHaveCount(0)
  await expect(dialog.getByText('原因（选填）', { exact: true })).toHaveCount(0)
  await expect(dialog.locator('input')).toHaveCount(0)
})

test('negative keyword add and list use separate dialogs', async ({ page }) => {
  await page.route('**/api/v1/projects/*/material-keywords/facets', route => route.fulfill({
    json: { status: 'ok', data: { campaign_names: [] } },
  }))
  await page.route('**/api/v1/projects/*/material-keywords?*', route => route.fulfill({
    json: { status: 'ok', data: {
      total: 0, page: 1, page_size: 20, available_years: [2026], selected_year: 2026, items: [],
    } },
  }))
  await page.route('**/api/v1/projects/*/negative-keywords', route => route.fulfill({
    json: { status: 'ok', data: { counts: { phrase: 1, exact: 0 }, items: [
      { id: 'negative-1', keyword_text: '免费', match_type: 'phrase', source: 'manual', created_by: 'admin', created_at: '2026-09-16T08:00:00Z' },
    ] } },
  }))
  await page.goto('/jfsem?page=materials', { waitUntil: 'networkidle' })

  await page.getByRole('button', { name: '添加否词', exact: true }).click()
  const addDialog = page.getByRole('dialog', { name: '添加否词' })
  await expect(addDialog).toBeVisible()
  await expect(addDialog.locator('textarea')).toBeVisible()
  await expect(addDialog.getByText('从当前模板复制', { exact: true })).toHaveCount(0)
  await expect(addDialog.getByRole('tablist')).toHaveCount(0)
  await expect(addDialog.getByText('添加短语否定关键词', { exact: true })).toHaveCount(0)
  await expect(addDialog.getByRole('button', { name: '取消', exact: true })).toBeVisible()
  await expect(addDialog.getByRole('button', { name: '添加短语否词', exact: true })).toBeVisible()
  await expect(addDialog.getByRole('button', { name: '添加精确否词', exact: true })).toBeVisible()
  await expect(addDialog.locator('.negative-keyword-list-section')).toHaveCount(0)
  await addDialog.getByRole('button', { name: '取消', exact: true }).click()

  await page.getByRole('button', { name: '否词名单', exact: true }).click()
  const listDialog = page.getByRole('dialog', { name: '否词名单' })
  await expect(listDialog).toBeVisible()
  await expect(listDialog.getByRole('searchbox', { name: '搜索否词' })).toBeVisible()
  await expect(listDialog.getByRole('columnheader', { name: '否词' })).toBeVisible()
  await expect(listDialog.getByRole('columnheader', { name: '类型' })).toBeVisible()
  await expect(listDialog.getByRole('columnheader', { name: '来源' })).toBeVisible()
  await expect(listDialog.getByRole('columnheader', { name: '添加时间' })).toBeVisible()
  await expect(listDialog.locator('.viewport-sticky-pagination[aria-label="否词名单分页"]')).toBeVisible()
  await expect(listDialog.getByText('免费', { exact: true })).toBeVisible()
  await expect(listDialog.getByText('短语否词', { exact: true })).toBeVisible()
  await expect(listDialog.locator('textarea')).toHaveCount(0)
})

test('material table stays fully usable above the fixed pagination', async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  await page.route('**/api/v1/projects/*/material-keywords?*', route => route.fulfill({
    json: { status: 'ok', data: {
      total: 20, page: 1, page_size: 20, available_years: [2026], selected_year: 2026,
      items: Array.from({ length: 20 }, (_, index) => ({
        id: String(index + 1), campaign_name: 'A成本', keyword_text: `布局验证词-${index + 1}`,
        impressions: 100, clicks: 8, spend: '32.00', uv: 6, copies: 2, adds: 1,
        cpc: '4.00', uv_cost: '5.33', copy_cost: '16.00', add_cost: '32.00',
        is_blacklisted: false, blacklist_reason: null,
      })),
    } },
  }))
  await page.goto('/jfsem?page=materials', { waitUntil: 'networkidle' })
  const tableViewport = page.locator('.material-keyword-table-scroll')
  const pagination = page.locator('.viewport-sticky-pagination')
  await expect(page.locator('.material-keyword-table tbody tr')).toHaveCount(20)
  const tableBox = await tableViewport.boundingBox()
  const paginationBox = await pagination.boundingBox()
  expect(tableBox).not.toBeNull()
  expect(paginationBox).not.toBeNull()
  const tableOverflow = await tableViewport.evaluate(element => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }))
  expect(tableOverflow.scrollHeight).toBe(tableOverflow.clientHeight)
  const finalRow = page.getByText('布局验证词-20', { exact: true })
  await finalRow.scrollIntoViewIfNeeded()
  const finalRowBox = await finalRow.boundingBox()
  const visiblePaginationBox = await pagination.boundingBox()
  expect(finalRowBox).not.toBeNull()
  expect(visiblePaginationBox).not.toBeNull()
  expect(finalRowBox!.y + finalRowBox!.height).toBeLessThanOrEqual(visiblePaginationBox!.y)
  await page.screenshot({ path: 'artifacts/ui-audit/latest/materials-table-bottom.png' })
})
