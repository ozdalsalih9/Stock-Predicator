import { AlertTriangle, DatabaseZap, LoaderCircle } from 'lucide-react'
import type { ReactNode } from 'react'

export function LoadingSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="loading-skeleton" aria-label="İçerik yükleniyor" aria-busy="true">
      {Array.from({ length: rows }).map((_, index) => <i key={index} />)}
    </div>
  )
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <div className="data-state">
      <DatabaseZap size={22} />
      <strong>{title}</strong>
      <p>{description}</p>
      {action}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="data-state error" role="alert">
      <AlertTriangle size={22} />
      <strong>Doğrulanmış veriye ulaşılamadı</strong>
      <p>{message}</p>
      {onRetry && <button className="button secondary" onClick={onRetry}><LoaderCircle size={15} /> Yeniden dene</button>}
    </div>
  )
}
