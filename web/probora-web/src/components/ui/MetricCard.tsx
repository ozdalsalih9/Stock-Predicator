import type { LucideIcon } from 'lucide-react'
import { useEffect, useState } from 'react'

interface MetricCardProps {
  icon: LucideIcon
  label: string
  value: number
  suffix?: string
  detail: string
  accent?: 'mint' | 'blue' | 'violet' | 'amber'
}

export function MetricCard({ icon: Icon, label, value, suffix = '', detail, accent = 'mint' }: MetricCardProps) {
  const animationKey = `probora-metric-${label}`
  const [alreadyAnimated] = useState(() => typeof window !== 'undefined' && sessionStorage.getItem(animationKey) === 'seen')
  const [reduceMotion] = useState(() => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const skipAnimation = alreadyAnimated || reduceMotion
  const [displayValue, setDisplayValue] = useState(skipAnimation ? value : 0)

  useEffect(() => {
    if (skipAnimation || value <= 0) return
    const startedAt = performance.now()
    let frame = 0
    const update = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / 760)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplayValue(Math.round(value * eased))
      if (progress < 1) frame = requestAnimationFrame(update)
      else sessionStorage.setItem(animationKey, 'seen')
    }
    frame = requestAnimationFrame(update)
    return () => cancelAnimationFrame(frame)
  }, [animationKey, skipAnimation, value])

  return (
    <article className={`metric-card ${accent}`}>
      <div><Icon size={17} /><span>{label}</span></div>
      <strong>{skipAnimation ? value : displayValue}{suffix}</strong>
      <p>{detail}</p>
    </article>
  )
}
