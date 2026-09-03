import type { AnalysisBudgetConfig } from '../models/api'

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
