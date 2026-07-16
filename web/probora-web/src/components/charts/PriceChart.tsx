import { useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { formatPrice } from '../../lib/format'
import type { PriceBar } from '../../types'
import { EmptyState } from '../ui/DataStates'

type Range = '1H' | '1D' | '7D' | '30D' | '90D'

const rangeHours: Record<Range, number> = { '1H': 2, '1D': 24, '7D': 168, '30D': 720, '90D': 2160 }

export function PriceChart({ bars, interval = '1h' }: { bars: PriceBar[]; interval?: '1h' | '1d' }) {
  const [range, setRange] = useState<Range>(interval === '1d' ? '90D' : '7D')
  const data = useMemo(() => {
    const points = interval === '1d'
      ? range === '90D' ? 90 : range === '30D' ? 30 : range === '7D' ? 7 : 2
      : rangeHours[range]
    return bars.slice(-points).map((bar) => ({
      time: new Date(bar.openTime).getTime(),
      close: bar.close,
    }))
  }, [bars, interval, range])

  if (bars.length < 2) {
    return <EmptyState title="Fiyat serisi bekleniyor" description="Seçilen varlık için yeterli doğrulanmış fiyat noktası henüz bulunmuyor." />
  }

  return (
    <div className="chart-block">
      <div className="chart-toolbar" aria-label="Grafik zaman aralığı">
        {(Object.keys(rangeHours) as Range[]).map((item) => (
          <button className={range === item ? 'active' : ''} key={item} onClick={() => setRange(item)}>{item}</button>
        ))}
      </div>
      <div className="price-chart" aria-label={`${range} fiyat hareketi`}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 12, right: 4, left: -14, bottom: 0 }}>
            <defs>
              <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#55dfb2" stopOpacity={0.28} />
                <stop offset="100%" stopColor="#55dfb2" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="rgba(148, 179, 207, .10)" />
            <XAxis
              dataKey="time"
              type="number"
              domain={['dataMin', 'dataMax']}
              tickFormatter={(value: number) => new Intl.DateTimeFormat('tr-TR', { day: '2-digit', month: 'short', timeZone: 'UTC' }).format(value)}
              stroke="#70859a"
              tickLine={false}
              axisLine={false}
              fontSize={10}
              minTickGap={38}
            />
            <YAxis domain={['auto', 'auto']} tickFormatter={(value: number) => formatPrice(value)} stroke="#70859a" tickLine={false} axisLine={false} fontSize={10} width={65} />
            <Tooltip
              contentStyle={{ background: '#0d1b2b', border: '1px solid rgba(148,179,207,.18)', borderRadius: 8, fontSize: 11 }}
              labelFormatter={(value) => new Intl.DateTimeFormat('tr-TR', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(Number(value))}
              formatter={(value) => [formatPrice(Number(value)), 'Kapanış']}
            />
            <Area type="monotone" dataKey="close" stroke="#55dfb2" strokeWidth={2} fill="url(#priceFill)" isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="chart-summary">Grafik yalnızca API’den gelen doğrulanmış kapanış verilerini gösterir. Saatler UTC’dir.</p>
    </div>
  )
}
