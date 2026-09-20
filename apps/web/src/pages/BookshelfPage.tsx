import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { clearWorkspaceTaskId } from '../features/analysis/workspaceSession'
import {
  listShelfBooks,
  removeShelfBook,
  type ShelfBook,
  type ShelfBookStage,
} from '../features/books/storage'

const statusLabels: Record<ShelfBookStage, string> = {
  uploaded: '待解析',
  parsed: '待规划',
  planned: '待分析',
  queued: '等待分析',
  running: '概括中',
  failed: '可重试',
  interrupted: '已暂停',
  batch_summaries_completed: '待汇总',
  merging: '汇总中',
  finalizing: '生成细纲',
  completed: '细纲完成',
}

const coverTones = [
  'from-[#2d4938] to-[#1c3025]',
  'from-[#6d513d] to-[#493426]',
  'from-[#334e5a] to-[#233740]',
  'from-[#665c36] to-[#443d24]',
]

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(new Date(value))
}

function BookCard({ book, index }: { book: ShelfBook; index: number }) {
  const completed = book.stage === 'completed'
  return (
    <article className="group relative flex min-h-64 items-end px-2 pt-4">
      <Link
        to={`/books/${book.id}`}
        className={`relative flex h-60 w-full origin-bottom flex-col overflow-hidden rounded-t-md bg-gradient-to-br ${coverTones[index % coverTones.length]} p-5 text-[#f4f0e4] shadow-[8px_10px_18px_rgba(32,28,20,0.18)] transition duration-300 group-hover:-translate-y-2 group-hover:shadow-[10px_18px_28px_rgba(32,28,20,0.24)]`}
      >
        <span className="absolute inset-y-0 left-3 w-px bg-white/15" />
        <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-white/46">
          NovelAtlas · {statusLabels[book.stage]}
        </span>
        <h2 className="mt-6 line-clamp-4 font-serif text-xl font-semibold leading-8 tracking-tight">
          {book.title}
        </h2>
        <div className="mt-auto border-t border-white/12 pt-4 text-xs leading-5 text-white/48">
          <p>{book.chapter_count ? `${book.chapter_count} 章` : '尚未完成章节解析'}</p>
          <p>{completed ? '点击阅读细纲' : '点击查看进度'}</p>
        </div>
      </Link>
    </article>
  )
}

export function BookshelfPage() {
  const queryClient = useQueryClient()
  const books = useQuery({
    queryKey: ['shelf-books'],
    queryFn: listShelfBooks,
  })
  const remove = useMutation({
    mutationFn: removeShelfBook,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['shelf-books'] }),
  })

  return (
    <div className="px-5 py-10 md:px-10 lg:px-16 lg:py-14">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-[#55705e]">
              Local library · 我的书架
            </p>
            <h1 className="mt-3 font-serif text-4xl font-semibold tracking-tight text-[#17221b] md:text-5xl">
              读过的故事，留下一册细纲
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-black/50">
              书名取自 TXT 文件名。细纲与批次概括只保存在这个浏览器中，不会包含小说正文。
            </p>
          </div>
          <Link
            to="/books/new"
            onClick={clearWorkspaceTaskId}
            className="shrink-0 rounded-xl bg-[#1e3227] px-5 py-3.5 text-sm font-semibold text-white shadow-[0_10px_30px_rgba(30,50,39,0.18)] transition hover:bg-[#294535]"
          >
            ＋ 新增书籍
          </Link>
        </div>

        {books.isPending && (
          <div className="mt-10 rounded-2xl border border-black/8 bg-white/55 p-8 text-sm text-black/42">
            正在打开浏览器书架…
          </div>
        )}

        {books.isError && (
          <div className="mt-10 rounded-2xl border border-rose-900/10 bg-rose-50 p-6 text-sm leading-6 text-rose-800">
            无法读取浏览器书架。请检查浏览器的隐私与网站存储设置。
          </div>
        )}

        {books.data?.length === 0 && (
          <section className="mt-10 rounded-3xl border border-dashed border-black/15 bg-white/45 px-6 py-16 text-center">
            <div className="mx-auto grid size-16 place-items-center rounded-2xl bg-[#e2e9df] font-serif text-2xl text-[#31533f]">
              书
            </div>
            <h2 className="mt-5 font-serif text-2xl font-semibold text-[#17221b]">
              书架还是空的
            </h2>
            <p className="mt-2 text-sm text-black/45">上传第一本 TXT，完成的分析结果会自动收进这里。</p>
            <Link
              to="/books/new"
              onClick={clearWorkspaceTaskId}
              className="mt-6 inline-flex rounded-xl bg-[#1e3227] px-5 py-3 text-sm font-semibold text-white"
            >
              新增第一本书
            </Link>
          </section>
        )}

        {books.data && books.data.length > 0 && (
          <div className="mt-10 space-y-9">
            <div className="relative grid grid-cols-2 gap-x-2 gap-y-8 border-b-[14px] border-[#6e543d] bg-[linear-gradient(to_bottom,transparent_calc(100%-8px),rgba(57,38,24,0.08)_calc(100%-8px))] px-2 pb-0 shadow-[0_12px_18px_-14px_rgba(38,25,15,0.8)] sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
              {books.data.map((book, index) => (
                <BookCard key={book.id} book={book} index={index} />
              ))}
            </div>

            <section className="rounded-2xl border border-black/8 bg-white/55 p-5">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="font-serif text-lg font-semibold text-[#17221b]">书架管理</h2>
                  <p className="mt-1 text-xs leading-5 text-black/38">这里只删除浏览器中的历史记录，不删除仍在后端临时目录中的 TXT。</p>
                </div>
                <span className="font-mono text-xs text-black/35">{books.data.length} 本</span>
              </div>
              <div className="mt-4 divide-y divide-black/8">
                {books.data.map((book) => (
                  <div key={book.id} className="flex items-center gap-4 py-3">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-[#17221b]">{book.title}</p>
                      <p className="mt-1 text-xs text-black/35">{statusLabels[book.stage]} · 更新于 {formatDate(book.updated_at)}</p>
                    </div>
                    <button
                      type="button"
                      disabled={remove.isPending}
                      onClick={() => {
                        if (window.confirm(`从浏览器书架移除《${book.title}》？`)) {
                          remove.mutate(book.id)
                        }
                      }}
                      className="rounded-lg px-3 py-2 text-xs font-semibold text-rose-700 transition hover:bg-rose-50 disabled:opacity-40"
                    >
                      移除记录
                    </button>
                  </div>
                ))}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
