import { BrainCircuit, CalendarDays, FlaskConical, ShieldQuestion } from 'lucide-react'
import { useMemo, useState } from 'react'

import { ModelComparisonChart } from '../components/charts/ModelComparisonChart'
import { EmptyState, LoadingSkeleton } from '../components/ui/DataStates'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import { useProboraData } from '../context/ProboraDataContext'
import { useModelCards } from '../hooks/useModelCards'
import { formatPercent, formatUtc } from '../lib/format'

function metric(metrics: Record<string, number> | undefined, ...names: string[]) {
  if (metrics === undefined) return null
  for (const name of names) if (Number.isFinite(metrics[name])) return metrics[name] ?? null
  return null
}

export function ModelsPage() {
  const { operations } = useProboraData()
  const models = useMemo(() => operations.predictionDashboard?.models ?? [], [operations.predictionDashboard?.models])
  const { cards, loading } = useModelCards(models)
  const [selectedVersion, setSelectedVersion] = useState('')
  const selectedModel = useMemo(() => models.find((model) => model.version === selectedVersion) ?? models[0], [models, selectedVersion])
  const card = selectedModel === undefined ? undefined : cards[selectedModel.version]
  const brier = metric(card?.metrics, 'brier_score', 'test_brier_score')
  const baselineBrier = metric(card?.metrics, 'baseline_brier_score')
  const ece = metric(card?.metrics, 'ece', 'expected_calibration_error')
  const riskError = metric(card?.metrics, 'risk_error', 'risk_mae')
  const coverage = metric(card?.metrics, 'interval_coverage', 'coverage')
  const beatsBaseline = brier !== null && baselineBrier !== null && brier < baselineBrier

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Model yönetişimi"
        title="Model performansı"
        description="Aday modellerin eğitim ve canlı Shadow kanıtları baseline, kalibrasyon ve kapsam kapılarıyla birlikte değerlendirilir."
      />

      {models.length === 0 ? <EmptyState title="Aday model bulunmuyor" description="Registry bir Shadow adayı atadığında performans kartı burada oluşur." /> : (
        <>
          <label className="model-selector">
            <span>İncelenen model</span>
            <select value={selectedModel?.version ?? ''} onChange={(event) => setSelectedVersion(event.target.value)}>
              {models.map((model) => <option value={model.version} key={model.version}>{model.assetClass === 'crypto' ? 'Kripto' : 'ABD'} · {model.horizonDays} {model.horizonUnit === 'trading_sessions' ? 'seans' : 'gün'}</option>)}
            </select>
          </label>

          {loading && card === undefined ? <LoadingSkeleton rows={6} /> : selectedModel && (
            <>
              <section className="model-overview">
                <article className="surface model-identity">
                  <BrainCircuit size={22} />
                  <div><p className="eyebrow">Aday model</p><h2>{selectedModel.assetClass === 'crypto' ? 'Kripto' : 'ABD Hisse'} · {selectedModel.horizonDays}</h2><span title={selectedModel.version}>{selectedModel.version}</span></div>
                  <StatusBadge tone="warning">Değerlendirme devam ediyor</StatusBadge>
                </article>
                <article className="surface"><CalendarDays size={18} /><span>Eğitim tarihi</span><strong>{formatUtc(card?.trainedAt ?? null)}</strong></article>
                <article className="surface"><FlaskConical size={18} /><span>Shadow tahmin</span><strong>{selectedModel.predictionCount}</strong></article>
                <article className="surface"><ShieldQuestion size={18} /><span>Promotion</span><strong>{selectedModel.maturedPredictionCount === 0 ? 'Kanıt yetersiz' : beatsBaseline ? 'Kapılar inceleniyor' : 'Baseline geçilemedi'}</strong></article>
              </section>

              <section className="model-performance-grid">
                <article className="surface performance-chart-panel">
                  <header className="section-heading"><div><p className="eyebrow">Düşük değer daha iyi</p><h2>Brier karşılaştırması</h2></div></header>
                  {brier === null || baselineBrier === null ? <EmptyState title="Canlı Brier sonucu bekleniyor" description="Olgunlaşmış etiket oluşmadan Shadow Brier skoru hesaplanamaz." /> : (
                    <>
                      <ModelComparisonChart brier={brier} baseline={baselineBrier} />
                      <div className={`baseline-note ${beatsBaseline ? 'positive' : ''}`}>{beatsBaseline ? 'Model mevcut ölçümde baseline değerinden daha düşük Brier üretiyor.' : 'Model henüz baseline performansını geçemedi.'}</div>
                    </>
                  )}
                </article>
                <article className="surface metric-ledger">
                  <header className="section-heading"><div><p className="eyebrow">Kalibrasyon defteri</p><h2>Değerlendirme metrikleri</h2></div></header>
                  <dl>
                    <div><dt>Brier skoru</dt><dd>{brier === null ? 'Bekleniyor' : brier.toFixed(4)}</dd></div>
                    <div><dt>Baseline Brier</dt><dd>{baselineBrier === null ? 'Bekleniyor' : baselineBrier.toFixed(4)}</dd></div>
                    <div><dt>ECE</dt><dd>{ece === null ? 'Bekleniyor' : ece.toFixed(4)}</dd></div>
                    <div><dt>Risk hatası</dt><dd>{riskError === null ? 'Bekleniyor' : riskError.toFixed(4)}</dd></div>
                    <div><dt>Kapsama oranı</dt><dd>{coverage === null ? 'Bekleniyor' : formatPercent(coverage)}</dd></div>
                    <div><dt>Tamamlanan / bekleyen</dt><dd>{selectedModel.maturedPredictionCount} / {selectedModel.predictionCount - selectedModel.maturedPredictionCount}</dd></div>
                  </dl>
                </article>
              </section>

              <section className="surface model-governance">
                <header className="section-heading"><div><p className="eyebrow">Promotion kapıları</p><h2>Production otomatik değildir</h2></div></header>
                <div className="gate-grid">
                  <div className={selectedModel.predictionCount > 0 ? 'passed' : ''}><span>01</span><strong>Canlı tahmin kaydı</strong><p>{selectedModel.predictionCount > 0 ? 'Başladı' : 'Bekleniyor'}</p></div>
                  <div className={selectedModel.maturedPredictionCount > 0 ? 'passed' : ''}><span>02</span><strong>Olgun etiket</strong><p>{selectedModel.maturedPredictionCount > 0 ? 'Başladı' : 'Kanıt yetersiz'}</p></div>
                  <div className={beatsBaseline ? 'passed' : ''}><span>03</span><strong>Baseline üstünlüğü</strong><p>{brier === null ? 'Ölçüm bekleniyor' : beatsBaseline ? 'Geçti' : 'Geçilemedi'}</p></div>
                  <div><span>04</span><strong>Kalibrasyon ve risk</strong><p>Değerlendirme bekliyor</p></div>
                  <div><span>05</span><strong>Production onayı</strong><p>Kilitli</p></div>
                </div>
              </section>
            </>
          )}
        </>
      )}
    </div>
  )
}
