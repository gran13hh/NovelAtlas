import { useRef, useState, type ChangeEvent, type DragEvent } from 'react'

import type { UploadedDocument } from './api'


type UploadPanelProps = {
  document: UploadedDocument | null
  error: string | null
  isDeleting: boolean
  isUploading: boolean
  maxUploadBytes: number
  progress: number
  onCancel: () => void
  onDelete: () => void
  onFile: (file: File) => void
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MiB`
}

function formatCharacters(characters: number): string {
  return new Intl.NumberFormat('zh-CN').format(characters)
}

function formatExpiration(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value))
}

export function UploadPanel({
  document,
  error,
  isDeleting,
  isUploading,
  maxUploadBytes,
  progress,
  onCancel,
  onDelete,
  onFile,
}: UploadPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)

  const selectFile = (file: File | undefined) => {
    if (file) onFile(file)
  }

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    selectFile(event.target.files?.[0])
    event.target.value = ''
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDragging(false)
    if (!isUploading) selectFile(event.dataTransfer.files[0])
  }

  if (document) {
    return (
      <section className="mt-10 rounded-2xl border border-[#31533f]/20 bg-[#edf2e9] p-5 shadow-[0_16px_40px_rgba(49,83,63,0.08)]">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-[#31533f]">
              <span className="size-2 rounded-full bg-emerald-500" />
              TXT 已安全接收
            </div>
            <h2 className="truncate font-serif text-xl font-semibold text-[#17221b]">
              {document.filename}
            </h2>
            <dl className="mt-4 grid grid-cols-2 gap-x-8 gap-y-3 text-sm sm:grid-cols-4">
              <div>
                <dt className="text-black/38">文件大小</dt>
                <dd className="mt-1 font-semibold text-black/68">
                  {formatBytes(document.size_bytes)}
                </dd>
              </div>
              <div>
                <dt className="text-black/38">字符数</dt>
                <dd className="mt-1 font-semibold text-black/68">
                  {formatCharacters(document.character_count)}
                </dd>
              </div>
              <div>
                <dt className="text-black/38">检测编码</dt>
                <dd className="mt-1 font-mono text-xs font-semibold uppercase text-black/68">
                  {document.detected_encoding}
                </dd>
              </div>
              <div>
                <dt className="text-black/38">自动清理</dt>
                <dd className="mt-1 font-semibold text-black/68">
                  {formatExpiration(document.expires_at)}
                </dd>
              </div>
            </dl>
          </div>

          <button
            type="button"
            onClick={onDelete}
            disabled={isDeleting}
            className="shrink-0 rounded-xl border border-rose-900/10 bg-white/70 px-4 py-2.5 text-sm font-semibold text-rose-800 transition hover:bg-white disabled:cursor-wait disabled:opacity-55"
          >
            {isDeleting ? '正在删除…' : '立即删除'}
          </button>
        </div>
        <p className="mt-5 border-t border-[#31533f]/10 pt-4 text-xs leading-5 text-black/42">
          任务 ID：<span className="font-mono">{document.task_id}</span>。正文仅保存在后端临时目录，当前浏览器只持有以上元数据。
        </p>
        {error && (
          <p className="mt-3 rounded-xl border border-rose-900/10 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            {error}
          </p>
        )}
      </section>
    )
  }

  return (
    <section className="mt-10" aria-live="polite">
      <div
        onDragEnter={(event) => {
          event.preventDefault()
          setIsDragging(true)
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => {
          const nextTarget = event.relatedTarget
          if (
            !(nextTarget instanceof Node) ||
            !event.currentTarget.contains(nextTarget)
          ) {
            setIsDragging(false)
          }
        }}
        onDrop={handleDrop}
        className={`rounded-2xl border border-dashed p-5 transition sm:p-6 ${
          isDragging
            ? 'border-[#31533f] bg-[#e6eee2]'
            : 'border-black/15 bg-white/55 hover:border-[#31533f]/45'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".txt,text/plain"
          onChange={handleChange}
          className="sr-only"
          aria-label="选择 TXT 小说文件"
        />

        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-semibold text-[#17221b]">
              {isUploading ? '正在上传并识别编码' : '拖入 TXT 小说，或从电脑选择'}
            </p>
            <p className="mt-1.5 text-sm text-black/42">
              仅支持 TXT，最大 {formatBytes(maxUploadBytes)}；正文不会写入浏览器持久缓存。
            </p>
          </div>

          {isUploading ? (
            <button
              type="button"
              onClick={onCancel}
              className="shrink-0 rounded-xl border border-black/10 bg-white px-4 py-2.5 text-sm font-semibold text-black/60 shadow-sm"
            >
              取消上传
            </button>
          ) : (
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="shrink-0 rounded-xl bg-[#1e3227] px-5 py-3 text-sm font-semibold text-white shadow-[0_10px_30px_rgba(30,50,39,0.18)] transition hover:bg-[#294535]"
            >
              选择 TXT
            </button>
          )}
        </div>

        {isUploading && (
          <div className="mt-5">
            <div className="mb-2 flex items-center justify-between text-xs font-medium text-black/45">
              <span>上传进度</span>
              <span>{progress}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-black/8">
              <div
                className="h-full rounded-full bg-[#55705e] transition-[width] duration-200"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {error && (
        <p className="mt-3 rounded-xl border border-rose-900/10 bg-rose-50 px-4 py-3 text-sm text-rose-800">
          {error}
        </p>
      )}
    </section>
  )
}
