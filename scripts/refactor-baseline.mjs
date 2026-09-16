import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Source-only recovery archive. Never includes runtime data or credentials.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const id = new Date().toISOString().replace(/[:.]/g, '-')
const output = path.join(root, 'data', 'refactor', 'baselines', id)
mkdirSync(output, { recursive: true })
const excluded = new Set(['node_modules', 'dist', '__pycache__', '.pytest_cache', '.ruff_cache', '.git', 'data', 'storage', '.venv'])
const entries = []
function scan(relative) {
  const absolute = path.join(root, relative)
  for (const item of readdirSync(absolute, { withFileTypes: true })) {
    if (excluded.has(item.name) || item.name.startsWith('.env') || /(?:htpasswd|\.pem$|\.key$|\.pyc$|\.duckdb|\.tsbuildinfo$)/i.test(item.name)) continue
    const child = path.join(relative, item.name)
    if (item.isDirectory()) scan(child)
    else if (item.isFile()) entries.push(child.replaceAll('\\', '/'))
  }
}
for (const directory of ['backend', 'frontend', 'packages', 'deploy', 'scripts', 'docs']) scan(directory)
for (const name of ['AGENTS.md', 'README.md', '.gitignore', '.dockerignore', 'docker-compose.yml']) {
  if (existsSync(path.join(root, name))) entries.push(name)
}
entries.sort()
const manifest = entries.map(file => ({ file, sha256: createHash('sha256').update(readFileSync(path.join(root, file))).digest('hex') }))
writeFileSync(path.join(output, 'manifest.json'), JSON.stringify({ created_at: new Date().toISOString(), root, files: manifest }, null, 2))
writeFileSync(path.join(output, 'files.txt'), entries.join('\n') + '\n')
const archive = path.join(output, 'source.tar.gz')
execFileSync('tar', ['-czf', archive, '-C', root, ...entries])
const listed = execFileSync('tar', ['-tzf', archive], { encoding: 'utf8' })
  .trim().split(/\r?\n/).map(file => file.replace(/^\.\//, '').replaceAll('\\', '/')).sort()
const asciiEntries = entries.filter(file => /^[\x00-\x7F]+$/.test(file))
const missing = asciiEntries.filter(file => !listed.includes(file))
if (missing.length) throw new Error(`Archive verification failed; missing ${missing.join(', ')}`)
if (listed.length !== entries.length) throw new Error(`Archive verification failed; expected ${entries.length} files, found ${listed.length}`)
const forbidden = listed.filter(file => /(^|\/)\.env($|\.)|(^|\/)(data|storage)(\/|$)|htpasswd|\.duckdb|\.pem$|\.key$/i.test(file))
if (forbidden.length) throw new Error(`Archive contains forbidden files: ${forbidden.join(', ')}`)
execFileSync(process.execPath, [path.join(root, 'scripts', 'verify-refactor-baseline.mjs'), output], { stdio: 'inherit' })
console.log(JSON.stringify({ baseline: output, file_count: entries.length, verified: true }))
