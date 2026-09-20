import { useMemo, useState } from 'react'

import { ChunkEditor } from './ChunkEditor'
import type { ParsedDocument } from './api'

type ParsePreviewProps = {
  error: string | null
  isParsing: boolean
  result: ParsedDocument | null
  onResultChange: (result: ParsedDocument) => void
  onParse: () => void
}

const number = new Intl.NumberFormat('zh-CN')

export function ParsePreview({
  error,
  isParsing,
  result,
  onResultChange,
  onParse,
}: ParsePreviewProps) {
  const [editingChunkId, setEditingChunkId] = useState<string | null>(null)
  const chunkById = useMemo(
    () => new Map(result?.chunks.map((chunk) => [chunk.chunk_id, chunk]) ?? []),
    [result],
  )

  if (!result) {
    return (
      <section className="mt-4 rounded-2xl border border-black/10 bg-white/55 p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#55705e]">
              下一步 · 结构解析
            </p>
            <h2 className="mt-2 font-serif text-xl font-semibold text-[#17221b]">
              识别章节并建立原文坐标
            </h2>
            <p className="mt-2 text-sm leading-6 text-black/48">
              本步骤不调用大模型；结果随当前后端临时任务一起清理。
            </p>
          </div>
          <button
            type="button"
            onClick={onParse}
            disabled={isParsing}
            className="shrink-0 rounded-xl bg-[#1e3227] px-5 py-3 text-sm font-semibold text-white shadow-[0_10px_30px_rgba(30,50,39,0.16)] transition hover:bg-[#294535] disabled:cursor-wait disabled:opacity-60"
          >
            {isParsing ? '正在解析…' : '开始解析章节'}
          </button>
        </div>
        {error && (
          <p className="mt-4 rounded-xl border border-rose-900/10 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {error}
          </p>
        )}
      </section>
    )
  }

  return (
    <section className="mt-4 overflow-hidden rounded-2xl border border-[#31533f]/20 bg-white/70 shadow-[0_16px_40px_rgba(49,83,63,0.06)]">
      <div className="border-b border-black/8 bg-[#24382c] p-5 text-white">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-[#b7caae]">
              <span className="size-2 rounded-full bg-emerald-400" />
              结构解析完成
            </p>
            <h2 className="mt-2 font-serif text-2xl font-semibold">
              {result.volumes.length > 0 && `${number.format(result.volumes.length)} 卷 · `}
              {number.format(result.chapter_count)} 个章节 ·{' '}
              {number.format(result.chunk_count)} 个文本块
            </h2>
          </div>
          <button
            type="button"
            onClick={onParse}
            disabled={isParsing}
            className="shrink-0 rounded-lg border border-white/15 bg-white/8 px-3.5 py-2 text-xs font-semibold text-white/75 transition hover:bg-white/12 disabled:cursor-wait disabled:opacity-50"
          >
            {isParsing ? '正在重新解析…' : '重新解析'}
          </button>
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-white/10 pt-4 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-white/40">总 Token</dt>
            <dd className="mt-1 font-semibold text-white/85">
              {number.format(result.token_count)}
            </dd>
          </div>
          <div>
            <dt className="text-white/40">分词器</dt>
            <dd className="mt-1 font-mono text-xs font-semibold text-white/85">
              {result.tokenizer}
            </dd>
          </div>
          <div>
            <dt className="text-white/40">字符总数</dt>
            <dd className="mt-1 font-semibold text-white/85">
              {number.format(result.character_count)}
            </dd>
          </div>
          <div>
            <dt className="text-white/40">识别方式</dt>
            <dd className="mt-1 font-semibold text-white/85">
              {result.used_fallback_chapter ? '无标题降级' : '标题规则'}
            </dd>
          </div>
        </dl>
        <p className="mt-4 text-xs leading-5 text-white/38">
          文本块编辑与删除仅影响当前解析清单；重新解析会恢复原始分块。
        </p>
      </div>

      <div className="max-h-[520px] divide-y divide-black/8 overflow-y-auto">
        {result.chapters.map((chapter) => (
          <details key={chapter.chapter_id} className="group p-5">
            <summary className="flex cursor-pointer list-none items-start gap-4">
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-[#e4ebe0] font-mono text-xs font-bold text-[#31533f]">
                {String(chapter.ordinal).padStart(2, '0')}
              </span>
              <div className="min-w-0 flex-1">
                <h3 className="truncate font-semibold text-[#17221b]">
                  {chapter.title}
                </h3>
                {chapter.volume_title && (
                  <p className="mt-1 text-[11px] font-semibold text-[#55705e]">
                    {chapter.volume_title}
                  </p>
                )}
                <p className="mt-1 text-xs text-black/40">
                  {number.format(chapter.character_count)} 字符 ·{' '}
                  {number.format(chapter.token_count)} Token ·{' '}
                  {chapter.chunk_ids.length} 块
                </p>
              </div>
              <span className="mt-1 text-sm text-black/30 transition group-open:rotate-45">
                ＋
              </span>
            </summary>
            <div className="ml-12 mt-4 rounded-xl bg-[#f3f1ea] p-4">
              <p className="text-sm leading-6 text-black/58">
                {chapter.preview || '该标题下没有正文内容。'}
              </p>
              <p className="mt-3 font-mono text-[11px] text-black/35">
                原文区间 [{chapter.content_start_char},{' '}
                {chapter.content_end_char}) · {chapter.chapter_id}
              </p>
            </div>

            <div className="ml-12 mt-4">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-bold uppercase tracking-[0.14em] text-black/35">
                  文本块
                </p>
                <span className="text-xs text-black/30">
                  {chapter.chunk_ids.length} 个
                </span>
              </div>
              {chapter.chunk_ids.length === 0 ? (
                <p className="rounded-xl border border-dashed border-black/12 px-4 py-3 text-sm text-black/38">
                  本章没有文本块；重新解析可以恢复已删除的块。
                </p>
              ) : (
                <div className="space-y-2">
                  {chapter.chunk_ids.map((chunkId) => {
                    const chunk = chunkById.get(chunkId)
                    if (!chunk) return null
                    const isEditing = editingChunkId === chunkId
                    return (
                      <div
                        key={chunkId}
                        className="rounded-xl border border-black/8 bg-white/75 p-3"
                      >
                        <div className="flex flex-wrap items-center gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-mono text-xs font-semibold text-[#31533f]">
                                文本块 {chunk.ordinal}
                              </span>
                              {chunk.content_override !== null && (
                                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800">
                                  已编辑
                                </span>
                              )}
                            </div>
                            <p className="mt-1 text-xs text-black/35">
                              {number.format(chunk.token_count)} Token · 原文 [{chunk.reference.start_char},{' '}
                              {chunk.reference.end_char})
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={() =>
                              setEditingChunkId(isEditing ? null : chunkId)
                            }
                            className="rounded-lg border border-black/10 bg-white px-3 py-2 text-xs font-semibold text-black/58 transition hover:border-[#55705e]/35 hover:text-[#31533f]"
                          >
                            {isEditing ? '收起' : '编辑或删除'}
                          </button>
                        </div>
                        {isEditing && (
                          <ChunkEditor
                            chunk={chunk}
                            taskId={result.task_id}
                            onChanged={onResultChange}
                            onClose={() => setEditingChunkId(null)}
                          />
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </details>
        ))}
      </div>

      {error && (
        <p className="m-5 rounded-xl border border-rose-900/10 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {error}
        </p>
      )}
    </section>
  )
}
