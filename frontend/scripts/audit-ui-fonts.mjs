import { chromium } from 'playwright'

const baseUrl = process.env.UI_AUDIT_BASE_URL || 'http://localhost:8280'
const executablePath = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const routes = ['/', '/jfsem?page=accounts', '/jfsem?page=account-list', '/jfsem?page=delivery', '/jfsem?page=materials', '/jfsem?page=creatives', '/jfsem?page=records', '/jfsem?page=reports', '/jfsem?page=members', '/jfsem?page=strategies']
const allowedTitleSelector = 'h1, h2, h3, .fui-DialogTitle, .brand-copy strong, .brand-mark, .nav-label'
const dialogScenarios = [
  ['/', 'button', /^新建项目$/],
  ['/jfsem?page=accounts', 'button', /^添加账户管家$/],
  ['/jfsem?page=accounts', 'button', /^删除管家$/],
  ['/jfsem?page=delivery', 'button', /^指定账户新建/],
  ['/jfsem?page=delivery', 'button', /^查看说明$/],
  ['/jfsem?page=materials', 'button', /^添加关键词黑名单$/],
  ['/jfsem?page=materials', 'button', /^添加否词$/],
  ['/jfsem?page=materials', 'button', /^分级规则$/],
  ['/jfsem?page=creatives', 'button', /^添加$/],
  ['/jfsem?page=members', 'button', /^设置$/],
]

async function findOffenders(page) {
  return page.locator('button, input, select, textarea, label, th, td, p, span, small, strong, b, em, a, li, dt, dd').evaluateAll((nodes, allowed) => nodes
    .filter(node => !node.matches(allowed) && !node.closest(allowed))
    .filter(node => Number.parseInt(getComputedStyle(node).fontWeight, 10) > 400)
    .slice(0, 20)
    .map(node => ({ tag: node.tagName.toLowerCase(), className: node.className?.toString?.() || '', text: node.textContent?.trim().slice(0, 50) || '', weight: getComputedStyle(node).fontWeight })), allowedTitleSelector)
}

const browser = await chromium.launch({ headless: true, executablePath })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  let failed = false
  for (const route of routes) {
    await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle', timeout: 30000 })
    await page.waitForTimeout(500)
    const offenders = await findOffenders(page)
    if (offenders.length) {
      failed = true
      console.log(route, JSON.stringify(offenders))
    }
  }
  for (const [route, role, accessibleName] of dialogScenarios) {
    await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle', timeout: 30000 })
    await page.waitForTimeout(500)
    await page.getByRole(role, { name: accessibleName }).first().click()
    await page.locator('.fui-DialogSurface').waitFor({ state: 'visible', timeout: 5000 })
    await page.waitForTimeout(350)
    const offenders = await findOffenders(page)
    if (offenders.length) {
      failed = true
      console.log(`${route} dialog ${String(accessibleName)}`, JSON.stringify(offenders))
    }
  }
  if (failed) process.exitCode = 1
} finally {
  await browser.close()
}
