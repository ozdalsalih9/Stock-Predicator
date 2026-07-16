import { useCallback, useEffect, useState } from 'react'

import { api } from '../lib/api'
import type { ShadowCollectorDashboard, ShadowPredictionDashboard, UsEquityShadowDashboard } from '../types'

export function useOperationsDashboard(enabled: boolean) {
  const [dashboard, setDashboard] = useState<ShadowCollectorDashboard | null>(null)
  const [equityDashboard, setEquityDashboard] = useState<UsEquityShadowDashboard | null>(null)
  const [predictionDashboard, setPredictionDashboard] = useState<ShadowPredictionDashboard | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision((current) => current + 1), [])

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    const load = () => {
      setLoading(true)
      void Promise.all([
        api.shadowCollector(controller.signal),
        api.usEquityShadow(controller.signal),
        api.shadowPredictions(controller.signal),
      ])
        .then(([derivatives, equities, predictions]) => {
          setDashboard(derivatives)
          setEquityDashboard(equities)
          setPredictionDashboard(predictions)
          setError('')
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted) {
            setError(reason instanceof Error ? reason.message : 'Operasyon verisi alınamadı.')
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false)
        })
    }
    load()
    const interval = window.setInterval(load, 30_000)
    return () => {
      controller.abort()
      window.clearInterval(interval)
    }
  }, [enabled, revision])

  return { dashboard, equityDashboard, predictionDashboard, loading, error, refresh }
}
