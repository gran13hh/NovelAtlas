import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { AnalysisPlanPanel } from './features/analysis/AnalysisPlanPanel'
import { ModelGatewayPanel } from './features/models/ModelGatewayPanel'
import { parseDocument, type ParsedDocument } from './features/parsing/api'
import { ParsePreview } from './features/parsing/ParsePreview'
import {
  DEFAULT_MAX_UPLOAD_BYTES,
  deleteUpload,
  fetchUploadConstraints,
  uploadTxt,
  type UploadedDocument,
} from './features/upload/api'
import { UploadPanel } from './features/upload/UploadPanel'

type HealthResponse = {
  status: 'ok'
  service: string
  version: string
}

const outlineStages = [
  {
    marker: '01',
    title: '批次规划',
    description: '根据模型输入预算组合相邻章节，预估调用次数。',
  },
  {
    marker: '02',
    title: '逐批概括',
    description: '每批只调用一次模型，并在成功后立即保存进度。',
  },
  {
    marker: '03',
    title: '分层汇总',
    description: '逐层合并批次概括，避免一次提交整本长篇小说。',
  },
  {
    marker: '04',
    title: '详细大纲',
    description: '输出故事线、人物关系、世界观、伏笔与不确定项。',
  },
]

async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch('/api/health')

  if (!response.ok) {
    throw new Error(`API health check failed with ${response.status}`)
  }

  return response.json() as Promise<HealthResponse>
}

function App() {
  const [uploadedDocument, setUploadedDocument] =
    useState<UploadedDocument | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [parseResult, setParseResult] = useState<ParsedDocument | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const uploadController = useRef<AbortController | null>(null)

  const health = useQuery({
    queryKey: ['api-health'],
    queryFn: fetchHealth,
    retry: 1,
    refetchInterval: 30_000,
  })
  const uploadConstraints = useQuery({
    queryKey: ['upload-constraints'],
    queryFn: fetchUploadConstraints,
    retry: 1,
  })
  const maxUploadBytes =
    uploadConstraints.data?.max_upload_bytes ?? DEFAULT_MAX_UPLOAD_BYTES

  const uploadMutation = useMutation({
    mutationFn: ({ file, controller }: { file: File; controller: AbortController }) =>
      uploadTxt(file, {
        signal: controller.signal,
        onProgress: setUploadProgress,
      }),
    onMutate: () => {
      setUploadError(null)
      setUploadProgress(0)
    },
    onSuccess: (uploaded) => {
      setUploadedDocument(uploaded)
      setParseResult(null)
      setParseError(null)
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
    onSuccess: () => {
      setUploadedDocument(null)
      setUploadError(null)
      setUploadProgress(0)
      setParseResult(null)
      setParseError(null)
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
    onSuccess: setParseResult,
    onError: (error) => {
      setParseError(
        error instanceof Error ? error.message : '解析失败，请稍后重试',
      )
    },
  })

  useEffect(() => () => uploadController.current?.abort(), [])

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

  const apiState = health.isPending
    ? { label: '正在连接 API', tone: 'bg-amber-400' }
    : health.isError
      ? { label: 'API 未启动', tone: 'bg-rose-400' }
      : {
          label: `API 已连接 · v${health.data.version}`,
          tone: 'bg-emerald-400',
        }

  return (
    <main className="min-h-screen overflow-hidden bg-[#f3f1ea] text-[#191a17]">
      <div className="pointer-events-none fixed inset-0 opacity-45 [background-image:radial-gradient(#b9b5a7_0.7px,transparent_0.7px)] [background-size:18px_18px]" />

      <div className="relative mx-auto min-h-screen max-w-[1440px] border-x border-black/10 bg-[#f8f7f2]/95">
        <header className="flex items-center justify-between border-b border-black/10 px-5 py-4 md:px-10">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-xl bg-[#1e3227] font-mono text-sm font-bold tracking-tight text-[#e7efdf] shadow-[0_6px_20px_rgba(30,50,39,0.2)]">
              NA
            </span>
            <div>
              <p className="font-serif text-lg font-semibold leading-none tracking-tight">
                NovelAtlas
              </p>
              <p className="mt-1 text-[10px] font-medium uppercase tracking-[0.22em] text-black/45">
                Narrative Intelligence
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 rounded-full border border-black/10 bg-white/70 px-3 py-2 text-xs font-medium text-black/60 shadow-sm">
            <span className={`size-2 rounded-full ${apiState.tone}`} />
            <span>{apiState.label}</span>
          </div>
        </header>

        <section className="grid border-b border-black/10 lg:grid-cols-[1.25fr_0.75fr]">
          <div className="px-5 py-14 md:px-10 md:py-20 lg:border-r lg:border-black/10 lg:px-16 lg:py-24">
            <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-[#31533f]/20 bg-[#dfe8dc] px-3 py-1.5 text-xs font-semibold text-[#31533f]">
              <span>阶段 5</span>
              <span className="h-3 w-px bg-[#31533f]/25" />
              <span>全书细纲工作流</span>
            </div>

            <h1 className="max-w-3xl font-serif text-5xl font-semibold leading-[1.04] tracking-[-0.045em] text-[#17221b] md:text-7xl">
              把一部长篇小说，
              <span className="text-[#55705e]">整理成可回看的详细大纲。</span>
            </h1>

            <p className="mt-7 max-w-2xl text-base leading-8 text-black/58 md:text-lg">
              上传小说文本后，由 AI Agent 分批概括重要内容，再逐层汇总故事线、主要人物关系、世界观与伏笔。
            </p>

            <UploadPanel
              document={uploadedDocument}
              error={uploadError}
              isDeleting={deleteMutation.isPending}
              isUploading={uploadMutation.isPending}
              maxUploadBytes={maxUploadBytes}
              progress={uploadProgress}
              onCancel={() => uploadController.current?.abort()}
              onDelete={() => {
                if (uploadedDocument) {
                  deleteMutation.mutate(uploadedDocument.task_id)
                }
              }}
              onFile={handleFile}
            />

            {uploadedDocument && (
              <>
                <ParsePreview
                  error={parseError}
                  isParsing={parseMutation.isPending}
                  result={parseResult}
                  onResultChange={setParseResult}
                  onParse={() => parseMutation.mutate(uploadedDocument.task_id)}
                />
                {parseResult && (
                  <AnalysisPlanPanel
                    key={parseResult.chunks
                      .map(
                        (chunk) =>
                          `${chunk.chunk_id}:${chunk.token_count}:${chunk.content_override ?? ''}`,
                      )
                      .join('|')}
                    taskId={uploadedDocument.task_id}
                  />
                )}
              </>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-4">
              <a
                href="#workflow"
                className="rounded-xl border border-black/10 bg-white px-5 py-3.5 text-sm font-semibold text-black/65 shadow-sm transition hover:border-black/20 hover:text-black"
              >
                查看处理流程
              </a>
            </div>
          </div>

          <aside className="flex min-h-[430px] flex-col justify-between bg-[#24382c] p-6 text-[#e9eee7] md:p-10 lg:p-12">
            <div className="flex items-center justify-between text-xs uppercase tracking-[0.2em] text-white/45">
              <span>Outline workspace</span>
              <span>{parseResult ? '02 / 05' : uploadedDocument ? '01 / 05' : '00 / 05'}</span>
            </div>

            <div className="my-12 space-y-3">
              {outlineStages.map((module) => (
                <div
                  key={module.marker}
                  className="grid grid-cols-[auto_1fr] gap-4 rounded-2xl border border-white/10 bg-white/[0.055] p-4"
                >
                  <span className="font-mono text-xs text-[#b7caae]">
                    {module.marker}
                  </span>
                  <div>
                    <h2 className="text-base font-semibold tracking-tight">
                      {module.title}
                    </h2>
                    <p className="mt-1.5 text-sm leading-6 text-white/48">
                      {module.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>

            <p className="text-xs leading-5 text-white/35">
              当前已完成上传、解析与文本模型配置；大纲生成能力将按阶段逐项接入并验收。
            </p>
          </aside>
        </section>

        <ModelGatewayPanel />

        <section
          id="workflow"
          className="grid gap-px bg-black/10 md:grid-cols-3"
        >
          {[
            ['输入', 'TXT 小说正文', '校验编码、识别章节并生成无重叠分析片段'],
            ['概括', '批次 Agent + Skills', '动态组批、逐批保存并支持失败后继续'],
            ['输出', '全书详细大纲', '查看、修正并导出故事线与设定梳理'],
          ].map(([eyebrow, title, description], index) => (
            <article
              key={eyebrow}
              className="relative bg-[#f8f7f2] px-6 py-10 md:px-10 md:py-12"
            >
              <div className="mb-8 flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-[0.2em] text-[#55705e]">
                  {eyebrow}
                </span>
                <span className="font-mono text-xs text-black/25">
                  0{index + 1}
                </span>
              </div>
              <h2 className="font-serif text-2xl font-semibold tracking-tight">
                {title}
              </h2>
              <p className="mt-3 max-w-sm text-sm leading-6 text-black/50">
                {description}
              </p>
            </article>
          ))}
        </section>

        <footer className="flex flex-col gap-2 border-t border-black/10 px-5 py-6 text-xs text-black/42 md:flex-row md:items-center md:justify-between md:px-10">
          <span>NovelAtlas · AI Agent 长篇小说细纲工作台</span>
          <span>本地优先 · 临时处理 · 批次可恢复</span>
        </footer>
      </div>
    </main>
  )
}

export default App
