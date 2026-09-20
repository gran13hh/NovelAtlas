import { useId, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import {
  discoverModels,
  fetchModelGatewayStatus,
  testBrowserTextModel,
  type AnalysisBudgetConfig,
  type BrowserModelGatewayConfig,
  type BrowserProviderConfig,
} from './api'
import {
  clearBrowserModelConfig,
  hasCachedBrowserModelConfig,
  loadBrowserModelConfig,
  saveBrowserModelConfig,
} from './storage'

type ProviderFormProps = {
  config: BrowserProviderConfig
  models: string[]
  isDiscovering: boolean
  isTesting: boolean
  discoveryError: string | null
  testError: string | null
  testResult: string | null
  onChange: (config: BrowserProviderConfig) => void
  onDiscover: () => void
  onTest: () => void
}

type AnalysisBudgetFormProps = {
  budget: AnalysisBudgetConfig
  onChange: (budget: AnalysisBudgetConfig) => void
}

const tokenNumber = new Intl.NumberFormat('zh-CN')

function availableContentTokens(budget: AnalysisBudgetConfig): number {
  return (
    Math.min(
      budget.max_input_tokens,
      budget.context_window_tokens - budget.output_reserve_tokens,
    ) - budget.safety_margin_tokens
  )
}

function AnalysisBudgetForm({ budget, onChange }: AnalysisBudgetFormProps) {
  const available = availableContentTokens(budget)
  const update = (change: Partial<AnalysisBudgetConfig>) =>
    onChange({ ...budget, ...change })
  const fields: Array<{
    key: keyof AnalysisBudgetConfig
    label: string
    description: string
    min: number
    max?: number
  }> = [
    {
      key: 'context_window_tokens',
      label: '模型上下文窗口',
      description: '模型一次请求支持的输入与输出 Token 总量。',
      min: 512,
    },
    {
      key: 'max_input_tokens',
      label: '最大分析输入',
      description: 'NovelAtlas 允许一次请求使用的输入上限。',
      min: 128,
    },
    {
      key: 'output_reserve_tokens',
      label: '输出预留',
      description: '为批次概括或汇总结果预留的生成空间。',
      min: 32,
      max: 32_000,
    },
    {
      key: 'safety_margin_tokens',
      label: '安全余量',
      description: '留给提示词、格式波动和分词差异的缓冲。',
      min: 512,
    },
  ]

  return (
    <article className="mt-4 rounded-2xl border border-black/10 bg-white/70 p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#55705e]">
            分析 Token 预算
          </p>
          <h3 className="mt-2 font-serif text-xl font-semibold text-[#17221b]">
            控制每批小说原文的大小
          </h3>
        </div>
        <div className="rounded-xl bg-[#e4ebe0] px-3 py-2 text-right">
          <p className="text-[10px] font-bold uppercase text-[#55705e]">可用正文</p>
          <p className="mt-0.5 font-mono text-sm font-semibold text-[#1e3227]">
            {tokenNumber.format(Math.max(0, available))} Token
          </p>
        </div>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        {fields.map((field) => (
          <label key={field.key} className="rounded-xl border border-black/8 bg-white/75 p-3">
            <span className="text-xs font-semibold text-black/58">{field.label}</span>
            <input
              type="number"
              min={field.min}
              max={field.max}
              step={1}
              value={budget[field.key]}
              onChange={(event) =>
                update({ [field.key]: Number(event.target.value) })
              }
              className="mt-2 w-full rounded-lg border border-black/10 bg-white px-3 py-2.5 font-mono text-sm text-[#17221b] outline-none transition focus:border-[#55705e] focus:ring-3 focus:ring-[#55705e]/10"
            />
            <span className="mt-2 block text-[11px] leading-4 text-black/38">
              {field.description}
            </span>
          </label>
        ))}
      </div>

      <p
        className={`mt-4 rounded-xl px-3 py-2.5 text-xs leading-5 ${
          available >= 64
            ? 'border border-emerald-900/10 bg-emerald-50 text-emerald-800'
            : 'border border-rose-900/10 bg-rose-50 text-rose-800'
        }`}
      >
        {available >= 64
          ? `每个批次最多安排 ${tokenNumber.format(available)} 个正文 Token；规划本身不会调用模型。`
          : '当前预算无法容纳正文，请增大上下文或输入上限，或减少输出预留和安全余量。'}
      </p>
    </article>
  )
}

function ProviderForm({
  config,
  models,
  isDiscovering,
  isTesting,
  discoveryError,
  testError,
  testResult,
  onChange,
  onDiscover,
  onTest,
}: ProviderFormProps) {
  const [showKey, setShowKey] = useState(false)
  const [modelMenuOpen, setModelMenuOpen] = useState(false)
  const [showAllModels, setShowAllModels] = useState(false)
  const [activeModelIndex, setActiveModelIndex] = useState(0)
  const modelInputId = useId()
  const modelListId = `${modelInputId}-listbox`
  const update = (change: Partial<BrowserProviderConfig>) =>
    onChange({ ...config, ...change })
  const modelQuery = config.model.trim().toLocaleLowerCase()
  const visibleModels =
    showAllModels || !modelQuery
      ? models
      : models.filter((model) => model.toLocaleLowerCase().includes(modelQuery))
  const connectionReady =
    config.provider === 'mock' ||
    Boolean(config.base_url.trim() && config.api_key.trim())
  const testReady = connectionReady && Boolean(config.model.trim())

  const selectModel = (model: string) => {
    update({ model })
    setModelMenuOpen(false)
    setShowAllModels(false)
    setActiveModelIndex(0)
  }

  return (
    <article className="rounded-2xl border border-black/10 bg-white/70 p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#55705e]">
            文本模型
          </p>
          <h3 className="mt-2 font-serif text-xl font-semibold text-[#17221b]">
            {config.model || '尚未选择模型'}
          </h3>
        </div>
        <span className="rounded-full bg-[#e4ebe0] px-2.5 py-1 text-[10px] font-bold uppercase text-[#31533f]">
          浏览器配置
        </span>
      </div>

      <div className="mt-5 space-y-4">
        <label className="block">
          <span className="text-xs font-semibold text-black/55">接口类型</span>
          <select
            value={config.provider}
            onChange={(event) => {
              const provider = event.target.value as 'mock' | 'openai' | 'deepseek'
              update({
                provider,
                base_url: provider === 'deepseek' ? 'https://api.deepseek.com/v1' : provider === 'openai' ? 'https://api.openai.com/v1' : config.base_url,
                model:
                  provider === 'mock'
                    ? 'novelatlas-mock-text'
                    : config.model.startsWith('novelatlas-mock-')
                      ? ''
                      : config.model,
              })
            }}
            className="mt-1.5 w-full rounded-xl border border-black/12 bg-white px-3.5 py-3 text-sm text-[#17221b] outline-none transition focus:border-[#55705e] focus:ring-3 focus:ring-[#55705e]/10"
          >
            <option value="mock">本地 Mock</option>
            <option value="openai">OpenAI Responses / 兼容接口</option>
            <option value="deepseek">DeepSeek Chat Completions</option>
          </select>
        </label>

        <label className="block">
          <span className="text-xs font-semibold text-black/55">API Base URL</span>
          <input
            type="url"
            value={config.base_url}
            onChange={(event) => update({ base_url: event.target.value })}
            disabled={config.provider === 'mock'}
            placeholder="https://api.openai.com/v1"
            spellCheck={false}
            className="mt-1.5 w-full rounded-xl border border-black/12 bg-white px-3.5 py-3 font-mono text-xs text-[#17221b] outline-none transition focus:border-[#55705e] focus:ring-3 focus:ring-[#55705e]/10 disabled:bg-black/[0.035] disabled:text-black/30"
          />
        </label>

        <label className="block">
          <span className="flex items-center justify-between gap-3 text-xs font-semibold text-black/55">
            API Key
            {config.provider !== 'mock' && (
              <button
                type="button"
                onClick={() => setShowKey((visible) => !visible)}
                className="text-[#55705e] hover:underline"
              >
                {showKey ? '隐藏' : '显示'}
              </button>
            )}
          </span>
          <input
            type={showKey ? 'text' : 'password'}
            value={config.api_key}
            onChange={(event) => update({ api_key: event.target.value })}
            disabled={config.provider === 'mock'}
            placeholder="sk-…"
            autoComplete="off"
            spellCheck={false}
            className="mt-1.5 w-full rounded-xl border border-black/12 bg-white px-3.5 py-3 font-mono text-xs text-[#17221b] outline-none transition focus:border-[#55705e] focus:ring-3 focus:ring-[#55705e]/10 disabled:bg-black/[0.035] disabled:text-black/30"
          />
        </label>

        <div>
          <label htmlFor={modelInputId} className="text-xs font-semibold text-black/55">
            模型
          </label>
          <div
            className="relative mt-1.5"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) {
                setModelMenuOpen(false)
              }
            }}
          >
            <input
              id={modelInputId}
              type="text"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={modelMenuOpen}
              aria-controls={modelListId}
              aria-activedescendant={
                modelMenuOpen && visibleModels[activeModelIndex]
                  ? `${modelListId}-${activeModelIndex}`
                  : undefined
              }
              value={config.model}
              onChange={(event) => {
                update({ model: event.target.value })
                setShowAllModels(false)
                setActiveModelIndex(0)
                setModelMenuOpen(models.length > 0)
              }}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  setModelMenuOpen(false)
                  return
                }
                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                  event.preventDefault()
                  setModelMenuOpen(true)
                  if (!modelMenuOpen) setShowAllModels(true)
                  const direction = event.key === 'ArrowDown' ? 1 : -1
                  setActiveModelIndex((current) => {
                    const count = visibleModels.length
                    return count === 0 ? 0 : (current + direction + count) % count
                  })
                  return
                }
                if (
                  event.key === 'Enter' &&
                  modelMenuOpen &&
                  visibleModels[activeModelIndex]
                ) {
                  event.preventDefault()
                  selectModel(visibleModels[activeModelIndex])
                }
              }}
              placeholder="选择或输入文本模型"
              spellCheck={false}
              className="w-full rounded-xl border border-black/12 bg-white py-3 pr-11 pl-3.5 font-mono text-xs text-[#17221b] outline-none transition focus:border-[#55705e] focus:ring-3 focus:ring-[#55705e]/10"
            />
            <button
              type="button"
              aria-label={modelMenuOpen ? '收起模型列表' : '展开全部模型'}
              disabled={models.length === 0}
              onClick={() => {
                setShowAllModels(true)
                setActiveModelIndex(0)
                setModelMenuOpen((open) => !open)
              }}
              className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-sm text-[#31533f] disabled:text-black/20"
            >
              {modelMenuOpen ? '▲' : '▼'}
            </button>
            {modelMenuOpen && (
              <div
                id={modelListId}
                role="listbox"
                aria-label="文本模型列表"
                className="absolute z-30 mt-1.5 max-h-64 w-full overflow-y-auto rounded-xl border border-black/12 bg-white py-1.5 shadow-xl"
              >
                {visibleModels.length > 0 ? (
                  visibleModels.map((model, index) => (
                    <button
                      key={model}
                      id={`${modelListId}-${index}`}
                      type="button"
                      role="option"
                      aria-selected={model === config.model}
                      onMouseEnter={() => setActiveModelIndex(index)}
                      onClick={() => selectModel(model)}
                      className={`block w-full px-3.5 py-2.5 text-left font-mono text-xs transition ${
                        index === activeModelIndex
                          ? 'bg-[#e4ebe0] text-[#1e3227]'
                          : 'text-[#17221b] hover:bg-black/[0.035]'
                      }`}
                    >
                      {model}
                    </button>
                  ))
                ) : (
                  <p className="px-3.5 py-3 text-xs text-black/42">
                    没有匹配的模型，可继续手动输入模型 ID。
                  </p>
                )}
              </div>
            )}
          </div>
          {models.length > 0 && (
            <span className="mt-1.5 block text-[11px] text-black/35">
              已读取 {models.length} 个接口可见模型；点击右侧箭头可浏览全部，输入文字可筛选。
            </span>
          )}
        </div>
      </div>

      <div className="mt-5 grid gap-2 sm:grid-cols-2">
        <button
          type="button"
          onClick={onDiscover}
          disabled={!connectionReady || isDiscovering}
          className="rounded-xl border border-[#31533f]/15 bg-[#edf2e9] px-3 py-3 text-xs font-semibold text-[#31533f] transition hover:bg-[#e3ece0] disabled:cursor-not-allowed disabled:opacity-45"
        >
          {isDiscovering ? '正在连接…' : '测试连接并读取模型'}
        </button>
        <button
          type="button"
          onClick={onTest}
          disabled={!testReady || isTesting}
          className="rounded-xl bg-[#1e3227] px-3 py-3 text-xs font-semibold text-white transition hover:bg-[#294535] disabled:cursor-not-allowed disabled:opacity-45"
        >
          {isTesting ? '正在调用…' : '测试文本调用'}
        </button>
      </div>

      {discoveryError && (
        <p className="mt-3 rounded-xl border border-rose-900/10 bg-rose-50 px-3 py-2.5 text-xs leading-5 text-rose-800">
          {discoveryError}
        </p>
      )}
      {testError && (
        <p className="mt-3 rounded-xl border border-rose-900/10 bg-rose-50 px-3 py-2.5 text-xs leading-5 text-rose-800">
          {testError}
        </p>
      )}
      {testResult && (
        <p className="mt-3 rounded-xl border border-emerald-900/10 bg-emerald-50 px-3 py-2.5 text-xs leading-5 text-emerald-800">
          {testResult}
        </p>
      )}
    </article>
  )
}

export function ModelGatewayPanel() {
  const [config, setConfig] = useState<BrowserModelGatewayConfig>(() =>
    loadBrowserModelConfig(),
  )
  const [isCached, setIsCached] = useState(() => hasCachedBrowserModelConfig())
  const [isDirty, setIsDirty] = useState(false)
  const [cacheMessage, setCacheMessage] = useState<string | null>(null)
  const [textModels, setTextModels] = useState<string[]>([])

  const status = useQuery({
    queryKey: ['model-gateway-status'],
    queryFn: fetchModelGatewayStatus,
    retry: 1,
  })
  const textCatalog = useMutation({
    mutationFn: discoverModels,
    onSuccess: (result) => setTextModels(result.models),
  })
  const textTest = useMutation({ mutationFn: testBrowserTextModel })

  const updateTextConfig = (value: BrowserProviderConfig) => {
    const previous = config.text
    const connectionChanged =
      previous.provider !== value.provider ||
      previous.base_url !== value.base_url ||
      previous.api_key !== value.api_key
    setConfig((current) => ({ ...current, text: value }))
    setIsDirty(true)
    setCacheMessage(null)
    textTest.reset()
    if (connectionChanged) {
      textCatalog.reset()
      setTextModels([])
    }
  }

  const updateAnalysisBudget = (value: AnalysisBudgetConfig) => {
    setConfig((current) => ({ ...current, analysis_budget: value }))
    setIsDirty(true)
    setCacheMessage(null)
  }

  const budgetIsValid =
    Number.isInteger(config.analysis_budget.context_window_tokens) &&
    Number.isInteger(config.analysis_budget.max_input_tokens) &&
    Number.isInteger(config.analysis_budget.output_reserve_tokens) &&
    Number.isInteger(config.analysis_budget.safety_margin_tokens) &&
    config.analysis_budget.context_window_tokens >= 512 &&
    config.analysis_budget.max_input_tokens >= 128 &&
    config.analysis_budget.output_reserve_tokens >= 32 &&
    config.analysis_budget.output_reserve_tokens <= 32_000 &&
    config.analysis_budget.safety_margin_tokens >= 512 &&
    availableContentTokens(config.analysis_budget) >= 64

  const save = () => {
    try {
      saveBrowserModelConfig(config)
      setIsCached(true)
      setIsDirty(false)
      setCacheMessage('配置已保存到当前浏览器。')
    } catch {
      setCacheMessage('浏览器拒绝了本地缓存，请检查隐私或存储设置。')
    }
  }

  const clear = () => {
    try {
      const reset = clearBrowserModelConfig()
      setConfig(reset)
      setIsCached(false)
      setIsDirty(false)
      setCacheMessage('浏览器中的模型配置与 API Key 已清除。')
      setTextModels([])
      textCatalog.reset()
      textTest.reset()
    } catch {
      setCacheMessage('无法清除浏览器缓存，请检查隐私或存储设置。')
    }
  }

  return (
    <section className="border-b border-black/10 bg-[#eef0e9] px-5 py-12 md:px-10 lg:px-16">
      <div className="mx-auto max-w-4xl">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-[#55705e]">
              Stage 04 · Text Model Gateway
            </p>
            <h2 className="mt-3 font-serif text-3xl font-semibold tracking-tight text-[#17221b]">
              在当前浏览器配置文本模型。
            </h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-black/48">
              该模型将用于分批概括小说与汇总详细大纲。浏览器配置不会写入后端文件。
            </p>
          </div>
          {status.data && (
            <div className="text-right text-xs leading-5 text-black/38">
              <p>服务端默认：{status.data.text.model}</p>
              <p>
                超时 {status.data.timeout_seconds} 秒 · 最多重试{' '}
                {status.data.max_retries} 次
              </p>
            </div>
          )}
        </div>

        <div className="mt-6 rounded-2xl border border-amber-800/15 bg-amber-50/80 p-4 text-sm leading-6 text-amber-900/75">
          <p className="font-semibold text-amber-900">浏览器缓存安全提示</p>
          <p className="mt-1">
            保存后，API Key 会以明文存在此站点的 localStorage 中，可能被浏览器扩展、开发者工具或同源脚本读取。仅建议在个人电脑和本地服务中使用；公共设备请使用服务端 `.env` 或在完成后立即清除。
          </p>
        </div>

        {status.isError && (
          <p className="mt-5 rounded-xl border border-rose-900/10 bg-rose-50 px-4 py-3 text-sm text-rose-800">
            无法读取服务端模型网关状态，但浏览器表单仍可编辑。
          </p>
        )}

        <div className="mt-8">
          <ProviderForm
            config={config.text}
            models={textModels}
            isDiscovering={textCatalog.isPending}
            isTesting={textTest.isPending}
            discoveryError={
              textCatalog.error instanceof Error ? textCatalog.error.message : null
            }
            testError={textTest.error instanceof Error ? textTest.error.message : null}
            testResult={
              textTest.data
                ? `${textTest.data.is_mock ? 'Mock' : '远程'}文本调用成功：${textTest.data.content}`
                : null
            }
            onChange={updateTextConfig}
            onDiscover={() => textCatalog.mutate(config.text)}
            onTest={() => textTest.mutate(config.text)}
          />
        </div>

        <AnalysisBudgetForm
          budget={config.analysis_budget}
          onChange={updateAnalysisBudget}
        />

        <div className="mt-5 flex flex-col gap-3 rounded-2xl border border-black/10 bg-white/55 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-semibold text-[#17221b]">
              {isDirty
                ? '页面配置有尚未保存的修改'
                : isCached
                  ? '当前浏览器已有缓存配置'
                  : '当前使用未保存的页面配置'}
            </p>
            {cacheMessage && (
              <p className="mt-1 text-xs text-black/42">{cacheMessage}</p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={clear}
              className="rounded-xl border border-rose-900/10 bg-white px-4 py-2.5 text-xs font-semibold text-rose-700 transition hover:bg-rose-50"
            >
              清除浏览器配置
            </button>
            <button
              type="button"
              onClick={save}
              disabled={!budgetIsValid}
              className="rounded-xl bg-[#1e3227] px-4 py-2.5 text-xs font-semibold text-white transition hover:bg-[#294535] disabled:cursor-not-allowed disabled:opacity-45"
            >
              保存到此浏览器（含 Key）
            </button>
          </div>
        </div>

        <p className="mt-5 text-xs leading-5 text-black/36">
          “测试连接并读取模型”调用兼容接口的 `/models`；测试文本会产生真实模型请求并可能产生费用。API Key 仅随操作请求发送，不会出现在响应中。
        </p>
      </div>
    </section>
  )
}
