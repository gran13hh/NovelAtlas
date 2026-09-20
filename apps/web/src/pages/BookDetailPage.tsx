import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import {
  fetchAnalysisStatus,
  fetchBatchSummaries,
  fetchFinalOutline,
} from '../features/analysis/api'
import { saveWorkspaceTaskId } from '../features/analysis/workspaceSession'
import { ExportPanel } from '../features/export/ExportPanel'
import {
  getShelfBook,
  saveShelfBook,
  type ShelfBook,
  type ShelfBookStage,
} from '../features/books/storage'
import type { NovelOutline, OutlineClaim } from '../features/analysis/api'

const statusLabels: Record<ShelfBookStage, string> = {
  uploaded: '等待解析',
  parsed: '等待规划',
  planned: '等待开始分析',
  queued: '等待后台任务',
  running: '正在逐批概括',
  failed: '分析失败，可继续',
  interrupted: '分析已暂停',
  batch_summaries_completed: '批次概括已完成',
  merging: '正在分层汇总',
  finalizing: '正在生成细纲',
  completed: '全书细纲已完成',
}

async function loadBookDetail(bookId: string): Promise<ShelfBook | null> {
  const cached = await getShelfBook(bookId)
  if (
    !cached ||
    new Date(cached.source_expires_at).getTime() <= Date.now()
  ) {
    return cached
  }

  try {
    const [manifest, summaries] = await Promise.all([
      fetchAnalysisStatus(cached.task_id),
      fetchBatchSummaries(cached.task_id),
    ])
    const outline =
      manifest.status === 'completed'
        ? await fetchFinalOutline(cached.task_id)
        : cached.outline
    const refreshed: ShelfBook = {
      ...cached,
      updated_at: new Date().toISOString(),
      stage: manifest.status,
      manifest,
      summaries,
      outline,
    }
    await saveShelfBook(refreshed)
    return refreshed
  } catch {
    return cached
  }
}

function ClaimList({ items }: { items: OutlineClaim[] }) {
  if (items.length === 0) return <p className="text-sm text-black/35">暂无明确内容</p>
  return (
    <ul className="space-y-2">
      {items.map((item, index) => (
        <li key={`${item.description}-${index}`} className="rounded-lg bg-black/[0.025] px-3 py-2 text-sm leading-6 text-black/62">
          {item.description}
        </li>
      ))}
    </ul>
  )
}

function CachedOutline({ outline }: { outline: NovelOutline }) {
  return (
    <div className="space-y-5">
      <article className="rounded-2xl bg-[#24382c] p-6 text-white md:p-8">
        <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#b7caae]">总体概述</p>
        <p className="mt-3 font-serif text-lg leading-8 text-white/85">{outline.overall_summary}</p>
      </article>

      <section>
        <h2 className="font-serif text-2xl font-semibold text-[#17221b]">章节范围细纲</h2>
        <div className="mt-4 space-y-2">
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
          <h2 className="font-serif text-lg font-semibold">主要故事线</h2>
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
          <h2 className="font-serif text-lg font-semibold">主要人物与关系</h2>
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
          <h2 className="font-serif text-lg font-semibold">世界观</h2>
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
          <h2 className="font-serif text-lg font-semibold">伏笔与不确定项</h2>
          <div className="mt-3">
            <ClaimList items={[...outline.foreshadowing, ...outline.unresolved_items, ...outline.conflicts_and_uncertainties]} />
          </div>
        </section>
      </div>
    </div>
  )
}

export function BookDetailPage() {
  const { bookId = '' } = useParams()
  const [loadedAt] = useState(() => Date.now())
  const book = useQuery({
    queryKey: ['shelf-book', bookId],
    queryFn: () => loadBookDetail(bookId),
    enabled: Boolean(bookId),
  })

  if (book.isPending) {
    return <div className="px-5 py-16 text-center text-sm text-black/40">正在取出书架记录…</div>
  }

  if (book.isError || !book.data) {
    return (
      <div className="mx-auto max-w-3xl px-5 py-16 text-center">
        <h1 className="font-serif text-3xl font-semibold text-[#17221b]">没有找到这本书</h1>
        <p className="mt-3 text-sm text-black/45">记录可能已从当前浏览器清除。</p>
        <Link to="/books" className="mt-6 inline-flex rounded-xl bg-[#1e3227] px-5 py-3 text-sm font-semibold text-white">返回我的书架</Link>
      </div>
    )
  }

  const record = book.data
  const sourceAvailable = new Date(record.source_expires_at).getTime() > loadedAt

  return (
    <div className="px-5 py-10 md:px-10 lg:px-16 lg:py-14">
      <div className="mx-auto max-w-5xl">
        <Link to="/books" className="text-sm font-semibold text-[#55705e] hover:underline">← 返回我的书架</Link>
        <div className="mt-6 flex flex-col gap-5 border-b border-black/10 pb-8 md:flex-row md:items-end md:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-[#55705e]">Cached analysis · 历史分析</p>
            <h1 className="mt-3 break-words font-serif text-4xl font-semibold tracking-tight text-[#17221b] md:text-5xl">{record.title}</h1>
            <p className="mt-3 text-sm text-black/45">{statusLabels[record.stage]}{record.chapter_count ? ` · ${record.chapter_count} 章` : ''}{record.summaries.length ? ` · ${record.summaries.length} 个批次概括` : ''}</p>
          </div>
          {sourceAvailable && (
            <Link
              to="/books/new"
              onClick={() => saveWorkspaceTaskId(record.task_id)}
              className="shrink-0 rounded-xl border border-[#31533f]/18 bg-[#edf2e9] px-5 py-3 text-sm font-semibold text-[#31533f] transition hover:bg-[#e3ece0]"
            >
              {record.stage === 'completed' ? '打开分析工作台' : '继续整理'}
            </Link>
          )}
        </div>

        {!sourceAvailable && (
          <p className="mt-5 rounded-xl border border-amber-900/10 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-800">
            后端临时原文已过期，无法继续分析；浏览器中已保存的概括和细纲仍可阅读。
          </p>
        )}

        <div className="mt-8">
          {record.outline ? (
            <>
              <CachedOutline outline={record.outline.outline} />
              <ExportPanel title={record.title} outline={record.outline.outline} />
            </>
          ) : record.summaries.length > 0 ? (
            <section>
              <h2 className="font-serif text-2xl font-semibold text-[#17221b]">已完成的批次概括</h2>
              <p className="mt-2 text-sm text-black/42">全书细纲尚未生成，以下内容已保存在浏览器书架。</p>
              <div className="mt-5 space-y-3">
                {record.summaries.map((item) => (
                  <article key={item.batch.batch_id} className="rounded-xl border border-black/8 bg-white/70 p-5">
                    <p className="text-xs font-bold text-[#55705e]">批次 {item.batch.ordinal} · {item.batch.chapter_range_label}</p>
                    <p className="mt-2 text-sm leading-7 text-black/62">{item.summary.overview}</p>
                  </article>
                ))}
              </div>
            </section>
          ) : (
            <section className="rounded-2xl border border-dashed border-black/15 bg-white/45 px-6 py-12 text-center">
              <h2 className="font-serif text-2xl font-semibold text-[#17221b]">还没有可展示的分析结果</h2>
              <p className="mt-2 text-sm text-black/42">{sourceAvailable ? '可以返回工作台继续章节解析与细纲提取。' : '临时原文已过期，请重新上传 TXT。'}</p>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
