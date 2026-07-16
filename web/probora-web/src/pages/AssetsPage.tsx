import { Filter, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'
import { useProboraData } from '../context/ProboraDataContext'
import { formatPrice, relativeTime } from '../lib/format'
import type { Asset, DataState } from '../types'

type MarketFilter = 'all' | 'crypto' | 'us_equity'
type StateFilter = 'all' | DataState

const stateLabel: Record<DataState, string> = { fresh: 'Güncel', stale: 'Gecikmiş', missing: 'Veri yok' }

export function AssetsPage() {
  const { market, operations } = useProboraData()
  const [marketFilter, setMarketFilter] = useState<MarketFilter>('all')
  const [stateFilter, setStateFilter] = useState<StateFilter>('all')
  const [query, setQuery] = useState('')
  const predictionModels = operations.predictionDashboard?.models ?? []

  const filtered = useMemo(() => market.assets.filter((asset) => {
    const matchesMarket = marketFilter === 'all' || asset.assetClass === marketFilter
    const matchesState = stateFilter === 'all' || asset.dataState === stateFilter
    const term = query.trim().toLocaleUpperCase('tr-TR')
    const matchesQuery = term === '' || `${asset.symbol} ${asset.displayName}`.toLocaleUpperCase('tr-TR').includes(term)
    return matchesMarket && matchesState && matchesQuery
  }), [market.assets, marketFilter, query, stateFilter])

  const shadowCountFor = (asset: Asset) => {
    const models = predictionModels.filter((model) => model.assetClass === asset.assetClass)
    return models.every((model) => model.coveragePercent === 1)
      ? models.reduce((sum, model) => sum + model.predictionDays, 0)
      : null
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Piyasa evreni"
        title="İzlenen varlıklar"
        description="Sekiz kripto ve yirmi ABD hissesi/ETF aynı veri kalitesi ve Shadow yönetişim kurallarıyla izlenir."
      />

      <section className="asset-controls" aria-label="Varlık filtreleri">
        <div className="segmented-control">
          <button className={marketFilter === 'all' ? 'active' : ''} onClick={() => setMarketFilter('all')}>Tümü</button>
          <button className={marketFilter === 'crypto' ? 'active' : ''} onClick={() => setMarketFilter('crypto')}>Kripto</button>
          <button className={marketFilter === 'us_equity' ? 'active' : ''} onClick={() => setMarketFilter('us_equity')}>ABD Hisse & ETF</button>
        </div>
        <label className="search-field"><Search size={16} /><span className="sr-only">Varlık ara</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Sembol veya varlık ara" /></label>
        <label className="select-field"><Filter size={15} /><span className="sr-only">Veri durumunu filtrele</span>
          <select value={stateFilter} onChange={(event) => setStateFilter(event.target.value as StateFilter)}>
            <option value="all">Tüm veri durumları</option>
            <option value="fresh">Güncel</option>
            <option value="stale">Gecikmiş</option>
            <option value="missing">Veri yok</option>
          </select>
        </label>
      </section>

      <section className="surface asset-list">
        <div className="asset-table-head">
          <span>Varlık</span><span>Piyasa</span><span>Son veri</span><span>30 / 90 model</span><span>Risk</span><span>Veri kalitesi</span><span>Shadow</span>
        </div>
        <div className="asset-rows">
          {filtered.map((asset) => {
            const classModels = predictionModels.filter((model) => model.assetClass === asset.assetClass)
            const shadowCount = shadowCountFor(asset)
            return (
              <Link className="asset-row" to={`/assets/${asset.symbol}`} key={asset.symbol}>
                <span className="asset-identity"><b>{asset.baseAsset.slice(0, 1)}</b><span><strong>{asset.symbol}</strong><small>{asset.displayName}</small></span></span>
                <span>{asset.assetClass === 'crypto' ? 'Kripto · Binance' : `${asset.exchange} · ABD`}</span>
                <span><strong>{formatPrice(asset.latestPrice)} {asset.quoteAsset}</strong><small>{relativeTime(asset.latestPriceAt)}</small></span>
                <span className="model-pills">
                  {[30, 90].map((horizon) => <i key={horizon}>{horizon}{asset.assetClass === 'crypto' ? 'g' : 's'} {classModels.some((model) => model.horizonDays === horizon) ? 'Shadow' : 'Bekliyor'}</i>)}
                </span>
                <span className="muted-cell">Detayda</span>
                <span><StatusBadge tone={asset.dataState === 'fresh' ? 'success' : asset.dataState === 'stale' ? 'warning' : 'danger'}>{stateLabel[asset.dataState]}</StatusBadge></span>
                <span><strong>{shadowCount === null ? 'Kısmi' : shadowCount}</strong><small>kayıt / varlık</small></span>
              </Link>
            )
          })}
        </div>
      </section>
      <p className="table-note">{filtered.length} varlık gösteriliyor. Risk değeri toplu listede tahmin edilmez; yalnız varlık detayındaki gerçek model çıktısından okunur.</p>
    </div>
  )
}
