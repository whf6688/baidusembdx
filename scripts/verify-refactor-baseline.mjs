import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const baseline = path.resolve(process.argv[2] || '')
const manifestPath = path.join(baseline, 'manifest.json')
const archivePath = path.join(baseline, 'source.tar.gz')
if (!existsSync(manifestPath) || !existsSync(archivePath)) throw new Error('Baseline manifest or archive is missing')
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
const temporary = mkdtempSync(path.join(tmpdir(), 'baidu-search-baseline-'))
try {
  execFileSync('tar', ['-xzf', archivePath, '-C', temporary])
  const failures = []
  for (const entry of manifest.files) {
    const restored = path.join(temporary, ...entry.file.split('/'))
    if (!existsSync(restored)) { failures.push(`${entry.file}: missing`); continue }
    const actual = createHash('sha256').update(readFileSync(restored)).digest('hex')
    if (actual !== entry.sha256) failures.push(`${entry.file}: hash mismatch`)
  }
  if (failures.length) throw new Error(`Baseline verification failed: ${failures.slice(0, 10).join(', ')}`)
  const result = { verified_at: new Date().toISOString(), verified: true, file_count: manifest.files.length, archive: archivePath }
  writeFileSync(path.join(baseline, 'verification.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result))
} finally {
  rmSync(temporary, { recursive: true, force: true })
}
