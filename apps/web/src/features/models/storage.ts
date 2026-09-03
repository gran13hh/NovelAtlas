import type {
  AnalysisBudgetConfig,
  BrowserModelGatewayConfig,
  BrowserProviderConfig,
} from './api'

const STORAGE_KEY = 'novelatlas.model-gateway.v1'

export const DEFAULT_BROWSER_MODEL_CONFIG: BrowserModelGatewayConfig = {
  version: 2,
  text: {
    provider: 'mock',
    model: 'novelatlas-mock-text',
    base_url: 'https://api.openai.com/v1',
    api_key: '',
  },
  analysis_budget: {
    context_window_tokens: 128_000,
    max_input_tokens: 24_000,
    output_reserve_tokens: 4_000,
    safety_margin_tokens: 2_000,
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

function isAnalysisBudget(value: unknown): value is AnalysisBudgetConfig {
  if (typeof value !== 'object' || value === null) return false
  return (
    'context_window_tokens' in value &&
    typeof value.context_window_tokens === 'number' &&
    'max_input_tokens' in value &&
    typeof value.max_input_tokens === 'number' &&
    'output_reserve_tokens' in value &&
    typeof value.output_reserve_tokens === 'number' &&
    'safety_margin_tokens' in value &&
    typeof value.safety_margin_tokens === 'number'
  )
}

function cloneDefaults(): BrowserModelGatewayConfig {
  return {
    version: 2,
    text: { ...DEFAULT_BROWSER_MODEL_CONFIG.text },
    analysis_budget: { ...DEFAULT_BROWSER_MODEL_CONFIG.analysis_budget },
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
      value.version === 2 &&
      'text' in value &&
      isProviderConfig(value.text) &&
      'analysis_budget' in value &&
      isAnalysisBudget(value.analysis_budget)
    ) {
      return {
        version: 2,
        text: { ...value.text },
        analysis_budget: { ...value.analysis_budget },
      }
    }
    if (
      typeof value === 'object' &&
      value !== null &&
      'version' in value &&
      value.version === 1 &&
      'text' in value &&
      isProviderConfig(value.text)
    ) {
      return {
        version: 2,
        text: { ...value.text },
        analysis_budget: { ...DEFAULT_BROWSER_MODEL_CONFIG.analysis_budget },
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
