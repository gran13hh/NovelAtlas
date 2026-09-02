export type ModelProviderStatus = {
  provider: 'mock' | 'openai'
  model: string
  base_url: string | null
  configured: boolean
  is_mock: boolean
  missing_settings: string[]
}

export type ModelGatewayStatus = {
  text: ModelProviderStatus
  image: ModelProviderStatus
  timeout_seconds: number
  max_retries: number
}

export type BrowserProviderConfig = {
  provider: 'mock' | 'openai'
  model: string
  base_url: string
  api_key: string
}

export type BrowserModelGatewayConfig = {
  version: 1
  text: BrowserProviderConfig
  image: BrowserProviderConfig
}

export type ModelCatalogResult = {
  provider: 'mock' | 'openai'
  models: string[]
}

export type TextGenerationResult = {
  provider: 'mock' | 'openai'
  model: string
  content: string
  request_id: string | null
  usage: {
    input_tokens: number | null
    output_tokens: number | null
    total_tokens: number | null
  } | null
  is_mock: boolean
}

export type ImageGenerationResult = {
  provider: 'mock' | 'openai'
  model: string
  request_id: string | null
  image_base64: string | null
  image_url: string | null
  revised_prompt: string | null
  is_mock: boolean
}

function responseMessage(payload: unknown, fallback: string): string {
  if (typeof payload !== 'object' || payload === null || !('detail' in payload)) {
    return fallback
  }
  if (typeof payload.detail === 'string') return payload.detail
  if (Array.isArray(payload.detail)) {
    const issue = payload.detail[0] as unknown
    if (
      typeof issue === 'object' &&
      issue !== null &&
      'msg' in issue &&
      typeof issue.msg === 'string'
    ) {
      const location =
        'loc' in issue && Array.isArray(issue.loc)
          ? issue.loc.slice(1).map(String).join('.')
          : ''
      return location ? `${location}：${issue.msg}` : issue.msg
    }
  }
  if (
    typeof payload.detail === 'object' &&
    payload.detail !== null &&
    'message' in payload.detail &&
    typeof payload.detail.message === 'string'
  ) {
    return payload.detail.message
  }
  return fallback
}

async function jsonResponse<T>(response: Response, fallback: string): Promise<T> {
  if (response.ok) return response.json() as Promise<T>
  const payload = (await response.json().catch(() => null)) as unknown
  throw new Error(responseMessage(payload, fallback))
}

export async function fetchModelGatewayStatus(): Promise<ModelGatewayStatus> {
  const response = await fetch('/api/models/config')
  return jsonResponse(response, `读取模型配置失败（${response.status}）`)
}

export async function testTextModel(): Promise<TextGenerationResult> {
  const response = await fetch('/api/models/test/text', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt: 'NovelAtlas 模型网关连接测试',
      instructions: '请返回简短的连接确认。',
      max_output_tokens: 128,
    }),
  })
  return jsonResponse(response, `文本模型测试失败（${response.status}）`)
}

export async function testImageModel(): Promise<ImageGenerationResult> {
  const response = await fetch('/api/models/test/image', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt: 'NovelAtlas 模型网关连接测试：虚构山河地图',
      size: '1024x1024',
    }),
  })
  return jsonResponse(response, `图片模型测试失败（${response.status}）`)
}

export async function discoverModels(
  capability: 'text' | 'image',
  config: BrowserProviderConfig,
): Promise<ModelCatalogResult> {
  const connection = {
    provider: config.provider,
    base_url: config.base_url,
    api_key: config.api_key,
  }
  const response = await fetch(`/api/models/browser/catalog/${capability}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config: connection }),
  })
  return jsonResponse(response, `读取模型列表失败（${response.status}）`)
}

export async function testBrowserTextModel(
  config: BrowserProviderConfig,
): Promise<TextGenerationResult> {
  const response = await fetch('/api/models/browser/test/text', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      config,
      request: {
        prompt: 'NovelAtlas 浏览器模型配置连接测试',
        instructions: '请返回简短的连接确认。',
        max_output_tokens: 128,
      },
    }),
  })
  return jsonResponse(response, `文本模型测试失败（${response.status}）`)
}

export async function testBrowserImageModel(
  config: BrowserProviderConfig,
): Promise<ImageGenerationResult> {
  const response = await fetch('/api/models/browser/test/image', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      config,
      request: {
        prompt: 'NovelAtlas 浏览器模型配置连接测试：虚构山河地图',
        size: '1024x1024',
      },
    }),
  })
  return jsonResponse(response, `图片模型测试失败（${response.status}）`)
}
