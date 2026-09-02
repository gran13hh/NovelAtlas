import type { ParsedDocument } from './api'

type ParsePreviewProps = {
  error: string | null
  isParsing: boolean
  result: ParsedDocument | null
  onParse: () => void
}

const number = new Intl.NumberFormat('zh-CN')

export function ParsePreview({
  error,
  isParsing,
  result,
  onParse,
}: ParsePreviewProps) {
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
