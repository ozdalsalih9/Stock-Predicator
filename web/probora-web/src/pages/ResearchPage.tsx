import {
  AlertTriangle,
  BarChart3,
  CalendarCheck2,
  CheckCircle2,
  Database,
  FlaskConical,
  Gauge,
  RefreshCw,
  ServerCog,
} from 'lucide-react'
import type { CSSProperties } from 'react'

import { EmptyState, ErrorState, LoadingSkeleton } from '../components/ui/DataStates'
import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge, type StatusTone } from '../components/ui/StatusBadge'
import { useProboraData } from '../context/ProboraDataContext'
import { formatPercent, formatUtc } from '../lib/format'
import type { ResearchPipelineDashboard } from '../types'

const stateView: Record<ResearchPipelineDashboard['state'], { label: string; tone: StatusTone; title: string }> = {
  collecting: { label: 'Veri toplanıyor', tone: 'info', title: 'S&P 500 geçmiş evreni büyüyor' },
  waiting_next_batch: { label: 'Kota penceresi bekleniyor', tone: 'warning', title: 'Birinci parti tamamlandı' },
  audit_required: { label: 'Denetim gerekli', tone: 'warning', title: 'Veri indirme tamamlandı' },
  ready: { label: 'Eğitime hazır', tone: 'success', title: 'V4.3 veri kapısı açık' },
  no_data: { label: 'Veri bekleniyor', tone: 'muted', title: 'Bootstrap henüz başlamadı' },
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('tr-TR').format(value)
}

function coverageText(value: number | null) {
  return value === null ? 'Denetim bekliyor' : formatPercent(value)
}

export function ResearchPage() {
  const { operations } = useProboraData()
  const research = operations.researchDashboard
  const view = stateView[research?.state ?? 'no_data']

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="V4.3 veri laboratuvarı"
        title="Araştırma hattı"
        description="Geçmişte endekste bulunmuş hisseleri nokta-zaman doğruluğuyla topluyor, yüzde 95 kapsama kapısından geçiriyor ve ancak sonra GPU eğitimini açıyoruz."
        action={<button className="button secondary" onClick={operations.refresh} disabled={operations.loading}><RefreshCw size={15} /> Yenile</button>}
      />

      {operations.error !== '' && <ErrorState message={operations.error} onRetry={operations.refresh} />}
      {research === null ? <LoadingSkeleton rows={7} /> : research.state === 'no_data' ? (
        <section className="surface">
          <EmptyState title="Araştırma verisi bağlı değil" description="Bootstrap durum dosyası API konteynerine bağlandığında canlı ilerleme burada görünür." />
        </section>
      ) : (
        <>
          <section className="surface research-hero">
            <div>
              <StatusBadge tone={view.tone}>{view.label}</StatusBadge>
              <p className="eyebrow">Aktif çalışma · Parti {research.batchNumber}/{research.batchCount}</p>
              <h2>{view.title}</h2>
              <p>{research.nextStep}. Bu işlem eğitimden ayrıdır; günlük Shadow tahminleri aynı anda çalışmaya devam eder.</p>
            </div>
            <div className="research-ring" style={{ '--research-progress': `${research.overallProgressPercent * 3.6}deg` } as CSSProperties}>
              <span><strong>%{research.overallProgressPercent.toFixed(1)}</strong><small>tüm evren</small></span>
            </div>
          </section>

          <section className="research-metrics">
            <article className="surface"><Database size={18} /><span>İşlenen sembol</span><strong>{research.processedSymbols}<small> / {research.currentUniverseSize}</small></strong><p>Dondurulmuş çekirdek: {research.frozenUniverseSize}</p></article>
            <article className="surface"><BarChart3 size={18} /><span>İndirilen günlük bar</span><strong>{formatNumber(research.downloadedBars)}</strong><p>Her bar tek bir hissenin tek işlem günüdür.</p></article>
            <article className="surface"><Gauge size={18} /><span>Ortalama kapsama</span><strong>{coverageText(research.meanDailyCoverage)}</strong><p>Kapı: en az {formatPercent(research.requiredDailyCoverage)}</p></article>
            <article className="surface"><CalendarCheck2 size={18} /><span>Üyelik takvimi</span><strong>{research.membershipFresh ? 'Güncel' : 'Kontrol gerekli'}</strong><p>{research.membershipLastSnapshotDate ?? 'Snapshot bekleniyor'} · {research.membershipFreshnessDays ?? '—'} gün</p></article>
          </section>

          <section className="surface research-progress-panel">
            <header className="section-heading">
              <div><p className="eyebrow">Kota güvenli indirme</p><h2>Parti {research.batchNumber} ilerlemesi</h2></div>
              <strong>{research.batchProcessedSymbols}/{research.batchSize} sembol</strong>
            </header>
            <div className="research-progress-track"><i style={{ width: `${research.batchProgressPercent}%` }} /></div>
            <div className="research-progress-meta"><span>%{research.batchProgressPercent.toFixed(1)} tamamlandı</span><span>{research.successfulSymbols} başarılı · {research.failedSymbols} yeniden denenecek</span><span>Son kayıt {formatUtc(research.lastUpdatedAt)}</span></div>
          </section>

          <section className="surface research-pipeline">
            <header className="section-heading"><div><p className="eyebrow">Kontrollü sıra</p><h2>V4.3 eğitim kapıları</h2></div></header>
            <ol>
              <li className={research.processedSymbols > 0 ? 'active' : ''}><span>01</span><Database size={17} /><strong>Parti 1</strong><small>{research.batchNumber > 1 || research.batchProgressPercent >= 100 ? 'Tamamlandı' : 'Çalışıyor'}</small></li>
              <li className={research.batchNumber > 1 ? 'active' : ''}><span>02</span><ServerCog size={17} /><strong>Parti 2</strong><small>{research.batchNumber > 1 ? 'Başladı' : 'Sonraki kota'}</small></li>
              <li className={research.processedSymbols >= research.currentUniverseSize ? 'active' : ''}><span>03</span><AlertTriangle size={17} /><strong>Delist eşleme</strong><small>{research.failedSymbols} sembol</small></li>
              <li className={research.coverageReady ? 'active' : ''}><span>04</span><CheckCircle2 size={17} /><strong>%95 kapsama</strong><small>{research.coverageReady ? 'Geçti' : coverageText(research.minimumDailyCoverage)}</small></li>
              <li className={research.coverageReady ? 'active' : ''}><span>05</span><FlaskConical size={17} /><strong>V4.3 ablation</strong><small>{research.coverageReady ? 'Hazır' : 'Kilitli'}</small></li>
            </ol>
          </section>

          <section className="research-detail-grid">
            <article className="surface research-quality">
              <header className="section-heading"><div><p className="eyebrow">Kapsama denetimi</p><h2>Üç ayrı kontrol</h2></div><span>Son denetim {formatUtc(research.coverageCheckedAt)}</span></header>
              <dl>
                <div><dt>Ortalama günlük kapsama</dt><dd>{coverageText(research.meanDailyCoverage)}</dd></div>
                <div><dt>En düşük günlük kapsama</dt><dd>{coverageText(research.minimumDailyCoverage)}</dd></div>
                <div><dt>Son gün kapsaması</dt><dd>{coverageText(research.latestDailyCoverage)}</dd></div>
                <div><dt>Üyelik snapshot tarihi</dt><dd>{research.membershipLastSnapshotDate ?? 'Bekleniyor'}</dd></div>
              </dl>
            </article>
            <article className="surface research-failures">
              <header className="section-heading"><div><p className="eyebrow">Sessizce atlanmaz</p><h2>Yeniden deneme kuyruğu</h2></div><StatusBadge tone={research.failedSymbols === 0 ? 'success' : 'warning'}>{research.failedSymbols} sembol</StatusBadge></header>
              {research.recentFailures.length === 0 ? <p className="research-empty-list"><CheckCircle2 size={17} /> Açık indirme hatası yok.</p> : (
                <ul>{research.recentFailures.map((failure) => <li key={failure.symbol}><strong>{failure.symbol}</strong><span>{failure.errorType}</span><small>delist eşleme</small></li>)}</ul>
              )}
            </article>
          </section>

          <div className="inline-notice ai"><FlaskConical size={18} /><p><strong>“2,5 milyon günlük bar” 2,5 milyon gün beklemek demek değildir.</strong> Yaklaşık 758 hisse × binlerce geçmiş işlem günü satırıdır. Bu çapraz kesit, modelin farklı şirket ve piyasa rejimlerini aynı eğitimde görmesini sağlar.</p></div>
        </>
      )}
    </div>
  )
}
