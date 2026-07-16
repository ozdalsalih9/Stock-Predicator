import * as signalR from '@microsoft/signalr'
import { useEffect, useMemo, useState } from 'react'

import { api, ApiError } from '../lib/api'
import type { Analysis, Asset, MarketPriceUpdate, NewsArticle, PriceBar, SystemFreshness } from '../types'

const catalog: Asset[] = [
  ['BTCUSDT', 'BTC', 'Bitcoin', '2017-08-01'],
  ['ETHUSDT', 'ETH', 'Ethereum', '2017-08-01'],
  ['SOLUSDT', 'SOL', 'Solana', '2020-08-01'],
  ['BNBUSDT', 'BNB', 'BNB', '2017-11-01'],
  ['XRPUSDT', 'XRP', 'XRP', '2018-05-01'],
  ['ADAUSDT', 'ADA', 'Cardano', '2018-04-01'],
  ['LINKUSDT', 'LINK', 'Chainlink', '2019-01-01'],
  ['DOGEUSDT', 'DOGE', 'Dogecoin', '2019-07-01'],
].map(([symbol, baseAsset, displayName, dataStartsAt]) => ({
  symbol: symbol!,
  baseAsset: baseAsset!,
  quoteAsset: 'USDT',
  displayName: displayName!,
  assetClass: 'crypto',
  exchange: 'BINANCE',
  dataStartsAt: dataStartsAt!,
  latestPrice: null,
  latestPriceAt: null,
  dataState: 'missing',
}))

export function useMarketData(selectedSymbol: string, horizon: 30 | 90) {
  const [assets, setAssets] = useState<Asset[]>(catalog)
  const [bars, setBars] = useState<PriceBar[]>([])
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [analysisState, setAnalysisState] = useState<'loading' | 'ready' | 'no-production-model'>('loading')
  const [freshness, setFreshness] = useState<SystemFreshness | null>(null)
  const [news, setNews] = useState<NewsArticle[]>([])
  const [loading, setLoading] = useState(true)
  const [connectionState, setConnectionState] = useState<'connected' | 'unavailable'>('unavailable')
  const [notice, setNotice] = useState('Veri servisinin başlatılması bekleniyor.')

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([api.assets(controller.signal), api.freshness(controller.signal)])
      .then(([nextAssets, nextFreshness]) => {
        setAssets(nextAssets)
        setFreshness(nextFreshness)
        setConnectionState('connected')
        setNotice('')
      })
      .catch(() => {
        setConnectionState('unavailable')
        setNotice('Veri servisi çevrimdışı. Arayüz güvenli bekleme durumunda.')
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setAnalysis(null)
    setAnalysisState('loading')
    void Promise.allSettled([
      api.bars(selectedSymbol, '1h', 336, controller.signal),
      api.analysis(selectedSymbol, horizon, controller.signal),
      api.news(selectedSymbol, controller.signal),
    ]).then(([barsResult, analysisResult, newsResult]) => {
      if (barsResult.status === 'fulfilled') setBars(barsResult.value)
      if (newsResult.status === 'fulfilled') setNews(newsResult.value)
      if (analysisResult.status === 'fulfilled') {
        setAnalysis(analysisResult.value)
        setAnalysisState('ready')
      } else if (analysisResult.reason instanceof ApiError && analysisResult.reason.status === 404) {
        setAnalysisState('no-production-model')
      }
    })
    return () => controller.abort()
  }, [horizon, selectedSymbol])

  useEffect(() => {
    const connection = new signalR.HubConnectionBuilder()
      .withUrl('/hubs/market')
      .withAutomaticReconnect()
      .build()
    connection.on('marketPrices', (updates: MarketPriceUpdate[]) => {
      const updateBySymbol = new Map(updates.map((update) => [update.symbol, update]))
      setAssets((current) =>
        current.map((asset) => {
          const update = updateBySymbol.get(asset.symbol)
          return update === undefined
            ? asset
            : { ...asset, latestPrice: update.price, latestPriceAt: update.priceTime, dataState: 'fresh' }
        }),
      )
    })
    void connection.start().catch(() => undefined)
    return () => {
      void connection.stop()
    }
  }, [])

  return useMemo(
    () => ({ assets, bars, analysis, analysisState, freshness, news, loading, connectionState, notice }),
    [analysis, analysisState, assets, bars, connectionState, freshness, loading, news, notice],
  )
}
