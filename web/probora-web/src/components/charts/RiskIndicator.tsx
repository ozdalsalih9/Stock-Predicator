export function RiskIndicator({ score }: { score: number }) {
  const percent = Math.max(0, Math.min(100, score * 100))
  const level = percent <= 30 ? 'Düşük' : percent <= 60 ? 'Orta' : percent <= 80 ? 'Yüksek' : 'Çok yüksek'
  return (
    <div className="risk-indicator">
      <div className="risk-scale" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(percent)} aria-label={`Risk skoru ${Math.round(percent)}, ${level}`}>
        <i /><i /><i /><i />
        <b style={{ left: `${percent}%` }} />
      </div>
      <div><strong>{Math.round(percent)}/100</strong><span>{level} risk</span></div>
      <p>Risk skoru bir al veya sat önerisi değildir.</p>
    </div>
  )
}
