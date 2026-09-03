import { useMutation } from '@tanstack/react-query'

import { loadBrowserModelConfig } from '../models/storage'
import { createAnalysisPlan } from './api'

type AnalysisPlanPanelProps = {
  taskId: string
}

const number = new Intl.NumberFormat('zh-CN')

export function AnalysisPlanPanel({ taskId }: AnalysisPlanPanelProps) {
  const planning = useMutation({
    mutationFn: () => {
      const config = loadBrowserModelConfig()
      return createAnalysisPlan(taskId, config.analysis_budget)
    },
  })
  const plan = planning.data

  return (
    <section className="mt-4 overflow-hidden rounded-2xl border border-[#31533f]/20 bg-white/70 shadow-[0_16px_40px_rgba(49,83,63,0.06)]">
      <div className="p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#55705e]">
              Stage 5B · 批次规划
            </p>
            <h2 className="mt-2 font-serif text-xl font-semibold text-[#17221b]">
              预估需要多少次模型调用
            </h2>
            <p className="mt-2 max-w-xl text-sm leading-6 text-black/48">
              使用浏览器中已保存的 Token 预算组合相邻章节。该步骤只在本地后端计算，不会调用模型，也不会产生 API 费用。
            </p>
          </div>
          <button
            type="button"
            onClick={() => planning.mutate()}
            disabled={planning.isPending}
            className="shrink-0 rounded-xl bg-[#1e3227] px-5 py-3 text-sm font-semibold text-white shadow-[0_10px_30px_rgba(30,50,39,0.16)] transition hover:bg-[#294535] disabled:cursor-wait disabled:opacity-60"
          >
            {planning.isPending
              ? '正在规划…'
              : plan
                ? '按当前预算重新规划'
                : '规划分析批次'}
          </button>
        </div>

        {planning.error instanceof Error && (
          <p className="mt-4 rounded-xl border border-rose-900/10 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {planning.error.message}
          </p>
        )}
      </div>

      {plan && (
        <div className="border-t border-black/8">
          <dl className="grid grid-cols-2 gap-px bg-black/8 sm:grid-cols-4">
            {[
              ['可用正文 / 批', `${number.format(plan.budget.available_content_tokens)} Token`],
              ['概括调用', `${number.format(plan.summary_call_count)} 次`],
              ['预计汇总调用', `${number.format(plan.estimated_merge_call_count)} 次`],
              ['预计总调用', `${number.format(plan.estimated_total_call_count)} 次`],
            ].map(([label, value]) => (
              <div key={label} className="bg-[#f8f7f2] p-4">
                <dt className="text-[11px] font-semibold text-black/38">{label}</dt>
                <dd className="mt-1.5 font-mono text-sm font-semibold text-[#1e3227]">
                  {value}
                </dd>
              </div>
            ))}
          </dl>

          <div className="grid gap-4 border-b border-black/8 p-5 text-xs leading-5 text-black/48 sm:grid-cols-3">
            <p>
              <span className="block font-semibold text-black/65">计划输入</span>
              {number.format(plan.planned_input_token_count)} Token，分为{' '}
              {number.format(plan.segment_count)} 个无重叠片段。
            </p>
            <p>
              <span className="block font-semibold text-black/65">含汇总预估</span>
              总输入约 {number.format(plan.estimated_total_input_tokens)} Token；实际用量以模型返回为准。
            </p>
            <p>
              <span className="block font-semibold text-black/65">空章节处理</span>
              跳过 {number.format(plan.skipped_empty_chapter_count)} 个无正文标题块，不为其单独发起请求。
            </p>
          </div>

          <div className="p-5">
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-serif text-lg font-semibold text-[#17221b]">
                {number.format(plan.batch_count)} 个原文批次
              </h3>
              <span className="font-mono text-[10px] text-black/28">
                {plan.plan_id}
              </span>
            </div>

            {plan.batches.length === 0 ? (
              <p className="mt-4 rounded-xl border border-dashed border-black/12 px-4 py-3 text-sm text-black/42">
                当前解析清单中没有可用于分析的正文，请检查是否删除了全部文本块。
              </p>
            ) : (
              <div className="mt-4 max-h-80 space-y-2 overflow-y-auto pr-1">
                {plan.batches.map((batch) => (
                  <div
                    key={batch.batch_id}
                    className="flex flex-col gap-2 rounded-xl border border-black/8 bg-[#f8f7f2] p-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div>
                      <p className="text-sm font-semibold text-[#17221b]">
                        批次 {batch.ordinal} · {batch.chapter_range_label}
                      </p>
                      <p className="mt-1 text-xs text-black/38">
                        {batch.segment_ids.length} 个片段 · {batch.source_chunk_ids.length} 个来源文本块
                        {batch.contains_edited_content ? ' · 含用户编辑内容' : ''}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-lg bg-[#e4ebe0] px-2.5 py-1.5 font-mono text-xs font-semibold text-[#31533f]">
                      {number.format(batch.token_count)} Token
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
