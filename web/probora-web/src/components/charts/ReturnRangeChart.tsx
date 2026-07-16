import { formatPercent } from '../../lib/format'

export function ReturnRangeChart({ p10, p50, p90 }: { p10: number; p50: number; p90: number }) {
  const minimum = Math.min(-0.4, p10)
  const maximum = Math.max(0.4, p90)
  const scale = (value: number) => ((value - minimum) / (maximum - minimum)) * 100

  return (
    <div className="return-range">
      <div className="return-track" role="img" aria-label={`Kötümser ${formatPercent(p10, true)}, merkez ${formatPercent(p50, true)}, iyimser ${formatPercent(p90, true)}`}>
        <i className="return-band" style={{ left: `${scale(p10)}%`, width: `${scale(p90) - scale(p10)}%` }} />
        <i className="return-zero" style={{ left: `${scale(0)}%` }} />
        <b className="return-marker low" style={{ left: `${scale(p10)}%` }} />
        <b className="return-marker center" style={{ left: `${scale(p50)}%` }} />
        <b className="return-marker high" style={{ left: `${scale(p90)}%` }} />
      </div>
      <div className="return-labels">
        <span><small>P10 · Kötümser</small><strong>{formatPercent(p10, true)}</strong></span>
        <span><small>P50 · Merkez</small><strong>{formatPercent(p50, true)}</strong></span>
        <span><small>P90 · İyimser</small><strong>{formatPercent(p90, true)}</strong></span>
      </div>
    </div>
  )
}
