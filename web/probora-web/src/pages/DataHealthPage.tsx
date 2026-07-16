import { CheckCircle2, Clock3, Database, DatabaseZap, RefreshCw, ServerCog, TriangleAlert } from 'lucide-react'

import { ErrorState, LoadingSkeleton } from '../components/ui/DataStates'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge, type StatusTone } from '../components/ui/StatusBadge'
import { useProboraData } from '../context/ProboraDataContext'
import { formatPercent, formatUtc } from '../lib/format'

const stateText = {
  healthy: 'Hazır',
  warming: 'Kanıt birikiyor',
  degraded: 'İnceleme gerekli',
  no_data: 'Değerlendirilmedi',
} as const

function stateTone(state: keyof typeof stateText): StatusTone {
  return state === 'healthy' ? 'success' : state === 'warming' ? 'warning' : state === 'degraded' ? 'danger' : 'muted'
}

export function DataHealthPage() {
  const { market, operations } = useProboraData()
  const crypto = operations.dashboard
  const equity = operations.equityDashboard
  const freshPrices = market.freshness?.items.filter((item) => item.dataset === 'price_bars' && item.state === 'fresh').length ?? 0

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Operasyonel güven"
        title="Veri sağlığı"
        description="Eksik veya gecikmiş veri sıfırla doldurulmaz. İlgili tahmin kapatılır ve nedeni görünür biçimde kaydedilir."
        action={<button className="button secondary" onClick={operations.refresh} disabled={operations.loading}><RefreshCw size={15} /> Yenile</button>}
      />

      {operations.error !== '' && <ErrorState message={operations.error} onRetry={operations.refresh} />}
      {crypto === null || equity === null ? <LoadingSkeleton rows={7} /> : (
        <>
          <section className="health-service-grid">
            <article className="surface health-service">
              <div><DatabaseZap size={19} /><span>Binance collector</span></div>
              <StatusBadge tone={stateTone(crypto.state)}>{stateText[crypto.state]}</StatusBadge>
              <strong>{crypto.currentCutoffCompleteAssets}/{crypto.totalAssets} bugünkü cutoff</strong>
              <p>Son çalışma: {crypto.recentRuns[0] ? formatUtc(crypto.recentRuns[0].completedAt) : 'Henüz yok'}</p>
            </article>
            <article className="surface health-service">
              <div><DatabaseZap size={19} /><span>Twelve Data collector</span></div>
              <StatusBadge tone={stateTone(equity.state)}>{stateText[equity.state]}</StatusBadge>
              <strong>{equity.readyAssets}/{equity.totalAssets} varlık hazır</strong>
              <p>Son çalışma: {formatUtc(equity.latestRun?.completedAt ?? null)}</p>
            </article>
            <article className="surface health-service">
              <div><Database size={19} /><span>PostgreSQL</span></div>
              <StatusBadge tone={market.connectionState === 'connected' ? 'success' : 'danger'}>{market.connectionState === 'connected' ? 'Bağlı' : 'Erişilemiyor'}</StatusBadge>
              <strong>{freshPrices} güncel fiyat akışı</strong>
              <p>Son sağlık kontrolü: {formatUtc(market.freshness?.checkedAt ?? null)}</p>
            </article>
            <article className="surface health-service">
              <div><ServerCog size={19} /><span>Worker</span></div>
              <StatusBadge tone={operations.error === '' ? 'success' : 'danger'}>{operations.error === '' ? 'Çalışıyor' : 'Kontrol gerekli'}</StatusBadge>
              <strong>{operations.predictionDashboard?.totalPredictions ?? 0} Shadow kayıt</strong>
              <p>Son inference: {formatUtc(operations.predictionDashboard?.models.reduce<string | null>((latest, model) => !model.lastPredictionAt ? latest : !latest || model.lastPredictionAt > latest ? model.lastPredictionAt : latest, null) ?? null)}</p>
            </article>
          </section>

          <section className="surface health-overview">
            <header className="section-heading"><div><p className="eyebrow">Readiness özeti</p><h2>Veri kapıları</h2></div></header>
            <div className="health-bars">
              <div><span>Kripto cutoff kapsamı</span><i><b style={{ width: `${crypto.totalAssets ? crypto.currentCutoffCompleteAssets / crypto.totalAssets * 100 : 0}%` }} /></i><strong>{crypto.currentCutoffCompleteAssets}/{crypto.totalAssets}</strong></div>
              <div><span>Kripto 90 günlük geçmiş</span><i><b style={{ width: `${crypto.totalAssets ? crypto.modelReadyAssets / crypto.totalAssets * 100 : 0}%` }} /></i><strong>{crypto.modelReadyAssets}/{crypto.totalAssets}</strong></div>
              <div><span>ABD EOD kapsamı</span><i><b style={{ width: `${equity.totalAssets ? equity.readyAssets / equity.totalAssets * 100 : 0}%` }} /></i><strong>{equity.readyAssets}/{equity.totalAssets}</strong></div>
              <div><span>7 gün zamanında çalışma</span><i><b style={{ width: `${(crypto.sevenDayOnTimeRate ?? 0) * 100}%` }} /></i><strong>{crypto.sevenDayOnTimeRate === null ? '—' : formatPercent(crypto.sevenDayOnTimeRate)}</strong></div>
            </div>
          </section>

          <section className="health-detail-grid">
            <article className="surface health-table-panel">
              <header className="section-heading"><div><p className="eyebrow">Kripto türev verisi</p><h2>UTC cutoff readiness</h2></div><span>{formatUtc(crypto.currentCutoff)}</span></header>
              <div className="compact-health-list">
                {crypto.assets.map((asset) => (
                  <div key={asset.symbol}>
                    <strong>{asset.symbol.replace('USDT', '')}<small>/USDT</small></strong>
                    <span>{asset.consecutiveDays}/{asset.requiredHistoryDays} gün</span>
                    <span>Snapshot {formatUtc(asset.latestSnapshotAt)}</span>
                    <StatusBadge tone={asset.state === 'ready' ? 'success' : asset.state === 'warming' || asset.state === 'stale' ? 'warning' : 'danger'}>
                      {asset.state === 'ready' ? 'Hazır' : asset.state === 'warming' ? 'Birikiyor' : asset.state === 'stale' ? 'Gecikmiş' : 'Veri yok'}
                    </StatusBadge>
                  </div>
                ))}
              </div>
            </article>
            <article className="surface health-table-panel">
              <header className="section-heading"><div><p className="eyebrow">ABD EOD verisi</p><h2>Varlık kapsamı</h2></div><span>{equity.provider}</span></header>
              <div className="compact-health-list">
                {equity.assets.map((asset) => (
                  <div key={asset.symbol}>
                    <strong>{asset.symbol}<small>{asset.exchange}</small></strong>
                    <span>{new Intl.NumberFormat('tr-TR').format(asset.barCount)} bar</span>
                    <span>Son seans {formatUtc(asset.latestBarAt)}</span>
                    <StatusBadge tone={asset.state === 'ready' ? 'success' : asset.state === 'warming' || asset.state === 'stale' ? 'warning' : 'danger'}>
                      {asset.state === 'ready' ? 'Hazır' : asset.state === 'warming' ? 'Birikiyor' : asset.state === 'stale' ? 'Gecikmiş' : 'Veri yok'}
                    </StatusBadge>
                  </div>
                ))}
              </div>
            </article>
          </section>

          <section className={`quality-summary ${crypto.unresolvedQualityIssues + equity.unresolvedQualityIssues > 0 ? 'warning' : ''}`}>
            {crypto.unresolvedQualityIssues + equity.unresolvedQualityIssues > 0 ? <TriangleAlert size={20} /> : <CheckCircle2 size={20} />}
            <div><strong>{crypto.unresolvedQualityIssues + equity.unresolvedQualityIssues} açık kalite olayı</strong><p>Eksik veri bulunan modelin tahmin kapısı otomatik kapanır. Eksik değerler sıfır olarak yorumlanmaz.</p></div>
            <Clock3 size={18} />
          </section>
        </>
      )}
    </div>
  )
}
