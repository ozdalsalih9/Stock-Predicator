import { AlertTriangle, BrainCircuit, Clock3, Database, Gauge, ShieldCheck } from 'lucide-react'

import { formatPercent, formatUtc } from '../../lib/format'
import type { Analysis } from '../../types'
import { ProbabilityBar } from '../charts/ProbabilityBar'
import { ReturnRangeChart } from '../charts/ReturnRangeChart'
import { RiskIndicator } from '../charts/RiskIndicator'
import { EmptyState } from '../ui/DataStates'
import { InfoTooltip } from '../ui/InfoTooltip'
import { StatusBadge } from '../ui/StatusBadge'

export function AnalysisPanel({ analysis, horizon, horizonUnit = 'gün' }: { analysis: Analysis | null; horizon: 30 | 90; horizonUnit?: 'gün' | 'seans' }) {
  if (analysis === null) {
    return (
      <section className="surface analysis-card">
        <header className="section-heading"><div><p className="eyebrow">{horizon} {horizonUnit}</p><h2>Tahmin değerlendirmesi</h2></div></header>
        <EmptyState title="Yeterli sonuç bulunmuyor" description="Bu model için henüz yayınlanabilir veya Shadow önizleme sonucu oluşmadı." />
      </section>
    )
  }

  const quiet = analysis.status !== 'signal' || analysis.confidenceScore < 0.1 || !analysis.directionEligible
  return (
    <section className="surface analysis-card">
      <header className="section-heading">
        <div>
          <p className="eyebrow">{horizon} {horizonUnit} · {analysis.isShadow ? 'Shadow değerlendirmesi' : 'Production'}</p>
          <h2>{quiet ? 'Belirgin sinyal yok' : 'Ölçülmüş yön sinyali'} <InfoTooltip /></h2>
        </div>
        <StatusBadge tone={analysis.isShadow ? 'ai' : 'success'}>{analysis.isShadow ? 'Shadow' : 'Production'}</StatusBadge>
      </header>

      {analysis.isShadow && (
        <div className="inline-notice ai"><BrainCircuit size={18} /><p><strong>Test sonucu</strong> Bu çıktı canlı kanıt toplar ancak yatırım sinyali olarak yayınlanmaz.</p></div>
      )}
      {quiet && (
        <div className="inline-notice warning"><AlertTriangle size={18} /><p><strong>Belirsizlik yüksek.</strong> Sınıflar arasındaki fark güven kapısını geçmedi.</p></div>
      )}

      {analysis.directionEligible ? <ProbabilityBar {...analysis.direction} /> : (
        <div className="inline-notice muted"><Gauge size={18} /><p>Yön modeli doğrulama kapısını geçmedi. Yalnız risk ve getiri senaryosu gösteriliyor.</p></div>
      )}

      <div className="analysis-subgrid">
        <div>
          <h3>Getiri belirsizlik aralığı</h3>
          <ReturnRangeChart {...analysis.expectedReturn} />
        </div>
        <div>
          <h3>Risk profili</h3>
          <RiskIndicator score={analysis.riskScore} />
        </div>
      </div>

      <dl className="audit-grid">
        <div><dt><ShieldCheck size={13} /> Model güveni</dt><dd>{formatPercent(analysis.confidenceScore)}</dd></div>
        <div><dt><Database size={13} /> Model sürümü</dt><dd title={analysis.modelVersion}>{analysis.modelVersion}</dd></div>
        <div><dt><Clock3 size={13} /> Tahmin zamanı</dt><dd>{formatUtc(analysis.analysisTime)}</dd></div>
        <div><dt><Database size={13} /> Veri kaynağı</dt><dd>{analysis.symbol.endsWith('USDT') ? 'Binance' : 'Twelve Data'}</dd></div>
      </dl>
    </section>
  )
}
