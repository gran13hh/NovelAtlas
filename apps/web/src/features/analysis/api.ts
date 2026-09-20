import type {
  AnalysisBudgetConfig,
  BrowserProviderConfig,
} from '../models/api'

export type AnalysisBudget = AnalysisBudgetConfig & {
  request_input_limit_tokens: number
  available_content_tokens: number
}

export type AnalysisSegment = {
  segment_id: string
  chapter_id: string
  chapter_ordinal: number
  chapter_title: string
  part_ordinal: number
  part_count: number
  source_start_char: number
  source_end_char: number
  source_chunk_ids: string[]
  token_count: number
  character_count: number
  content_fingerprint: string
  contains_edited_content: boolean
}

export type AnalysisBatch = {
  batch_id: string
  ordinal: number
  segment_ids: string[]
  chapter_ids: string[]
  chapter_start_ordinal: number
  chapter_end_ordinal: number
  chapter_range_label: string
  source_chunk_ids: string[]
  token_count: number
  character_count: number
  content_fingerprint: string
  contains_edited_content: boolean
}

export type AnalysisPlan = {
  schema_version: 1
  plan_id: string
  task_id: string
  tokenizer: string
  budget: AnalysisBudget
  source_token_count: number
  planned_input_token_count: number
  skipped_empty_chapter_count: number
  segment_count: number
  batch_count: number
  summary_call_count: number
  estimated_merge_call_count: number
  estimated_total_call_count: number
  estimated_merge_input_tokens: number
  estimated_total_input_tokens: number
  estimated_summary_tokens_per_batch: number
  segments: AnalysisSegment[]
  batches: AnalysisBatch[]
}

export type SummaryConfidence = 'certain' | 'likely' | 'uncertain'

export type BatchSummaryClaim = {
  description: string
  chapter_ids: string[]
  source_chunk_ids: string[]
  confidence: SummaryConfidence
}

export type BatchSummaryContent = {
  overview: string
  key_events: BatchSummaryClaim[]
  characters: Array<{
    name: string
    summary: string
    relationship_changes: string[]
    chapter_ids: string[]
    source_chunk_ids: string[]
    confidence: SummaryConfidence
  }>
  worldbuilding: Array<{
    category: string
    name: string
    description: string
    chapter_ids: string[]
    source_chunk_ids: string[]
    confidence: SummaryConfidence
  }>
  foreshadowing: BatchSummaryClaim[]
  unresolved_items: BatchSummaryClaim[]
}

export type BatchSummaryRecord = {
  schema_version: 1
  task_id: string
  plan_id: string
  batch: AnalysisBatch
  source_fingerprint: string
  summary: BatchSummaryContent
  provider: 'mock' | 'openai' | 'deepseek'
  model: string
  completed_at: string
  user_edited_at: string | null
}

export type OutlineSource = {
  input_ids: string[]
  batch_ids: string[]
  chapter_ids: string[]
}

export type OutlineClaim = {
  description: string
  sources: OutlineSource
  confidence: SummaryConfidence
}

export type ChapterRangeOutline = {
  chapter_range: string
  summary: string
  key_events: string[]
  sources: OutlineSource
}

export type NovelOutline = {
  overall_summary: string
  chapter_outline: ChapterRangeOutline[]
  storylines: Array<{
    name: string
    summary: string
    developments: string[]
    sources: OutlineSource
  }>
  characters: Array<{
    name: string
    summary: string
    relationships: string[]
    changes: string[]
    sources: OutlineSource
    confidence: SummaryConfidence
  }>
  worldbuilding: Array<{
    category: string
    name: string
    description: string
    sources: OutlineSource
    confidence: SummaryConfidence
  }>
  foreshadowing: OutlineClaim[]
  unresolved_items: OutlineClaim[]
  conflicts_and_uncertainties: OutlineClaim[]
}

export type FinalOutlineRecord = {
  schema_version: 1
  task_id: string
  plan_id: string
  input_ids: string[]
  source_batch_ids: string[]
  source_chapter_ids: string[]
  outline: NovelOutline
  provider: 'mock' | 'openai' | 'deepseek'
  model: string
  completed_at: string
  user_edited_at: string | null
}

export type AnalysisTaskError = {
  code: string
  message: string
  retryable: boolean
  batch_id: string | null
  merge_node_id: string | null
}

export type BatchCheckpoint = {
  batch_id: string
  ordinal: number
  status: 'pending' | 'running' | 'completed' | 'failed'
  attempt_count: number
}

export type MergeCheckpoint = {
  node_id: string
  level: number
  input_ids: string[]
  status: 'pending' | 'running' | 'completed' | 'failed'
  attempt_count: number
}

export type AnalysisTaskManifest = {
  engine?: 'baseline' | 'langgraph'
  analysis_goal?: string
  agent_concurrency?: number
  task_id: string
  plan_id: string
  status:
    | 'queued'
    | 'running'
    | 'failed'
    | 'interrupted'
    | 'batch_summaries_completed'
    | 'merging'
    | 'finalizing'
    | 'completed'
  provider: 'mock' | 'openai' | 'deepseek'
  model: string
  batch_count: number
  completed_batch_count: number
  current_batch_id: string | null
  batches: BatchCheckpoint[]
  merge_node_count: number
  completed_merge_node_count: number
  current_merge_node_id: string | null
  merge_nodes: MergeCheckpoint[]
  final_outline_status: 'pending' | 'running' | 'completed' | 'failed'
  final_outline_attempt_count: number
  error: AnalysisTaskError | null
}

export type AnalysisProgressSnapshot = {
  event_id: string
  task_id: string
  status: AnalysisTaskManifest['status']
  phase:
    | 'queued'
    | 'batch_summary'
    | 'hierarchical_merge'
    | 'final_outline'
    | 'completed'
    | 'failed'
    | 'interrupted'
  completed_batch_count: number
  batch_count: number
  current_batch_id: string | null
  current_batch_ordinal: number | null
  completed_merge_node_count: number
  merge_node_count: number
  current_merge_node_id: string | null
  current_merge_level: number | null
  final_outline_status: AnalysisTaskManifest['final_outline_status']
  error: AnalysisTaskError | null
  terminal: boolean
  updated_at: string
}

function responseDetail(payload: unknown, fallback: string): string {
  if (typeof payload !== 'object' || payload === null || !('detail' in payload)) {
    return fallback
  }
  if (typeof payload.detail === 'string') return payload.detail
  if (Array.isArray(payload.detail)) {
    const first = payload.detail[0] as unknown
    if (
      typeof first === 'object' &&
      first !== null &&
      'msg' in first &&
      typeof first.msg === 'string'
    ) {
      return first.msg
    }
  }
  return fallback
}

export async function createAnalysisPlan(
  taskId: string,
  budget: AnalysisBudgetConfig,
): Promise<AnalysisPlan> {
  const response = await fetch(`/api/analyses/${taskId}/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ budget }),
  })
  if (response.ok) return response.json() as Promise<AnalysisPlan>
  const payload = (await response.json().catch(() => null)) as unknown
  throw new Error(responseDetail(payload, `批次规划失败（${response.status}）`))
}

export function fetchAnalysisPlan(taskId: string): Promise<AnalysisPlan> {
  return jsonRequest(`/api/analyses/${taskId}/plan`)
}

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (response.ok) return response.json() as Promise<T>
  const payload = (await response.json().catch(() => null)) as unknown
  throw new Error(responseDetail(payload, `请求失败（${response.status}）`))
}

export function startAnalysis(
  taskId: string,
  config: BrowserProviderConfig,
  engine: 'baseline' | 'langgraph' = 'baseline',
  goal = '分析跨章节事件、人物别名与关系变化、世界观及证据冲突',
): Promise<AnalysisTaskManifest> {
  return jsonRequest(`/api/analyses/${taskId}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config, engine, goal }),
  })
}

export function fetchAnalysisStatus(taskId: string): Promise<AnalysisTaskManifest> {
  return jsonRequest(`/api/analyses/${taskId}/run`)
}

export function cancelAnalysis(taskId: string): Promise<AnalysisTaskManifest> {
  return jsonRequest(`/api/analyses/${taskId}/cancel`, { method: 'POST' })
}

export function fetchBatchSummaries(taskId: string): Promise<BatchSummaryRecord[]> {
  return jsonRequest(`/api/analyses/${taskId}/summaries`)
}

export function fetchFinalOutline(taskId: string): Promise<FinalOutlineRecord> {
  return jsonRequest(`/api/analyses/${taskId}/outline`)
}

export function updateBatchSummary(
  taskId: string,
  batchId: string,
  summary: BatchSummaryContent,
): Promise<BatchSummaryRecord> {
  return jsonRequest(`/api/analyses/${taskId}/summaries/${batchId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ summary }),
  })
}

export function updateFinalOutline(
  taskId: string,
  outline: NovelOutline,
): Promise<FinalOutlineRecord> {
  return jsonRequest(`/api/analyses/${taskId}/outline`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ outline }),
  })
}

export function subscribeAnalysisProgress(
  taskId: string,
  onSnapshot: (snapshot: AnalysisProgressSnapshot) => void,
  onConnectionError: () => void,
): () => void {
  const source = new EventSource(`/api/analyses/${taskId}/events`)
  const receive = (event: Event) => {
    const message = event as MessageEvent<string>
    const snapshot = JSON.parse(message.data) as AnalysisProgressSnapshot
    onSnapshot(snapshot)
    if (snapshot.terminal) source.close()
  }
  source.addEventListener('analysis.progress', receive)
  source.addEventListener('analysis.completed', receive)
  source.addEventListener('analysis.error', receive)
  source.onerror = onConnectionError
  return () => source.close()
}
