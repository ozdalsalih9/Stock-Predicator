import { BrainCircuit, CalendarClock, CheckCircle2, Clock3 } from 'lucide-react'

import { ShadowAccumulationChart } from '../components/charts/ShadowAccumulationChart'
import { ErrorState, LoadingSkeleton } from '../components/ui/DataStates'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import { useProboraData } from '../context/ProboraDataContext'
import { formatPercent, formatUtc } from '../lib/format'

export function ShadowPage() {
  const { operations } = useProboraData()
  const dashboard = operations.predictionDashboard

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Canlı model sınavı"
        title="Shadow tahminler"
        description="Aday modeller gerçek piyasa verisinde tahmin üretir; sonuçlar kullanıcı sinyaline dönüşmeden önce değiştirilemez kanıt olarak birikir."
        action={<button className="button secondary" onClick={operations.refresh} disabled={operations.loading}>Veriyi yenile</button>}
      />

      {operations.error !== '' && <ErrorState message={operations.error} onRetry={operations.refresh} />}
      {dashboard === null ? <LoadingSkeleton rows={6} /> : (
        <>
          <section className="shadow-summary">
            <article><BrainCircuit size={18} /><span>Toplam gizli tahmin</span><strong>{dashboard.totalPredictions}</strong><small>Canlı kayıtlardan</small></article>
            <article><CheckCircle2 size={18} /><span>Olgunlaşan etiket</span><strong>{dashboard.totalMaturedPredictions}</strong><small>Sonucu ölçülebilen</small></article>
            <article><CalendarClock size={18} /><span>Aday model</span><strong>{dashboard.candidateCount}</strong><small>Kripto ve ABD</small></article>
            <article><Clock3 size={18} /><span>Son kontrol</span><strong>{formatUtc(dashboard.checkedAt)}</strong><small>UTC zaman standardı</small></article>
          </section>

          <section className="surface">
            <header className="section-heading"><div><p className="eyebrow">Kanıt birikimi</p><h2>Sistem neden zamana ihtiyaç duyuyor?</h2></div><StatusBadge tone="ai">Değerlendirme sürüyor</StatusBadge></header>
            <ShadowAccumulationChart dashboard={dashboard} />
          </section>

          <section className="shadow-model-list">
            {dashboard.models.map((model) => {
              const progress = model.requiredCalendarDays === 0 ? 0 : model.calendarDaysElapsed / model.requiredCalendarDays
              return (
                <article className="surface shadow-evidence-card" key={model.version}>
                  <header>
                    <div><p className="eyebrow">{model.assetClass === 'crypto' ? 'Kripto' : 'ABD hisse & ETF'}</p><h2>{model.horizonDays} {model.horizonUnit === 'trading_sessions' ? 'seanslık' : 'günlük'} model</h2></div>
                    <StatusBadge tone={model.state === 'evaluable' ? 'success' : model.state === 'collecting' ? 'warning' : 'muted'}>
                      {model.state === 'evaluable' ? 'Ölçülebilir' : model.state === 'collecting' ? 'Kanıt birikiyor' : 'İlk tahmin bekleniyor'}
                    </StatusBadge>
                  </header>
                  <div className="prediction-primary">
                    <strong>{model.predictionCount}</strong>
                    <span>Shadow tahmin</span>
                  </div>
                  <div className="maturity-progress">
                    <div><span>Olgunlaşma ilerlemesi</span><strong>{model.calendarDaysElapsed}/{model.requiredCalendarDays} {model.horizonUnit === 'trading_sessions' ? 'seans' : 'gün'}</strong></div>
                    <i><b style={{ width: `${Math.min(100, progress * 100)}%` }} /></i>
                    <p>{model.startedAt === null ? 'İlk inference bekleniyor.' : `${model.remainingCalendarDays} ${model.horizonUnit === 'trading_sessions' ? 'tamamlanmış seans' : 'gün'} sonra ilk değerlendirme mümkün.`}</p>
                  </div>
                  <dl>
                    <div><dt>Tahmin günü</dt><dd>{model.predictionDays}</dd></div>
                    <div><dt>Varlık kapsamı</dt><dd>{model.coveredAssets}/{model.totalAssets}</dd></div>
                    <div><dt>Kapsama oranı</dt><dd>{formatPercent(model.coveragePercent)}</dd></div>
                    <div><dt>Olgun etiket</dt><dd>{model.maturedPredictionCount}</dd></div>
                  </dl>
                  <footer><span title={model.version}>{model.version}</span><span>Başlangıç: {formatUtc(model.startedAt)}</span></footer>
                </article>
              )
            })}
          </section>
        </>
      )}
    </div>
  )
}
