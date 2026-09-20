/** Harness owns tool/session presentation; Python LangGraph owns analysis. */
import { readFileSync } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import Schema from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'novelatlas'
export const inject = ['tools', 'skills']
export const Config = Schema.object({
  apiBaseUrl: Schema.string().default('http://127.0.0.1:8000'),
  timeoutMs: Schema.number().min(100).max(120000).default(30000),
  exportDirectory: Schema.string().default('./novelatlas-exports'),
})

const task = { type: 'string', required: true, description: 'NovelAtlas temporary task ID (32 hex characters)' }
const string = description => ({ type: 'string', required: true, description })
function taskPath(id) {
  if (!/^[0-9a-f]{32}$/.test(id)) throw new Error('Invalid task ID')
  return `/api/analyses/${id}`
}

export function apply(ctx, config) {
  const base = new URL(config.apiBaseUrl)
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash) throw new Error('Invalid API base URL')
  const exportRoot = resolve(config.exportDirectory)
  async function request(path, options = {}, signal) {
    const combined = signal ? AbortSignal.any([signal, AbortSignal.timeout(config.timeoutMs)]) : AbortSignal.timeout(config.timeoutMs)
    const response = await fetch(new URL(path, base), { ...options, signal: combined })
    if (!response.ok) throw new Error(`NovelAtlas HTTP ${response.status}; check task expiry, plan and configuration`)
    return response
  }
  async function json(path, value, signal, method = 'POST') {
    return (await request(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) }, signal)).json()
  }
  function register(toolName, description, parameters, execute) {
    ctx.tools.register(defineTool({ name: toolName, description, parameters,
      output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
      async execute(args, exec) {
        if (Object.keys(args).some(key => !(key in parameters))) throw new Error('Unknown tool parameter')
        return execute(args, exec)
      } }))
  }
  register('novelatlas_import_text', 'Import a small TXT demo; reuse the UI task ID for long novels.', { text: string('Novel text'), filename: { type: 'string' } }, async (args, exec) => {
    if (!args.text.trim() || Buffer.byteLength(args.text) > 50 * 1024 * 1024) throw new Error('Text is empty or too large')
    const form = new FormData()
    form.append('file', new Blob([args.text], { type: 'text/plain' }), (args.filename || 'harness-demo.txt').replace(/[^a-zA-Z0-9_.\u3400-\u9fff-]/g, '_'))
    const uploaded = await (await request('/api/uploads', { method: 'POST', body: form }, exec.signal)).json()
    await request(`/api/documents/${uploaded.task_id}/parse`, { method: 'POST' }, exec.signal)
    return uploaded
  })
  register('novelatlas_analyze', 'Start or resume a NovelAtlas LangGraph task. Uses server model configuration.', { task_id: task, goal: string('Analysis objective') }, async (args, exec) => {
    const path = taskPath(args.task_id)
    if (!args.goal.trim() || args.goal.length > 1000) throw new Error('Invalid goal')
    const existing = await fetch(new URL(path + '/plan', base), { signal: AbortSignal.any([exec.signal, AbortSignal.timeout(config.timeoutMs)]) })
    if (existing.status === 404) await json(path + '/plan', {}, exec.signal)
    else if (!existing.ok) throw new Error(`NovelAtlas HTTP ${existing.status}`)
    return json(path + '/run', { engine: 'langgraph', goal: args.goal }, exec.signal)
  })
  register('novelatlas_search', 'Retrieve chapter-linked original text using Chinese lexical RAG.', { task_id: task, query: string('Character, event or quote query') }, (args, exec) => json(taskPath(args.task_id) + '/search', { query: args.query, limit: 4 }, exec.signal))
  register('novelatlas_verify', 'Verify an exact quote and its IDs. Does not establish semantic support.', { task_id: task,
    passage_id: string('Retrieved passage ID'), chapter_id: string('Chapter ID'), chunk_id: string('Chunk ID'), quote: string('Exact original quote'), origin: { type: 'string', enum: ['original', 'user_edit'], description: 'Copy origin from the retrieved passage' } }, (args, exec) => {
      const { task_id, ...evidence } = args
      return json(taskPath(task_id) + '/verify', evidence, exec.signal)
    })
  register('novelatlas_task', 'Query task status and optionally the reviewed knowledge report.', { task_id: task, include_report: { type: 'boolean' } }, async (args, exec) => {
    const path = taskPath(args.task_id)
    const status = await (await request(path + '/run', {}, exec.signal)).json()
    if (args.include_report && status.status === 'completed') return { status, report: await (await request(path + '/knowledge', {}, exec.signal)).json() }
    return { status }
  })
  register('novelatlas_cancel', 'Pause a task, retaining its business and graph checkpoints.', { task_id: task }, (args, exec) => json(taskPath(args.task_id) + '/cancel', {}, exec.signal))
  register('novelatlas_export', 'Export the current confirmed outline to a configured local directory.', { task_id: task, format: { type: 'string', enum: ['html', 'docx'], required: true } }, async (args, exec) => {
    const record = await (await request(taskPath(args.task_id) + '/outline', {}, exec.signal)).json()
    const response = await request('/api/exports/outline', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'NovelAtlas 分析报告', format: args.format, outline: record.outline }) }, exec.signal)
    const bytes = Buffer.from(await response.arrayBuffer())
    await mkdir(exportRoot, { recursive: true })
    const filename = join(exportRoot, `${args.task_id}.${args.format}`)
    await writeFile(filename, bytes)
    return { path: filename, bytes: bytes.length, format: args.format }
  })
  ctx.skills.register({ name: 'novelatlas-analyze', source: 'bundled', description: 'Analyze long Chinese novels with planning, RAG evidence review and reports.',
    content: readFileSync(new URL('./skills/analyze.md', import.meta.url), 'utf8') })
}
