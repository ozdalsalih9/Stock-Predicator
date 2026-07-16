import { formatPercent } from '../../lib/format'

export function ProbabilityBar({ up, neutral, down }: { up: number; neutral: number; down: number }) {
  const values = [
    { key: 'down', label: 'Düşüş', value: down },
    { key: 'neutral', label: 'Yatay', value: neutral },
    { key: 'up', label: 'Yükseliş', value: up },
  ]
  const highest = values.reduce((winner, current) => current.value > winner.value ? current : winner)

  return (
    <div className="probability-visual">
      <div className="probability-stack" role="img" aria-label={`Düşüş ${formatPercent(down)}, yatay ${formatPercent(neutral)}, yükseliş ${formatPercent(up)}`}>
        {values.map((item) => <i className={item.key} key={item.key} style={{ width: `${item.value * 100}%` }} />)}
      </div>
      <div className="probability-legend">
        {values.map((item) => (
          <div className={item.key === highest.key ? 'highest' : ''} key={item.key}>
            <span><i className={item.key} />{item.label}</span>
            <strong>{formatPercent(item.value)}</strong>
          </div>
        ))}
      </div>
      <p>En yüksek olasılık, kesin sonuç anlamına gelmez.</p>
    </div>
  )
}
