import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export function ModelComparisonChart({ brier, baseline }: { brier: number | null; baseline: number | null }) {
  if (brier === null || baseline === null) return null
  const data = [{ name: 'Brier', model: brier, baseline }]
  return (
    <div className="comparison-chart" aria-label={`Model Brier ${brier.toFixed(3)}, baseline ${baseline.toFixed(3)}. Düşük değer daha iyidir.`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="rgba(148,179,207,.10)" />
          <XAxis dataKey="name" stroke="#70859a" axisLine={false} tickLine={false} fontSize={10} />
          <YAxis stroke="#70859a" axisLine={false} tickLine={false} fontSize={10} />
          <Tooltip />
          <Bar dataKey="model" name="Model" fill="#55dfb2" radius={[5, 5, 0, 0]} />
          <Bar dataKey="baseline" name="Baseline" fill="#70859a" radius={[5, 5, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
