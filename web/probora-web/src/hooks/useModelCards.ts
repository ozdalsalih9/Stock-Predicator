import { useEffect, useState } from 'react'

import { api } from '../lib/api'
import type { ModelCard, ShadowPredictionModel } from '../types'

export function useModelCards(models: ShadowPredictionModel[]) {
  const [cards, setCards] = useState<Record<string, ModelCard>>({})
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (models.length === 0) return
    const controller = new AbortController()
    setLoading(true)
    void Promise.allSettled(models.map((model) => api.modelCard(model.version, controller.signal)))
      .then((results) => {
        const next: Record<string, ModelCard> = {}
        results.forEach((result) => {
          if (result.status === 'fulfilled') next[result.value.version] = result.value
        })
        setCards(next)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [models])

  return { cards, loading }
}
