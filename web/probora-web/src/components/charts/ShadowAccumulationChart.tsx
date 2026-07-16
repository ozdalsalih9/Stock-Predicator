import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import type { ShadowPredictionDashboard } from '../../types'

export function ShadowAccumulationChart({ dashboard }: { dashboard: ShadowPredictionDashboard }) {
  const starts = dashboard.models.flatMap((model) => model.startedAt ? [new Date(model.startedAt).getTime()] : [])
  const now = new Date(dashboard.checkedAt).getTime()
  const start = starts.length > 0 ? Math.min(...starts) : now
  const data = [
    { time: start, predictions: 0 },
    { time: Math.max(now, start + 1), predictions: dashboard.totalPredictions },
  ]
  const evaluation30 = start + 30 * 86_400_000
  const evaluation90 = start + 90 * 86_400_000

  return (
    <div className="shadow-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 15, right: 20, left: -20, bottom: 0 }}>
          <XAxis dataKey="time" type="number" domain={[start, evaluation90]} tickFormatter={(value: number) => new Intl.DateTimeFormat('tr-TR', { day: '2-digit', month: 'short', timeZone: 'UTC' }).format(value)} stroke="#70859a" axisLine={false} tickLine={false} fontSize={10} />
          <YAxis allowDecimals={false} stroke="#70859a" axisLine={false} tickLine={false} fontSize={10} />
          <Tooltip labelFormatter={(value) => new Intl.DateTimeFormat('tr-TR', { dateStyle: 'medium', timeZone: 'UTC' }).format(Number(value))} formatter={(value) => [Number(value), 'Shadow tahmin']} />
          <ReferenceLine x={evaluation30} stroke="#f0b868" strokeDasharray="4 5" label={{ value: '30 gün', fill: '#f0b868', fontSize: 10 }} />
          <ReferenceLine x={evaluation90} stroke="#9c82ee" strokeDasharray="4 5" label={{ value: '90 gün', fill: '#b7a8f5', fontSize: 10 }} />
          <Line type="monotone" dataKey="predictions" stroke="#9c82ee" strokeWidth={2.5} dot={{ r: 3, fill: '#9c82ee' }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      <p>API şu anda yalnız başlangıç ve güncel toplamı sağlar; ara noktalar uydurulmaz. Yeni günlük kayıtlarla çizgi gerçek ölçümler üzerinden büyür.</p>
    </div>
  )
}
