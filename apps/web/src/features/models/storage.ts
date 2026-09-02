import type { BrowserModelGatewayConfig, BrowserProviderConfig } from './api'

const STORAGE_KEY = 'novelatlas.model-gateway.v1'

export const DEFAULT_BROWSER_MODEL_CONFIG: BrowserModelGatewayConfig = {
  version: 1,
  text: {
    provider: 'mock',
    model: 'novelatlas-mock-text',
    base_url: 'https://api.openai.com/v1',
    api_key: '',
  },
  image: {
    provider: 'mock',
    model: 'novelatlas-mock-image',
    base_url: 'https://api.openai.com/v1',
    api_key: '',
  },
}

function isProviderConfig(value: unknown): value is BrowserProviderConfig {
  if (typeof value !== 'object' || value === null) return false
  return (
    'provider' in value &&
    (value.provider === 'mock' || value.provider === 'openai') &&
    'model' in value &&
    typeof value.model === 'string' &&
    'base_url' in value &&
    typeof value.base_url === 'string' &&
    'api_key' in value &&
    typeof value.api_key === 'string'
  )
}

function cloneDefaults(): BrowserModelGatewayConfig {
  return {
    version: 1,
    text: { ...DEFAULT_BROWSER_MODEL_CONFIG.text },
    image: { ...DEFAULT_BROWSER_MODEL_CONFIG.image },
  }
}

export function loadBrowserModelConfig(): BrowserModelGatewayConfig {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return cloneDefaults()
    const value = JSON.parse(raw) as unknown
    if (
      typeof value === 'object' &&
      value !== null &&
      'version' in value &&
      value.version === 1 &&
      'text' in value &&
      isProviderConfig(value.text) &&
      'image' in value &&
      isProviderConfig(value.image)
    ) {
      return {
        version: 1,
        text: { ...value.text },
        image: { ...value.image },
      }
    }
  } catch {
    // Invalid or unavailable storage falls back to safe local Mock defaults.
  }
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Storage can be unavailable in hardened or private browser contexts.
  }
  return cloneDefaults()
}

export function saveBrowserModelConfig(config: BrowserModelGatewayConfig): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
}

export function clearBrowserModelConfig(): BrowserModelGatewayConfig {
  window.localStorage.removeItem(STORAGE_KEY)
  return cloneDefaults()
}

export function hasCachedBrowserModelConfig(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== null
  } catch {
    return false
  }
}
