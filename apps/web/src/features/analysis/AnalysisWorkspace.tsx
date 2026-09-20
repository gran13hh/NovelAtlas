import { AgentPanel } from './AgentPanel'
import { useCallback, useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'

import { loadBrowserModelConfig } from '../models/storage'
import { ExportPanel } from '../export/ExportPanel'
import { AnalysisPlanPanel } from './AnalysisPlanPanel'
import {
  cancelAnalysis,
  fetchAnalysisPlan,
  fetchAnalysisStatus,
  fetchBatchSummaries,
  fetchFinalOutline,
  startAnalysis,
  subscribeAnalysisProgress,
  updateBatchSummary,
  updateFinalOutline,
  type AnalysisPlan,
  type AnalysisProgressSnapshot,
  type AnalysisTaskManifest,
  type BatchSummaryContent,
  type BatchSummaryRecord,
  type FinalOutlineRecord,
  type NovelOutline,
  type OutlineClaim,
} from './api'
import { StructuredEditor } from './StructuredEditor'

type AnalysisWorkspaceProps = {
  taskId: string
  title: string
  onStateChange?: (state: AnalysisWorkspaceState) => void
}

export type AnalysisWorkspaceState = {
  plan: AnalysisPlan | null
  manifest: AnalysisTaskManifest | null
  summaries: BatchSummaryRecord[]
  outline: FinalOutlineRecord | null
}

const number = new Intl.NumberFormat('zh-CN')

const phaseLabels: Record<AnalysisProgressSnapshot['phase'], string> = {
  queued: '等待后台任务',
  batch_summary: '逐批概括原文',
  hierarchical_merge: '分层汇总概括',
  final_outline: '生成最终细纲',
  completed: '全书细纲已完成',
  failed: '分析遇到错误',
  interrupted: '分析已暂停',
}

function isActive(status: AnalysisTaskManifest['status'] | undefined): boolean {
  return Boolean(
    status &&
      ['queued', 'running', 'batch_summaries_completed', 'merging', 'finalizing'].includes(
        status,
      ),
  )
}

function estimatedRemainingCalls(
  plan: AnalysisPlan,
  manifest: AnalysisTaskManifest | null,
): number {
  if (!manifest) return plan.estimated_total_call_count
  if (manifest.status === 'completed') return 0

  const remainingBatches = manifest.batches.length
    ? manifest.batches.filter((item) => item.status !== 'completed').length
    : Math.max(0, manifest.batch_count - manifest.completed_batch_count)
  const pendingKnownMerges = manifest.merge_nodes.filter(
    (item) => item.status !== 'completed',
  ).length

  let undiscoveredMergeGroups = 0
  const levels = [...new Set(manifest.merge_nodes.map((item) => item.level))]
  for (const level of levels) {
    const availableInputIds = level === 1
      ? plan.batches.map((batch) => batch.batch_id)
      : manifest.merge_nodes
          .filter((item) => item.level === level - 1 && item.status === 'completed')
          .map((item) => item.node_id)
    const coveredInputIds = new Set(
      manifest.merge_nodes
        .filter((item) => item.level === level)
        .flatMap((item) => item.input_ids),
    )
    if (availableInputIds.some((inputId) => !coveredInputIds.has(inputId))) {
      // Checkpoints are created sequentially. Uncovered inputs therefore mean
      // at least one more group at this already-discovered hierarchy level.
      undiscoveredMergeGroups += 1
    }
  }

  const finalOutlineCall = manifest.final_outline_status === 'completed' ? 0 : 1
  const plannedHierarchyCalls = Math.max(
    0,
    plan.estimated_merge_call_count
      - manifest.completed_merge_node_count
      - (manifest.final_outline_status === 'completed' ? 1 : 0),
  )
  const knownHierarchyCalls =
    pendingKnownMerges + undiscoveredMergeGroups + finalOutlineCall

  return remainingBatches + Math.max(plannedHierarchyCalls, knownHierarchyCalls)
}

function ClaimList({ items }: { items: OutlineClaim[] }) {
  if (items.length === 0) return <p className="text-sm text-black/35">暂无明确内容</p>
  return (
    <ul className="space-y-2">
      {items.map((item, index) => (
        <li key={`${item.description}-${index}`} className="rounded-lg bg-black/[0.025] px-3 py-2 text-sm leading-6 text-black/62">
          {item.description}
          {item.confidence !== 'certain' && (
            <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800">
              {item.confidence === 'likely' ? '可能' : '不确定'}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

function BatchSummaryCard({
  record,
  taskId,
  onUpdated,
}: {
  record: BatchSummaryRecord
  taskId: string
  onUpdated: (record: BatchSummaryRecord) => void
}) {
  const [saving, setSaving] = useState(false)
  return (
    <details className="group rounded-xl border border-black/8 bg-white/75 p-4">
      <summary className="flex cursor-pointer list-none items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.14em] text-[#55705e]">
            批次 {record.batch.ordinal} · {record.batch.chapter_range_label}
          </p>
          <p className="mt-2 text-sm leading-6 text-black/62">{record.summary.overview}</p>
        </div>
        <span className="text-black/30 transition group-open:rotate-45">＋</span>
      </summary>
      <div className="mt-4 grid gap-3 border-t border-black/8 pt-4 md:grid-cols-2">
        {[
          ['关键事件', record.summary.key_events.map((item) => item.description)],
          ['人物变化', record.summary.characters.map((item) => `${item.name}：${item.summary}`)],
          ['世界观', record.summary.worldbuilding.map((item) => `${item.name}：${item.description}`)],
          ['伏笔与待解', [...record.summary.foreshadowing, ...record.summary.unresolved_items].map((item) => item.description)],
        ].map(([label, items]) => (
          <div key={label as string} className="rounded-lg bg-[#f3f1ea] p-3">
            <h4 className="text-xs font-bold text-black/45">{label as string}</h4>
            {(items as string[]).length ? (
              <ul className="mt-2 space-y-1 text-sm leading-5 text-black/58">
                {(items as string[]).map((item, index) => <li key={`${item}-${index}`}>· {item}</li>)}
              </ul>
            ) : <p className="mt-2 text-xs text-black/30">本批次未提取到</p>}
          </div>
        ))}
      </div>
      {record.user_edited_at && <p className="mt-3 text-xs text-amber-700">已人工修正</p>}
      <StructuredEditor
        label="编辑这个批次的完整概括"
        value={record.summary}
        isSaving={saving}
        onSave={async (value) => {
          setSaving(true)
          try {
            const updated = await updateBatchSummary(
              taskId,
              record.batch.batch_id,
              value as BatchSummaryContent,
            )
            onUpdated(updated)
          } finally {
            setSaving(false)
          }
        }}
      />
    </details>
  )
}

function OutlineView({
  record,
  taskId,
  onUpdated,
}: {
  record: FinalOutlineRecord
  taskId: string
  onUpdated: (record: FinalOutlineRecord) => void
}) {
  const [saving, setSaving] = useState(false)
  const outline = record.outline
  return (
    <div className="space-y-5">
      <article className="rounded-2xl bg-[#24382c] p-5 text-white md:p-7">
        <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#b7caae]">总体概述</p>
        <p className="mt-3 font-serif text-lg leading-8 text-white/85">{outline.overall_summary}</p>
        <p className="mt-4 text-xs text-white/38">
          {record.model} · 覆盖 {number.format(record.source_batch_ids.length)} 个批次
          {record.user_edited_at ? ' · 已人工修正' : ''}
        </p>
      </article>

      <section>
        <h3 className="font-serif text-xl font-semibold text-[#17221b]">章节范围细纲</h3>
        <div className="mt-3 space-y-2">
          {outline.chapter_outline.map((item, index) => (
            <article key={`${item.chapter_range}-${index}`} className="rounded-xl border border-black/8 bg-white/75 p-4">
              <p className="text-xs font-bold text-[#55705e]">{item.chapter_range}</p>
              <p className="mt-2 text-sm leading-6 text-black/62">{item.summary}</p>
              {item.key_events.length > 0 && <p className="mt-2 text-xs leading-5 text-black/42">{item.key_events.join(' · ')}</p>}
            </article>
          ))}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-2xl border border-black/8 bg-white/65 p-5">
          <h3 className="font-serif text-lg font-semibold">主要故事线</h3>
          <div className="mt-3 space-y-3">
            {outline.storylines.map((item, index) => (
              <div key={`${item.name}-${index}`}>
                <p className="text-sm font-semibold text-[#31533f]">{item.name}</p>
                <p className="mt-1 text-sm leading-6 text-black/58">{item.summary}</p>
              </div>
            ))}
            {outline.storylines.length === 0 && <p className="text-sm text-black/35">暂无明确故事线</p>}
          </div>
        </section>
        <section className="rounded-2xl border border-black/8 bg-white/65 p-5">
          <h3 className="font-serif text-lg font-semibold">主要人物与关系</h3>
          <div className="mt-3 space-y-3">
            {outline.characters.map((item, index) => (
              <div key={`${item.name}-${index}`}>
                <p className="text-sm font-semibold text-[#31533f]">{item.name}</p>
                <p className="mt-1 text-sm leading-6 text-black/58">{item.summary}</p>
                {[...item.relationships, ...item.changes].length > 0 && <p className="mt-1 text-xs leading-5 text-black/40">{[...item.relationships, ...item.changes].join(' · ')}</p>}
              </div>
            ))}
            {outline.characters.length === 0 && <p className="text-sm text-black/35">暂无主要人物归纳</p>}
          </div>
        </section>
        <section className="rounded-2xl border border-black/8 bg-white/65 p-5">
          <h3 className="font-serif text-lg font-semibold">世界观</h3>
          <div className="mt-3 space-y-3">
            {outline.worldbuilding.map((item, index) => (
              <div key={`${item.name}-${index}`}>
                <p className="text-sm font-semibold text-[#31533f]">{item.name}</p>
                <p className="mt-1 text-sm leading-6 text-black/58">{item.description}</p>
              </div>
            ))}
            {outline.worldbuilding.length === 0 && <p className="text-sm text-black/35">暂无明确世界观条目</p>}
          </div>
        </section>
        <section className="rounded-2xl border border-black/8 bg-white/65 p-5">
          <h3 className="font-serif text-lg font-semibold">伏笔与不确定项</h3>
          <div className="mt-3">
            <ClaimList items={[...outline.foreshadowing, ...outline.unresolved_items, ...outline.conflicts_and_uncertainties]} />
          </div>
        </section>
      </div>

      <StructuredEditor
        label="编辑完整全书细纲"
        value={outline}
        isSaving={saving}
        onSave={async (value) => {
          setSaving(true)
          try {
            onUpdated(await updateFinalOutline(taskId, value as NovelOutline))
          } finally {
            setSaving(false)
          }
        }}
      />
    </div>
  )
}

export function AnalysisWorkspace({
  taskId,
  title,
  onStateChange,
}: AnalysisWorkspaceProps) {
  const [engine, setEngine] = useState<'baseline' | 'langgraph'>('langgraph')
  const [goal, setGoal] = useState('分析跨章节事件、人物别名与关系变化、世界观及证据冲突')
  const [plan, setPlan] = useState<AnalysisPlan | null>(null)
  const [manifest, setManifest] = useState<AnalysisTaskManifest | null>(null)
  const [progress, setProgress] = useState<AnalysisProgressSnapshot | null>(null)
  const [summaries, setSummaries] = useState<BatchSummaryRecord[]>([])
  const [outline, setOutline] = useState<FinalOutlineRecord | null>(null)
  const [resultTab, setResultTab] = useState<'outline' | 'summaries'>('outline')
  const [connectionMessage, setConnectionMessage] = useState<string | null>(null)
  const [resultMessage, setResultMessage] = useState<string | null>(null)
  const [isHydrated, setIsHydrated] = useState(false)

  useEffect(() => {
    if (isHydrated) {
      onStateChange?.({ plan, manifest, summaries, outline })
    }
  }, [isHydrated, manifest, onStateChange, outline, plan, summaries])

  const loadResults = useCallback(async () => {
    const [status, batchResults] = await Promise.all([
      fetchAnalysisStatus(taskId),
      fetchBatchSummaries(taskId),
    ])
    setManifest(status)
    setSummaries(batchResults)
    if (status.status === 'completed') {
      setOutline(await fetchFinalOutline(taskId))
    }
  }, [taskId])

  useEffect(() => {
    let current = true
    fetchAnalysisPlan(taskId)
      .then(async (savedPlan) => {
        if (!current) return
        setPlan(savedPlan)
        try {
          const savedStatus = await fetchAnalysisStatus(taskId)
          if (!current) return
          setManifest(savedStatus)
          setEngine(savedStatus.engine ?? 'baseline')
          setGoal(savedStatus.analysis_goal ?? '分析跨章节事件、人物别名与关系变化、世界观及证据冲突')
          if (savedStatus.completed_batch_count > 0) {
            await loadResults()
          }
        } catch {
          // A valid plan may exist before analysis has been started.
        }
      })
      .catch(() => {
        // Planning is an explicit user action when no saved plan exists.
      })
      .finally(() => {
        if (current) setIsHydrated(true)
      })
    return () => {
      current = false
    }
  }, [loadResults, taskId])

  const run = useMutation({
    mutationFn: (config: ReturnType<typeof loadBrowserModelConfig>['text']) =>
      startAnalysis(taskId, config, engine, goal),
    onMutate: () => {
      setConnectionMessage(null)
      setResultMessage(null)
    },
    onSuccess: (value) => {
      setManifest(value)
      setProgress(null)
    },
  })

  const cancel = useMutation({
    mutationFn: () => cancelAnalysis(taskId),
    onSuccess: setManifest,
  })

  const active = isActive(manifest?.status)
  useEffect(() => {
    if (!active) return
    return subscribeAnalysisProgress(
      taskId,
      (snapshot) => {
        setProgress(snapshot)
        setManifest((current) =>
          current
            ? {
                ...current,
                status: snapshot.status,
                completed_batch_count: snapshot.completed_batch_count,
                current_batch_id: snapshot.current_batch_id,
                merge_node_count: snapshot.merge_node_count,
                completed_merge_node_count:
                  snapshot.completed_merge_node_count,
                current_merge_node_id: snapshot.current_merge_node_id,
                final_outline_status: snapshot.final_outline_status,
                error: snapshot.error,
              }
            : current,
        )
        setConnectionMessage(null)
        if (snapshot.terminal) {
          void loadResults().catch((error: unknown) =>
            setResultMessage(error instanceof Error ? error.message : '读取结果失败'),
          )
        }
      },
      () => setConnectionMessage('实时进度连接暂时中断，浏览器将自动重连。'),
    )
  }, [active, loadResults, taskId])

  const shownBatchCount = progress?.batch_count ?? manifest?.batch_count ?? plan?.batch_count ?? 0
  const shownCompletedBatches = progress?.completed_batch_count ?? manifest?.completed_batch_count ?? 0
  const completion = shownBatchCount > 0 ? Math.round((shownCompletedBatches / shownBatchCount) * 100) : 0
  const phase = progress ? phaseLabels[progress.phase] : manifest ? manifest.status : '尚未开始'
  const error = progress?.error ?? manifest?.error

  const modelConfig = loadBrowserModelConfig()
  const modelLabel = `${modelConfig.text.provider === 'mock' ? 'Mock' : '真实接口'} · ${modelConfig.text.model}`
  const remainingCalls = plan ? estimatedRemainingCalls(plan, manifest) : 0
  const callEstimateLabel = manifest
    ? `预计剩余至少 ${number.format(remainingCalls)} 次调用`
    : `预计 ${number.format(remainingCalls)} 次调用`
  const beginAnalysis = () => {
    if (!plan) return
    const config = loadBrowserModelConfig()
    if (
      config.text.provider !== 'mock' &&
      !window.confirm(
        manifest
          ? `将使用 ${config.text.model} 从断点继续，预计还需至少 ${remainingCalls} 次模型调用。汇总调用数可能随实际输出长度增加，并可能产生费用。是否继续？`
          : `将使用 ${config.text.model} 发起约 ${remainingCalls} 次模型调用，可能产生费用。是否继续？`,
      )
    ) {
      return
    }
    run.mutate(config.text)
  }

  return (
    <section id="analysis-workspace" className="mt-4">
      <AnalysisPlanPanel taskId={taskId} existingPlan={plan} onPlanCreated={(value) => {
        setPlan(value)
        setManifest(null)
        setProgress(null)
        setSummaries([])
        setOutline(null)
      }} />

      {engine === 'langgraph' && manifest && <AgentPanel taskId={taskId} active={active} />}
      {plan && (
        <section className="mt-4 overflow-hidden rounded-2xl border border-[#31533f]/20 bg-white/70 shadow-[0_16px_40px_rgba(49,83,63,0.06)]">
          <div className="p-5 md:p-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#55705e]">Stage 6 · 分析执行</p>
                <h2 className="mt-2 font-serif text-2xl font-semibold text-[#17221b]">确认预算后生成全书细纲</h2>
                <p className="mt-2 text-sm text-black/45">{modelLabel} · {callEstimateLabel}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {active && (
                  <button type="button" onClick={() => cancel.mutate()} disabled={cancel.isPending} className="rounded-xl border border-rose-900/10 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700 disabled:opacity-50">
                    {cancel.isPending ? '正在暂停…' : '暂停并保留进度'}
                  </button>
                )}
                <button type="button" onClick={beginAnalysis} disabled={active || run.isPending} className="rounded-xl bg-[#1e3227] px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-[#294535] disabled:cursor-not-allowed disabled:opacity-45">
                  {run.isPending ? '正在提交…' : manifest?.status === 'failed' || manifest?.status === 'interrupted' || manifest?.status === 'batch_summaries_completed' ? '从断点继续' : manifest?.status === 'completed' ? '分析已完成' : '确认并开始分析'}
                </button>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-3">
              <label className="text-sm">分析模式 <select aria-label="分析模式" disabled={active} value={engine} onChange={e => setEngine(e.target.value as 'baseline' | 'langgraph')} className="rounded-lg border border-black/15 px-2 py-2"><option value="langgraph">Agent 分析与核验</option><option value="baseline">基线：批次概括与细纲</option></select></label>
              {engine === 'langgraph' && <input aria-label="分析目标" disabled={active} value={goal} maxLength={1000} onChange={e => setGoal(e.target.value)} className="min-w-60 flex-1 rounded-lg border border-black/15 px-3 py-2 text-sm"/>}
            </div>
            {engine === 'langgraph' && <p className="mt-2 text-xs text-black/45">语义规划、专项分析与核验会增加模型调用；Token 预算规划中的原估算仅覆盖基线流程。</p>}
            {manifest && (
              <div className="mt-5 rounded-xl bg-[#f3f1ea] p-4" aria-live="polite">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="font-semibold text-[#31533f]">{phase}</span>
                  <span className="font-mono text-xs text-black/40">{shownCompletedBatches} / {shownBatchCount} 批</span>
                </div>
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-black/8">
                  <div className="h-full rounded-full bg-[#55705e] transition-[width]" style={{ width: `${completion}%` }} />
                </div>
                {progress?.phase === 'hierarchical_merge' && <p className="mt-2 text-xs text-black/40">正在处理第 {progress.current_merge_level ?? '—'} 层 · 已完成 {progress.completed_merge_node_count}/{progress.merge_node_count} 个已发现节点</p>}
                {connectionMessage && <p className="mt-2 text-xs text-amber-700">{connectionMessage}</p>}
              </div>
            )}

            {(run.error || error || resultMessage) && (
              <p className="mt-4 rounded-xl border border-rose-900/10 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                {run.error instanceof Error ? run.error.message : error?.message ?? resultMessage}
              </p>
            )}
          </div>

          {(summaries.length > 0 || outline) && (
            <div className="border-t border-black/8 p-5 md:p-6">
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" onClick={() => setResultTab('outline')} disabled={!outline} className={`rounded-full px-4 py-2 text-xs font-semibold ${resultTab === 'outline' ? 'bg-[#1e3227] text-white' : 'bg-black/5 text-black/50'} disabled:opacity-35`}>全书细纲</button>
                <button type="button" onClick={() => setResultTab('summaries')} className={`rounded-full px-4 py-2 text-xs font-semibold ${resultTab === 'summaries' ? 'bg-[#1e3227] text-white' : 'bg-black/5 text-black/50'}`}>批次概括 · {summaries.length}</button>
              </div>
              <div className="mt-5">
                {resultTab === 'outline' && outline ? (
                  <>
                    <OutlineView record={outline} taskId={taskId} onUpdated={(updated) => {
                      setOutline(updated)
                      setResultMessage('全书细纲的人工修正已保存。')
                    }} />
                    <ExportPanel title={title} outline={outline.outline} />
                  </>
                ) : (
                  <div className="space-y-3">
                    {summaries.map((record) => (
                      <BatchSummaryCard key={record.batch.batch_id} record={record} taskId={taskId} onUpdated={(updated) => {
                        setSummaries((current) => current.map((item) => item.batch.batch_id === updated.batch.batch_id ? updated : item))
                        setOutline(null)
                        setManifest((current) => current ? { ...current, status: 'batch_summaries_completed', final_outline_status: 'pending' } : current)
                        setResultMessage('批次概括已保存；上层细纲已作废，请点击“从断点继续”重新汇总。')
                      }} />
                    ))}
                  </div>
                )}
              </div>
              {resultMessage && <p className="mt-4 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{resultMessage}</p>}
            </div>
          )}
        </section>
      )}
    </section>
  )
}
