import { useEffect, useState } from 'react'

import {
  deleteTextChunk,
  fetchChunkContent,
  updateTextChunk,
  type ParsedDocument,
  type TextChunk,
} from './api'

type ChunkEditorProps = {
  chunk: TextChunk
  taskId: string
  onChanged: (result: ParsedDocument) => void
  onClose: () => void
}

export function ChunkEditor({
  chunk,
  taskId,
  onChanged,
  onClose,
}: ChunkEditorProps) {
  const [content, setContent] = useState('')
  const [originalContent, setOriginalContent] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isCurrent = true
    fetchChunkContent(taskId, chunk.chunk_id)
      .then((detail) => {
        if (!isCurrent) return
        setContent(detail.content)
        setOriginalContent(detail.original_content)
      })
      .catch((loadError: unknown) => {
        if (!isCurrent) return
        setError(
          loadError instanceof Error ? loadError.message : '读取文本块失败',
        )
      })
      .finally(() => {
        if (isCurrent) setIsLoading(false)
      })
    return () => {
      isCurrent = false
    }
  }, [chunk.chunk_id, taskId])

  const save = async () => {
    if (!content.trim()) {
      setError('文本块不能为空；如需移除，请使用“删除文本块”')
      return
    }
    setIsSaving(true)
    setError(null)
    try {
      const result = await updateTextChunk(taskId, chunk.chunk_id, content)
      onChanged(result)
      onClose()
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : '保存文本块失败',
      )
    } finally {
      setIsSaving(false)
    }
  }

  const remove = async () => {
    const confirmed = window.confirm(
      '确定删除这个文本块吗？原始 TXT 不会被删除，重新解析可以恢复该文本块。',
    )
    if (!confirmed) return

    setIsSaving(true)
    setError(null)
    try {
      const result = await deleteTextChunk(taskId, chunk.chunk_id)
      onChanged(result)
      onClose()
    } catch (deleteError) {
      setError(
        deleteError instanceof Error ? deleteError.message : '删除文本块失败',
      )
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="mt-3 rounded-xl border border-[#31533f]/15 bg-[#f3f1ea] p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.14em] text-[#55705e]">
            编辑文本块 {chunk.ordinal}
          </p>
          <p className="mt-1 font-mono text-[11px] text-black/35">
            原文 [{chunk.reference.start_char}, {chunk.reference.end_char})
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          disabled={isSaving}
          className="rounded-lg px-3 py-2 text-xs font-semibold text-black/45 transition hover:bg-black/5"
        >
          关闭
        </button>
      </div>

      {isLoading ? (
        <p className="mt-4 text-sm text-black/45">正在读取文本块…</p>
      ) : (
        <>
          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            disabled={isSaving || Boolean(error && !content)}
            rows={10}
            aria-label={`编辑文本块 ${chunk.ordinal}`}
            className="mt-4 w-full resize-y rounded-xl border border-black/12 bg-white px-4 py-3 font-serif text-sm leading-7 text-[#17221b] outline-none transition focus:border-[#55705e] focus:ring-3 focus:ring-[#55705e]/10 disabled:opacity-60"
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-black/38">
            <span>{content.length.toLocaleString('zh-CN')} 字符</span>
            {content !== originalContent && (
              <button
                type="button"
                onClick={() => setContent(originalContent)}
                disabled={isSaving}
                className="font-semibold text-[#55705e] hover:underline"
              >
                恢复原文
              </button>
            )}
          </div>
        </>
      )}

      <p className="mt-3 text-xs leading-5 text-amber-800/75">
        修改只作用于此文本块，不改写原始 TXT、引用坐标或相邻重叠块。
      </p>
      {error && (
        <p className="mt-3 rounded-lg border border-rose-900/10 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          {error}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-black/8 pt-4">
        <button
          type="button"
          onClick={remove}
          disabled={isLoading || isSaving}
          className="rounded-lg px-3 py-2 text-xs font-semibold text-rose-700 transition hover:bg-rose-50 disabled:opacity-45"
        >
          删除文本块
        </button>
        <button
          type="button"
          onClick={save}
          disabled={isLoading || isSaving || content === (chunk.content_override ?? originalContent)}
          className="rounded-lg bg-[#1e3227] px-4 py-2.5 text-xs font-semibold text-white transition hover:bg-[#294535] disabled:cursor-not-allowed disabled:opacity-45"
        >
          {isSaving ? '正在保存…' : '保存修改'}
        </button>
      </div>
    </div>
  )
}
