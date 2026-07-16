import type { Analysis, Asset, ModelCard, NewsArticle, PriceBar, ShadowCollectorDashboard, ShadowPredictionDashboard, SystemFreshness, UsEquityShadowDashboard } from '../types'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, headers: { Accept: 'application/json' } })
  if (!response.ok) {
    let message = 'İstek tamamlanamadı.'
    try {
      const problem = (await response.json()) as { title?: string; detail?: string }
      message = problem.detail ?? problem.title ?? message
    } catch {
      // Keep the safe fallback for non-JSON proxy errors.
    }
    throw new ApiError(response.status, message)
  }
  return (await response.json()) as T
}

export const api = {
  assets: (signal?: AbortSignal) => get<Asset[]>('/api/v1/assets', signal),
  bars: (symbol: string, interval = '1h', limit = 336, signal?: AbortSignal) =>
    get<PriceBar[]>(`/api/v1/assets/${encodeURIComponent(symbol)}/bars?interval=${interval}&limit=${limit}`, signal),
  analysis: (symbol: string, horizon: 30 | 90, signal?: AbortSignal) =>
    get<Analysis>(
      `/api/v1/assets/${encodeURIComponent(symbol)}/analyses/latest?horizonDays=${horizon}&includeShadowPreview=true`,
      signal,
    ),
  news: (symbol: string, signal?: AbortSignal) =>
    get<NewsArticle[]>(`/api/v1/assets/${encodeURIComponent(symbol)}/news?limit=12`, signal),
  freshness: (signal?: AbortSignal) => get<SystemFreshness>('/api/v1/system/freshness', signal),
  shadowCollector: (signal?: AbortSignal) =>
    get<ShadowCollectorDashboard>('/api/v1/system/shadow-collector', signal),
  usEquityShadow: (signal?: AbortSignal) =>
    get<UsEquityShadowDashboard>('/api/v1/system/us-equity-shadow', signal),
  shadowPredictions: (signal?: AbortSignal) =>
    get<ShadowPredictionDashboard>('/api/v1/system/shadow-predictions', signal),
  modelCard: (version: string, signal?: AbortSignal) =>
    get<ModelCard>(`/api/v1/models/${encodeURIComponent(version)}/card`, signal),
}
