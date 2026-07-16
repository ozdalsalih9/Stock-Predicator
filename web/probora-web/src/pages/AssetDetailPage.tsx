import { ArrowLeft, Clock3, DatabaseZap, ShieldCheck } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { PriceChart } from '../components/charts/PriceChart'
import { AnalysisPanel } from '../components/model/AnalysisPanel'
import { DisclaimerBanner } from '../components/ui/DisclaimerBanner'
import { ErrorState, LoadingSkeleton } from '../components/ui/DataStates'
import { StatusBadge } from '../components/ui/StatusBadge'
import { useProboraData } from '../context/ProboraDataContext'
import { useAssetDetail } from '../hooks/useAssetDetail'
import { formatPrice, formatUtc, relativeTime } from '../lib/format'

export function AssetDetailPage() {
  const { symbol = '' } = useParams()
  const { market, operations } = useProboraData()
  const asset = market.assets.find((item) => item.symbol === symbol.toUpperCase())
  const detail = useAssetDetail(asset)
  const models = operations.predictionDashboard?.models.filter((model) => model.assetClass === asset?.assetClass) ?? []

  if (asset === undefined) {
    return <ErrorState message="İstenen varlık Probora izleme evreninde bulunamadı." />
  }

  return (
    <div className="page-stack">
      <Link className="back-link" to="/assets"><ArrowLeft size={15} /> Varlıklara dön</Link>
      <header className="asset-detail-header">
        <div className="asset-title">
          <span>{asset.baseAsset.slice(0, 1)}</span>
          <div><p className="eyebrow">{asset.assetClass === 'crypto' ? 'Kripto · Binance' : `${asset.exchange} · ABD`}</p><h1>{asset.displayName} <small>{asset.symbol}</small></h1></div>
        </div>
        <div className="asset-detail-price"><strong>{formatPrice(asset.latestPrice)} {asset.quoteAsset}</strong><span>Son veri {relativeTime(asset.latestPriceAt)}</span></div>
      </header>

      <section className="asset-status-strip">
        <div><DatabaseZap size={15} /><span>Veri sağlığı</span><StatusBadge tone={asset.dataState === 'fresh' ? 'success' : asset.dataState === 'stale' ? 'warning' : 'danger'}>{asset.dataState === 'fresh' ? 'Güncel' : asset.dataState === 'stale' ? 'Gecikmiş' : 'Veri yok'}</StatusBadge></div>
        <div><ShieldCheck size={15} /><span>Shadow durumu</span><strong>{models.length} aday ufuk aktif</strong></div>
        <div><Clock3 size={15} /><span>Son güncelleme</span><strong>{formatUtc(asset.latestPriceAt)}</strong></div>
      </section>

      {detail.error !== '' && <ErrorState message={detail.error} />}

      <section className="surface detail-chart">
        <header className="section-heading"><div><p className="eyebrow">Doğrulanmış fiyat serisi</p><h2>Geçmiş fiyat hareketi</h2></div><StatusBadge tone="info">{asset.assetClass === 'crypto' ? '1 saatlik' : 'Günlük EOD'}</StatusBadge></header>
        {detail.loading ? <LoadingSkeleton rows={5} /> : <PriceChart bars={detail.bars} interval={asset.assetClass === 'crypto' ? '1h' : '1d'} />}
      </section>

      <div className="detail-analysis-grid">
        <AnalysisPanel analysis={detail.analyses[30]} horizon={30} horizonUnit={asset.assetClass === 'crypto' ? 'gün' : 'seans'} />
        <AnalysisPanel analysis={detail.analyses[90]} horizon={90} horizonUnit={asset.assetClass === 'crypto' ? 'gün' : 'seans'} />
      </div>

      <section className="surface evidence-panel">
        <header className="section-heading"><div><p className="eyebrow">Açıklanabilirlik</p><h2>Model kanıtları ve sınırlamalar</h2></div></header>
        {detail.analyses[30] === null ? <p className="empty-copy">Model sonucu oluştuğunda etkili özellikler ve sınırlamalar burada gösterilir.</p> : (
          <div className="evidence-columns">
            <div><h3>Yukarı yönü destekleyenler</h3><ul>{detail.analyses[30].positiveFactors.map((factor) => <li key={factor}>{factor}</li>)}</ul></div>
            <div><h3>Aşağı yönü destekleyenler</h3><ul>{detail.analyses[30].negativeFactors.map((factor) => <li key={factor}>{factor}</li>)}</ul></div>
            <div><h3>Bilinen sınırlamalar</h3><ul>{detail.analyses[30].limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></div>
          </div>
        )}
      </section>

      {detail.news.length > 0 && (
        <section className="surface news-section">
          <header className="section-heading"><div><p className="eyebrow">Metadata only</p><h2>Haber zaman çizelgesi</h2></div><StatusBadge tone="warning">Model girdisi değil</StatusBadge></header>
          <div className="news-grid">{detail.news.slice(0, 6).map((article) => <a href={article.sourceUrl} target="_blank" rel="noreferrer" key={article.id}><small>{article.sourceName} · {relativeTime(article.publishedAt)}</small><strong>{article.title}</strong></a>)}</div>
        </section>
      )}

      <DisclaimerBanner />
    </div>
  )
}
