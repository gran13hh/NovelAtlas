import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

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

const analysisModules = [
  {
    marker: '01',
    title: '剧情脉络',
    description: '从章节事件中整理主线、支线、伏笔与时间轴。',
  },
  {
    marker: '02',
    title: '人物图谱',
    description: '归纳人物外貌、性格、经历与持续变化的关系。',
  },
  {
    marker: '03',
    title: '文风档案',
    description: '提炼叙事节奏、句式、修辞及典型描写手法。',
  },
  {
    marker: '04',
    title: '世界设定',
    description: '连接地点、势力、制度、能力体系和原文依据。',
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
              <span>阶段 3</span>
              <span className="h-3 w-px bg-[#31533f]/25" />
              <span>章节与引用定位</span>
            </div>

            <h1 className="max-w-3xl font-serif text-5xl font-semibold leading-[1.04] tracking-[-0.045em] text-[#17221b] md:text-7xl">
              把一部长篇小说，
              <span className="text-[#55705e]">展开成可验证的故事地图。</span>
            </h1>

            <p className="mt-7 max-w-2xl text-base leading-8 text-black/58 md:text-lg">
              上传小说文本后，由 AI Agent 分阶段整理剧情、人物、文风与世界观；每条关键结论都保留返回原文的线索。
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
              <ParsePreview
                error={parseError}
                isParsing={parseMutation.isPending}
                result={parseResult}
                onParse={() => parseMutation.mutate(uploadedDocument.task_id)}
              />
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
              <span>Analysis workspace</span>
              <span>{parseResult ? '02 / 04' : uploadedDocument ? '01 / 04' : '00 / 04'}</span>
            </div>

            <div className="my-12 space-y-3">
              {analysisModules.map((module) => (
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
              当前仅展示产品结构。分析能力将在后续阶段逐项接入并独立验收。
            </p>
          </aside>
        </section>

        <section
          id="workflow"
          className="grid gap-px bg-black/10 md:grid-cols-3"
        >
          {[
            ['输入', 'TXT 小说正文', '校验编码、识别章节并建立引用坐标'],
            ['分析', 'Agents + Skills', '分层抽取、归并信息并核验引用'],
            ['输出', '可编辑小说图谱', '查看、修正、生图、仿写与导出'],
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
          <span>NovelAtlas · AI Agent 小说分析工作台</span>
          <span>本地优先 · 临时处理 · 结论可追溯</span>
        </footer>
      </div>
    </main>
  )
}

export default App
