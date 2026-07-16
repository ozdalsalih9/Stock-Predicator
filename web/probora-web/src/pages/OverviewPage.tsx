import { Activity, BrainCircuit, DatabaseZap, Layers3, ShieldCheck, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'

import { PriceChart } from '../components/charts/PriceChart'
import { ProbabilityBar } from '../components/charts/ProbabilityBar'
import { ReturnRangeChart } from '../components/charts/ReturnRangeChart'
import { RiskIndicator } from '../components/charts/RiskIndicator'
import { ModelJourney } from '../components/model/ModelJourney'
import { DisclaimerBanner } from '../components/ui/DisclaimerBanner'
import { EmptyState, ErrorState, LoadingSkeleton } from '../components/ui/DataStates'
import { InfoTooltip } from '../components/ui/InfoTooltip'
import { MetricCard } from '../components/ui/MetricCard'
import { StatusBadge } from '../components/ui/StatusBadge'
import { useProboraData } from '../context/ProboraDataContext'

export function OverviewPage() {
  const { market, operations } = useProboraData()
  const predictions = operations.predictionDashboard
  const cryptoCount = market.assets.filter((asset) => asset.assetClass === 'crypto').length
  const equityCount = market.assets.filter((asset) => asset.assetClass === 'us_equity').length
  const coverage = predictions?.models.length
    ? Math.round(predictions.models.reduce((sum, model) => sum + model.coveragePercent, 0) / predictions.models.length * 100)
    : 0

  return (
    <div className="page-stack">
      <section className="overview-hero">
        <div>
          <p className="eyebrow"><Sparkles size={14} /> Kanıta dayalı piyasa zekâsı</p>
          <h1>Piyasanın kesin cevabı yok.<br /><em>Ölçülebilir olasılıkları var.</em></h1>
          <p>Probora, kripto ve ABD piyasalarını takip eder; yön, getiri aralığı, risk ve model güvenini birlikte değerlendirir.</p>
          <div className="hero-actions">
            <Link className="button primary" to="/shadow">Shadow sürecini incele</Link>
            <Link className="button ghost" to="/flow">Sistem nasıl çalışıyor?</Link>
          </div>
        </div>
        <div className="system-pulse" aria-label="Sistem veri akışı aktif">
          <span className="pulse-orbit one"><i /></span>
          <span className="pulse-orbit two"><i /></span>
          <span className="pulse-core"><BrainCircuit size={27} /><strong>System Pulse</strong><small>28 veri hattı izleniyor</small></span>
          <b className="pulse-link a" /><b className="pulse-link b" /><b className="pulse-link c" />
        </div>
      </section>

      {market.notice !== '' && <div className="inline-notice warning"><DatabaseZap size={18} /><p>{market.notice}</p></div>}

      <section className="metric-grid" aria-label="Önemli sistem metrikleri">
        <MetricCard icon={Layers3} label="İzlenen Varlık" value={market.assets.length} detail={`${cryptoCount} kripto · ${equityCount} ABD`} />
        <MetricCard icon={BrainCircuit} label="Aday Model" value={predictions?.candidateCount ?? 0} detail="30 ve 90 ufuk" accent="violet" />
        <MetricCard icon={Activity} label="Shadow Tahmini" value={predictions?.totalPredictions ?? 0} detail="Canlı değerlendirme" accent="blue" />
        <MetricCard icon={ShieldCheck} label="İlk Tur Kapsama" value={coverage} suffix="%" detail="Varlık-model kapsamı" accent="amber" />
      </section>

      <section className="surface promotion-panel">
        <header className="section-heading">
          <div><p className="eyebrow">Production readiness</p><h2>Modeller şu anda sınavda</h2></div>
          <StatusBadge tone="ai">Shadow mode</StatusBadge>
        </header>
        <p>Sistem çalışıyor ve tahmin üretiyor. Modeller yeterli canlı kanıt toplamadan yatırım sinyali yayınlanmıyor.</p>
        <ModelJourney />
      </section>

      <section className="dashboard-grid">
        <article className="surface market-monitor">
          <header className="section-heading">
            <div><p className="eyebrow">Piyasa izleme</p><h2>BTC / USDT</h2></div>
            <StatusBadge tone={market.connectionState === 'connected' ? 'success' : 'danger'}>{market.connectionState === 'connected' ? 'Canlı veri' : 'Veri bekleniyor'}</StatusBadge>
          </header>
          {market.loading ? <LoadingSkeleton rows={4} /> : market.bars.length > 1 ? <PriceChart bars={market.bars} /> : <EmptyState title="Fiyat verisi bekleniyor" description="Grafik sahte veri kullanmaz; Binance verisi geldiğinde otomatik oluşur." />}
        </article>

        <article className="surface probability-panel">
          <header className="section-heading">
            <div><p className="eyebrow">30 günlük görünüm</p><h2>{market.analysis === null ? 'Sonuç bekleniyor' : market.analysis.status === 'signal' ? 'Ölçülmüş sinyal' : 'Belirgin sinyal yok'} <InfoTooltip /></h2></div>
            {market.analysis?.isShadow && <StatusBadge tone="ai">Shadow</StatusBadge>}
          </header>
          {market.analysis === null ? (
            market.analysisState === 'loading' ? <LoadingSkeleton rows={4} /> : <EmptyState title="Yeterli model sonucu yok" description="Güven kapısını geçen sonuç bulunmadığı için yön yayınlanmıyor." />
          ) : (
            <>
              <ProbabilityBar {...market.analysis.direction} />
              <div className="mini-analysis-grid">
                <div><h3>Getiri aralığı</h3><ReturnRangeChart {...market.analysis.expectedReturn} /></div>
                <div><h3>Risk</h3><RiskIndicator score={market.analysis.riskScore} /></div>
              </div>
            </>
          )}
        </article>
      </section>

      <section className="lower-grid">
        <article className="surface asset-distribution">
          <header className="section-heading"><div><p className="eyebrow">Evren dağılımı</p><h2>28 varlık, iki piyasa</h2></div></header>
          <div className="distribution-row"><span>ABD hisse ve ETF</span><i><b style={{ width: `${market.assets.length ? equityCount / market.assets.length * 100 : 0}%` }} /></i><strong>{equityCount}</strong></div>
          <div className="distribution-row"><span>Kripto</span><i><b style={{ width: `${market.assets.length ? cryptoCount / market.assets.length * 100 : 0}%` }} /></i><strong>{cryptoCount}</strong></div>
          <p>Alan karşılaştırması varlık sayısını doğrudan gösterir; pasta grafik kullanılmaz.</p>
        </article>
        <article className="surface evidence-summary">
          <header className="section-heading"><div><p className="eyebrow">Kanıt durumu</p><h2>İlk sonuçlar birikiyor</h2></div></header>
          {operations.error !== '' ? <ErrorState message={operations.error} onRetry={operations.refresh} /> : (
            <dl>
              <div><dt>Olgunlaşan etiket</dt><dd>{predictions?.totalMaturedPredictions ?? 0}</dd></div>
              <div><dt>Açık veri olayı</dt><dd>{(operations.dashboard?.unresolvedQualityIssues ?? 0) + (operations.equityDashboard?.unresolvedQualityIssues ?? 0)}</dd></div>
              <div><dt>Promotion</dt><dd>Değerlendirme devam ediyor</dd></div>
            </dl>
          )}
        </article>
      </section>

      <DisclaimerBanner />
    </div>
  )
}
