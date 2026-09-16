import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const baseUrl = process.env.UI_AUDIT_BASE_URL || 'http://localhost:8280'
const executablePath = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const outputDir = path.resolve('artifacts/ui-audit/latest/dialogs')
const scenarios = [
  ['project-create', '/', 'button', /^新建项目$/],
  ['manager-create', '/jfsem?page=accounts', 'button', /^添加账户管家$/],
  ['manager-archive', '/jfsem?page=accounts', 'button', /^删除管家$/],
  ['account-choice', '/jfsem?page=delivery', 'button', /^指定账户新建/],
  ['workflow', '/jfsem?page=delivery', 'button', /^查看说明$/],
  ['keyword-blacklist', '/jfsem?page=materials', 'button', /^添加关键词黑名单$/],
  ['negative-keyword', '/jfsem?page=materials', 'button', /^添加否词$/],
  ['keyword-rule', '/jfsem?page=materials', 'button', /^分级规则$/],
  ['creative-add', '/jfsem?page=creatives', 'button', /^添加$/],
  ['member-settings', '/jfsem?page=members', 'button', /^设置$/],
]

await mkdir(outputDir, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath })
try {
  for (const [name, route, role, accessibleName] of scenarios) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
    try {
      await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle', timeout: 30000 })
      await page.waitForTimeout(700)
      await page.getByRole(role, { name: accessibleName }).first().click()
      await page.locator('.fui-DialogSurface').waitFor({ state: 'visible', timeout: 5000 })
      await page.waitForTimeout(350)
      const unevenControls = await page.locator('.fui-DialogSurface').locator('.fui-Input, .fui-Textarea, select, input:not([type="checkbox"]):not([type="radio"]), textarea').evaluateAll(nodes => nodes
        .filter(node => !node.closest('.fui-Input, .fui-Textarea') || node.matches('.fui-Input, .fui-Textarea'))
        .map(node => {
          const style = getComputedStyle(node)
          return {
            node,
            widths: [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth],
            colors: [style.borderTopColor, style.borderRightColor, style.borderBottomColor, style.borderLeftColor],
            styles: [style.borderTopStyle, style.borderRightStyle, style.borderBottomStyle, style.borderLeftStyle],
            shadow: style.boxShadow,
            afterDisplay: node.matches('.fui-Input, .fui-Textarea') ? getComputedStyle(node, '::after').display : 'none',
          }
        })
        .filter(item => new Set(item.widths).size !== 1 || new Set(item.colors).size !== 1 || new Set(item.styles).size !== 1 || item.widths[0] !== '1px' || item.shadow !== 'none' || item.afterDisplay !== 'none')
        .map(item => ({ tag: item.node.tagName.toLowerCase(), className: item.node.className?.toString?.() || '', widths: item.widths, colors: item.colors, styles: item.styles, shadow: item.shadow, afterDisplay: item.afterDisplay })))
      if (unevenControls.length) throw new Error(`dialog controls have uneven borders: ${JSON.stringify(unevenControls)}`)
      await page.screenshot({ path: path.join(outputDir, `${name}.png`), fullPage: false })
    } catch (error) {
      console.log(`${name}: ${error instanceof Error ? error.message : String(error)}`)
    } finally {
      await page.close()
    }
  }
} finally {
  await browser.close()
}
