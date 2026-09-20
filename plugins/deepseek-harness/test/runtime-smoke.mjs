/** Integration against official Cordis Loader, ToolRuntime and live FastAPI. */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
import { mkdir, writeFile, readFile } from 'node:fs/promises'

const runtimeRoot = process.env.NOVELATLAS_HARNESS_RUNTIME || '/private/tmp/novelatlas-harness-runtime'
const requireRuntime = createRequire(resolve(runtimeRoot, 'package.json'))
const load = name => import(pathToFileURL(requireRuntime.resolve(name)).href)
const { Context } = await load('@deepseek-ai/cordis')
const { default: Loader } = await load('@deepseek-ai/cordis-plugin-loader')
const ctx = new Context()
const root = new URL('../', import.meta.url)
const profileRoot = process.env.NOVELATLAS_HARNESS_PROFILE || '/private/tmp/novelatlas-dsh-home/profiles/novelatlas-demo'
const loader = ctx.plugin(Loader, { baseUrl: pathToFileURL(profileRoot + '/').href })
await loader.await()
await ctx.loader.create({ id: 'system-prompt', name: pathToFileURL(requireRuntime.resolve('@deepseek-ai/dsh-system-prompt')).href })
await ctx.loader.create({ id: 'tools', name: pathToFileURL(requireRuntime.resolve('@deepseek-ai/dsh-tools')).href })
await ctx.loader.create({ id: 'skills', name: pathToFileURL(requireRuntime.resolve('@deepseek-ai/dsh-skill')).href })
await ctx.loader.create({ id: 'novelatlas', name: 'dsh-novelatlas',
  config: { apiBaseUrl: process.env.NOVELATLAS_API_URL || 'http://127.0.0.1:8017', timeoutMs: 30000, exportDirectory: '/private/tmp/novelatlas-harness-exports' } })
await ctx.loader.await()
const skills = await ctx.skills.list()
assert(skills.some(s => s.name === 'novelatlas-analyze'))
const skill = await ctx.skills.get('novelatlas-analyze')
assert(skill.content.includes('LangGraph'))
const results = []
async function call(name, args, expectedError = false) {
  const result = await ctx.tools.execute({ callId: 'smoke-' + results.length, name, arguments: args, signal: AbortSignal.timeout(30000) })
  assert.equal(result.isError, expectedError, JSON.stringify(result))
  results.push({ tool: name, isError: result.isError })
  return result.value
}
try {
  const sample = await readFile(new URL('../examples/agent_demo.txt', import.meta.url), 'utf8')
  const upload = await call('novelatlas_import_text', { text: sample, filename: 'demo.txt' })
  const tid = upload.task_id
  const search = await call('novelatlas_search', { task_id: tid, query: '林舟 沈月 决裂' })
  assert(search.length > 0)
  const evidence = { task_id: tid, passage_id: search[0].passage_id, chapter_id: search[0].chapter_id, chunk_id: search[0].chunk_id, quote: search[0].content.slice(0, 10) }
  assert.equal((await call('novelatlas_verify', evidence)).quote_valid, true)
  assert.equal((await call('novelatlas_verify', { ...evidence, quote: '不存在的证据' })).quote_valid, false)
  await call('novelatlas_task', { task_id: '../../escape' }, true)
  await call('novelatlas_search', { task_id: tid, query: 42 }, true)
  await call('novelatlas_cancel', { task_id: tid }, true) // no active task yet: expect a safe HTTP error
  await call('novelatlas_analyze', { task_id: tid, goal: '分析人物别名、关系变化及伪造密信的跨章节证据' })
  let status
  for (let i = 0; i < 100; i++) {
    status = await call('novelatlas_task', { task_id: tid, include_report: true })
    if (['completed', 'failed'].includes(status.status.status)) break
    await new Promise(r => setTimeout(r, 100))
  }
  assert.equal(status.status.status, 'completed', JSON.stringify(status))
  assert(status.report.reviews.length > 0)
  const html = await call('novelatlas_export', { task_id: tid, format: 'html' })
  assert((await readFile(html.path, 'utf8')).includes('Mock'))
  const docx = await call('novelatlas_export', { task_id: tid, format: 'docx' })
  assert((await readFile(docx.path))[0] === 0x50)
  const pluginManifest = JSON.parse(await readFile(resolve(profileRoot, 'node_modules/dsh-novelatlas/package.json'), 'utf8'))
  const summary = { plugin_version: pluginManifest.version, plugin_dependencies: pluginManifest.dependencies, runtime: 'official Cordis Loader + ToolRuntime', model: 'mock', skills: skills.map(s => s.name), task_id: tid, calls: results, exports: [html, docx] }
  const recordPath = resolve(root.pathname, '../../backup/plugins/deepseek-harness/test/last-smoke.json')
  await mkdir(resolve(recordPath, '..'), { recursive: true })
  await writeFile(recordPath, JSON.stringify(summary, null, 2))
  console.log(JSON.stringify(summary, null, 2))
} finally {
  await ctx.loader.remove('novelatlas')
  assert(!(await ctx.skills.list()).some(s => s.name === 'novelatlas-analyze'))
  await loader.dispose()
}
