import { useEffect, useState } from 'react'

type TraceRow = {
  time: string; kind: string; node?: string; status?: string; tool?: string;
  duration_ms?: number; estimated_input_tokens?: number;
  measured_usage?: { input_tokens: number | null; output_tokens: number | null; total_tokens: number | null } | null;
  observation?: { quote_valid?: boolean; count?: number };
}
type Plan = { mode: string; goal: string; tasks: { task_id: string; role: string; objective: string; depends_on: string[]; expected_artifact: string }[] }
type Passage = { passage_id: string; chapter_id: string; chunk_id: string; content: string; origin: string }
type Report = { entities: Record<string, string[]>; conflicts: string[]; domains: { task_id: string; items: { subject: string; description: string; classification: string; evidence: { quote: string; chapter_id: string; origin?: string }[] }[] }[] }

export function AgentPanel({ taskId, active }: { taskId: string; active: boolean }) {
  const [trace, setTrace] = useState<TraceRow[]>([])
  const [plan, setPlan] = useState<Plan | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [query, setQuery] = useState('')
  const [passages, setPassages] = useState<Passage[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    async function refresh() {
      const paths = ['trace', 'semantic-plan', 'knowledge']
      const results = await Promise.allSettled(paths.map(async p => {
        const r = await fetch(`/api/analyses/${taskId}/${p}`, { signal: controller.signal })
        return r.ok ? r.json() : null
      }))
      if (controller.signal.aborted) return
      if (results[0].status === 'fulfilled') setTrace(results[0].value ?? [])
      if (results[1].status === 'fulfilled') setPlan(results[1].value)
      if (results[2].status === 'fulfilled') setReport(results[2].value)
    }
    void refresh()
    const timer = active ? window.setInterval(() => void refresh(), 2000) : undefined
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [taskId, active])
  const measured = trace.reduce((n, r) => n + (r.measured_usage?.total_tokens ?? 0), 0)
  const estimated = trace.reduce((n, r) => n + (r.estimated_input_tokens ?? 0), 0)
  async function search() {
    setError('')
    try {
      const r = await fetch(`/api/analyses/${taskId}/search`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query, limit: 4 }) })
      if (!r.ok) throw new Error('检索失败，请确认任务尚未过期且已解析')
      setPassages(await r.json())
    } catch (e) { setError(e instanceof Error ? e.message : '检索失败') }
  }
  return <section className="mt-4 rounded-2xl border border-black/10 bg-white/70 p-5">
    <h3 className="font-serif text-xl">任务计划与证据核验</h3>
    {plan && <><p className="mt-2 text-sm text-black/50">{plan.goal} · {plan.mode === 'mock' ? 'Mock 演示计划' : '模型语义计划'}</p>
      <ul className="mt-3 space-y-2">{plan.tasks.map(t => <li key={t.task_id} className="text-sm"><strong>{t.objective}</strong> · 依赖：{t.depends_on.join('、') || '无'} · 产物：{t.expected_artifact}</li>)}</ul></>}
    <p className="mt-3 text-xs text-black/50">调用 {trace.filter(r => r.kind === 'model').length} 次 · 输入 Token 估算 {estimated} · 供应商实测总 Token {measured || '暂无'} · 工具调用 {trace.filter(r => r.kind === 'tool').length} 次</p>
    <details className="mt-3"><summary className="cursor-pointer text-sm">执行记录</summary><div className="mt-2 max-h-60 overflow-auto text-xs">{trace.filter(r => r.kind !== 'model').map((r, i) => <p key={i}>{r.time.slice(11, 19)} · {r.node || r.tool || r.kind} · {r.status || ''} {r.duration_ms === undefined ? '' : `${r.duration_ms}ms`}</p>)}</div></details>
    {report && <div className="mt-4 space-y-3">{report.domains.map(d => <div key={d.task_id}>{d.items.map((item, i) => <div key={i} className="mt-2 rounded-xl bg-[#f3f1ea] p-3"><p className="text-sm"><strong>{item.subject}</strong> · {item.classification === 'fact' ? item.evidence.some(e => e.origin === 'user_edit') ? '修订文本事实' : '原文事实' : item.classification === 'inference' ? '模型推断' : '不确定'}</p><p className="text-sm">{item.description}</p>{item.evidence.map((e, j) => <blockquote key={j} className="mt-1 text-xs text-black/50">{e.chapter_id}：{e.quote}</blockquote>)}</div>)}</div>)}{report.conflicts.map((c, i) => <p key={i} className="text-sm text-amber-800">{c}</p>)}</div>}
    <div className="mt-4 flex gap-2"><input aria-label="原文检索" value={query} onChange={e => setQuery(e.target.value)} maxLength={200} placeholder="检索人物、事件或原句" className="min-w-0 flex-1 rounded-xl border border-black/15 px-3 py-2"/><button type="button" onClick={() => void search()} disabled={!query.trim()} className="rounded-xl bg-[#31533f] px-4 text-sm text-white disabled:opacity-40">检索原文</button></div>
    {error && <p className="mt-2 text-sm text-red-700">{error}</p>}{passages.map(p => <blockquote key={p.passage_id} className="mt-3 rounded-xl bg-[#f3f1ea] p-3 text-sm"><p className="mb-1 text-xs text-black/40">{p.chapter_id} · {p.origin === 'user_edit' ? '人工修订文本' : '原文'}</p>{p.content}</blockquote>)}
  </section>
}
