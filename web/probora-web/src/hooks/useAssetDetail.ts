import { useEffect, useState } from 'react'

import { api, ApiError } from '../lib/api'
import type { Analysis, Asset, NewsArticle, PriceBar } from '../types'

export function useAssetDetail(asset: Asset | undefined) {
  const [bars, setBars] = useState<PriceBar[]>([])
  const [analyses, setAnalyses] = useState<Record<30 | 90, Analysis | null>>({ 30: null, 90: null })
  const [news, setNews] = useState<NewsArticle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (asset === undefined) {
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError('')
    const interval = asset.assetClass === 'crypto' ? '1h' : '1d'
    const limit = asset.assetClass === 'crypto' ? 2000 : 180
    void Promise.allSettled([
      api.bars(asset.symbol, interval, limit, controller.signal),
      api.analysis(asset.symbol, 30, controller.signal),
      api.analysis(asset.symbol, 90, controller.signal),
      api.news(asset.symbol, controller.signal),
    ]).then(([barsResult, analysis30, analysis90, newsResult]) => {
      if (barsResult.status === 'fulfilled') setBars(barsResult.value)
      else if (!controller.signal.aborted) setError('Fiyat serisine ulaşılamıyor. Son doğrulanmış veri gösterilemiyor.')
      setAnalyses({
        30: analysis30.status === 'fulfilled' ? analysis30.value : null,
        90: analysis90.status === 'fulfilled' ? analysis90.value : null,
      })
      if (newsResult.status === 'fulfilled') setNews(newsResult.value)
      const unexpectedAnalysisError = [analysis30, analysis90].find(
        (result) => result.status === 'rejected' && !(result.reason instanceof ApiError && result.reason.status === 404),
      )
      if (unexpectedAnalysisError !== undefined && !controller.signal.aborted) {
        setError('Tahmin servisine şu anda ulaşılamıyor.')
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [asset])

  return { bars, analyses, news, loading, error }
}
