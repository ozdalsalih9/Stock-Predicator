import type { ReactNode } from 'react'

export type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'ai' | 'muted'

export function StatusBadge({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return <span className={`status-badge ${tone}`}><i />{children}</span>
}
