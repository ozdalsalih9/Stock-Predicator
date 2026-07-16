export function formatPrice(value: number | null): string {
  if (value === null) return '—'
  const maximumFractionDigits = value >= 100 ? 2 : value >= 1 ? 4 : 6
  return new Intl.NumberFormat('tr-TR', { maximumFractionDigits }).format(value)
}

export function formatPercent(value: number, signed = false): string {
  const formatted = new Intl.NumberFormat('tr-TR', {
    style: 'percent',
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
    signDisplay: signed ? 'always' : 'auto',
  }).format(value)
  return formatted
}

export function relativeTime(value: string | null): string {
  if (value === null) return 'veri yok'
  const differenceMinutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60_000))
  if (differenceMinutes < 1) return 'şimdi'
  if (differenceMinutes < 60) return `${differenceMinutes} dk önce`
  const hours = Math.round(differenceMinutes / 60)
  return hours < 48 ? `${hours} sa önce` : `${Math.round(hours / 24)} gün önce`
}

export function formatUtc(value: string | null): string {
  if (value === null) return '—'
  return `${new Intl.DateTimeFormat('tr-TR', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'UTC',
  }).format(new Date(value))} UTC`
}
