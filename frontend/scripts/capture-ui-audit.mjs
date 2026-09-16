import { chromium } from 'playwright'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const baseUrl = process.env.UI_AUDIT_BASE_URL || 'http://localhost:8280'
const outputDir = path.resolve('artifacts/ui-audit/latest')
const executablePath = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const routes = [
  ['home', '/'],
  ['accounts', '/jfsem?page=accounts'],
  ['account-list', '/jfsem?page=account-list'],
  ['delivery', '/jfsem?page=delivery'],
  ['materials', '/jfsem?page=materials'],
  ['creatives', '/jfsem?page=creatives'],
  ['records', '/jfsem?page=records'],
  ['reports', '/jfsem?page=reports'],
  ['members', '/jfsem?page=members'],
  ['strategies', '/jfsem?page=strategies'],
]

await mkdir(outputDir, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath })
try {
  for (const width of [1440, 1280]) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, deviceScaleFactor: 1 })
    for (const [name, route] of routes) {
      await page.goto(`${baseUrl}${route}`, { waitUntil: 'networkidle', timeout: 30000 })
      await page.waitForTimeout(1200)
      await page.screenshot({ path: path.join(outputDir, `${name}-${width}.png`), fullPage: false })
    }
    await page.close()
  }
} finally {
  await browser.close()
}
