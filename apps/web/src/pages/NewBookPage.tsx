import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import {
  AnalysisWorkspace,
  type AnalysisWorkspaceState,
} from '../features/analysis/AnalysisWorkspace'
import {
  clearWorkspaceTaskId,
  loadWorkspaceTaskId,
  saveWorkspaceTaskId,
} from '../features/analysis/workspaceSession'
import {
  createShelfBook,
  getShelfBook,
  removeShelfBook,
  saveShelfBook,
  type ShelfBook,
  type ShelfBookStage,
} from '../features/books/storage'
import {
  fetchParsedDocument,
  parseDocument,
  type ParsedDocument,
} from '../features/parsing/api'
import { ParsePreview } from '../features/parsing/ParsePreview'
import {
  DEFAULT_MAX_UPLOAD_BYTES,
  deleteUpload,
  fetchUpload,
  fetchUploadConstraints,
  uploadTxt,
  type UploadedDocument,
} from '../features/upload/api'
import { UploadPanel } from '../features/upload/UploadPanel'

function analysisStage(state: AnalysisWorkspaceState): ShelfBookStage {
  if (state.manifest) return state.manifest.status
  if (state.plan) return 'planned'
  return 'parsed'
}

export function NewBookPage() {
  const queryClient = useQueryClient()
  const [uploadedDocument, setUploadedDocument] =
    useState<UploadedDocument | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [parseResult, setParseResult] = useState<ParsedDocument | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const [restorationTaskId] = useState(() => loadWorkspaceTaskId())
  const [isRestoring, setIsRestoring] = useState(
    () => restorationTaskId !== null,
  )
  const uploadController = useRef<AbortController | null>(null)
  const libraryWriteQueue = useRef<Promise<void>>(Promise.resolve())

  const uploadConstraints = useQuery({
    queryKey: ['upload-constraints'],
    queryFn: fetchUploadConstraints,
    retry: 1,
  })
  const maxUploadBytes =
    uploadConstraints.data?.max_upload_bytes ?? DEFAULT_MAX_UPLOAD_BYTES

  const saveBook = useCallback(
    async (
      uploaded: UploadedDocument,
      change: Partial<ShelfBook>,
    ) => {
      const current = (await getShelfBook(uploaded.task_id)) ?? createShelfBook(uploaded)
      await saveShelfBook({
        ...current,
        ...change,
        id: uploaded.task_id,
        task_id: uploaded.task_id,
        title: uploaded.filename,
        updated_at: new Date().toISOString(),
      })
      await queryClient.invalidateQueries({ queryKey: ['shelf-books'] })
      await queryClient.invalidateQueries({
        queryKey: ['shelf-book', uploaded.task_id],
      })
      setLibraryError(null)
    },
    [queryClient],
  )

  const queueBookSave = useCallback(
    (uploaded: UploadedDocument, change: Partial<ShelfBook>) => {
      const nextWrite = libraryWriteQueue.current.then(() =>
        saveBook(uploaded, change),
      )
      libraryWriteQueue.current = nextWrite.catch(() => undefined)
      return nextWrite
    },
    [saveBook],
  )

  const uploadMutation = useMutation({
    mutationFn: ({ file, controller }: { file: File; controller: AbortController }) =>
      uploadTxt(file, {
        signal: controller.signal,
        onProgress: setUploadProgress,
      }),
    onMutate: () => {
      setUploadError(null)
      setLibraryError(null)
      setUploadProgress(0)
    },
    onSuccess: (uploaded) => {
      setUploadedDocument(uploaded)
      saveWorkspaceTaskId(uploaded.task_id)
      setParseResult(null)
      setParseError(null)
      void queueBookSave(uploaded, createShelfBook(uploaded))
        .catch(() => setLibraryError('文件已上传，但浏览器拒绝保存书架记录。'))
    },
    onError: (error) => {
      setUploadError(
        error instanceof Error ? error.message : '上传失败，请稍后重试',
      )
    },
    onSettled: () => {
      uploadController.current = null
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteUpload,
    onSuccess: async (_, taskId) => {
      clearWorkspaceTaskId()
      setUploadedDocument(null)
      setUploadError(null)
      setUploadProgress(0)
      setParseResult(null)
      setParseError(null)
      await libraryWriteQueue.current
      const cached = await getShelfBook(taskId).catch(() => null)
      if (cached?.outline) {
        await saveShelfBook({
          ...cached,
          source_expires_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }).catch(() => undefined)
        await queryClient.invalidateQueries({ queryKey: ['shelf-books'] })
        await queryClient.invalidateQueries({ queryKey: ['shelf-book', taskId] })
      } else {
        await removeShelfBook(taskId).catch(() => undefined)
        await queryClient.invalidateQueries({ queryKey: ['shelf-books'] })
        await queryClient.invalidateQueries({ queryKey: ['shelf-book', taskId] })
      }
    },
    onError: (error) => {
      setUploadError(
        error instanceof Error ? error.message : '删除失败，请稍后重试',
      )
    },
  })

  const parseMutation = useMutation({
    mutationFn: parseDocument,
    onMutate: () => setParseError(null),
    onSuccess: (parsed) => {
      setParseResult(parsed)
      if (uploadedDocument) {
        void queueBookSave(uploadedDocument, {
          stage: 'parsed',
          chapter_count: parsed.chapter_count,
          chunk_count: parsed.chunk_count,
        }).catch(() => setLibraryError('解析成功，但未能更新浏览器书架。'))
      }
    },
    onError: (error) => {
      setParseError(
        error instanceof Error ? error.message : '解析失败，请稍后重试',
      )
    },
  })

  useEffect(() => () => uploadController.current?.abort(), [])

  useEffect(() => {
    const taskId = restorationTaskId
    if (!taskId) return
    let current = true
    fetchUpload(taskId)
      .then(async (uploaded) => {
        if (!current) return
        setUploadedDocument(uploaded)
        try {
          const parsed = await fetchParsedDocument(taskId)
          if (current) setParseResult(parsed)
        } catch {
          // An uploaded task may validly exist before its first parse.
        }
      })
      .catch(() => {
        if (!current) return
        clearWorkspaceTaskId()
        setUploadError('上次临时任务已过期或被删除，请重新上传 TXT。')
      })
      .finally(() => {
        if (current) setIsRestoring(false)
      })
    return () => {
      current = false
    }
  }, [restorationTaskId])

  const handleFile = (file: File) => {
    if (!file.name.toLowerCase().endsWith('.txt')) {
      setUploadError('仅支持 .txt 文件')
      return
    }
    if (file.size === 0) {
      setUploadError('TXT 文件为空')
      return
    }
    if (file.size > maxUploadBytes) {
      setUploadError(
        `TXT 文件不能超过 ${(maxUploadBytes / 1024 / 1024).toFixed(0)} MiB`,
      )
      return
    }

    const controller = new AbortController()
    uploadController.current = controller
    uploadMutation.mutate({ file, controller })
  }

  const persistAnalysis = useCallback(
    (state: AnalysisWorkspaceState) => {
      if (!uploadedDocument) return
      void queueBookSave(uploadedDocument, {
        stage: analysisStage(state),
        plan: state.plan,
        manifest: state.manifest,
        summaries: state.summaries,
        outline: state.outline,
      }).catch(() => setLibraryError('分析仍在继续，但结果未能写入浏览器书架。'))
    },
    [queueBookSave, uploadedDocument],
  )

  return (
    <div className="px-5 py-10 md:px-10 lg:px-16 lg:py-14">
      <div className="mx-auto max-w-5xl">
        <div className="flex flex-col gap-4 border-b border-black/10 pb-8 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-[#55705e]">
              New book · 新增书籍
            </p>
            <h1 className="mt-3 font-serif text-4xl font-semibold tracking-tight text-[#17221b] md:text-5xl">
              从一本 TXT 开始整理
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-7 text-black/50">
              上传、检查章节分块、确认调用预算，然后让 Agent 分批生成全书细纲。
            </p>
          </div>
          <Link
            to="/settings"
            className="shrink-0 rounded-xl border border-black/10 bg-white px-4 py-3 text-sm font-semibold text-black/60 shadow-sm transition hover:border-[#55705e]/35 hover:text-[#31533f]"
          >
            前往模型配置
          </Link>
        </div>

        <UploadPanel
          document={uploadedDocument}
          error={uploadError}
          isDeleting={deleteMutation.isPending}
          isUploading={uploadMutation.isPending}
          maxUploadBytes={maxUploadBytes}
          progress={uploadProgress}
          onCancel={() => uploadController.current?.abort()}
          onDelete={() => {
            if (uploadedDocument) deleteMutation.mutate(uploadedDocument.task_id)
          }}
          onFile={handleFile}
        />

        {isRestoring && (
          <p className="mt-3 text-sm text-black/42">正在恢复当前标签页的临时任务…</p>
        )}
        {libraryError && (
          <p className="mt-3 rounded-xl border border-amber-900/10 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            {libraryError}
          </p>
        )}

        {uploadedDocument && (
          <ParsePreview
            error={parseError}
            isParsing={parseMutation.isPending}
            result={parseResult}
            onResultChange={(parsed) => {
              setParseResult(parsed)
              void queueBookSave(uploadedDocument, {
                stage: 'parsed',
                chapter_count: parsed.chapter_count,
                chunk_count: parsed.chunk_count,
              }).catch(() => setLibraryError('文本块已更新，但未能同步浏览器书架。'))
            }}
            onParse={() => parseMutation.mutate(uploadedDocument.task_id)}
          />
        )}

        {uploadedDocument && parseResult && (
          <AnalysisWorkspace
            key={parseResult.chunks
              .map(
                (chunk) =>
                  `${chunk.chunk_id}:${chunk.token_count}:${chunk.content_override ?? ''}`,
              )
              .join('|')}
            taskId={uploadedDocument.task_id}
            title={uploadedDocument.filename}
            onStateChange={persistAnalysis}
          />
        )}
      </div>
    </div>
  )
}
