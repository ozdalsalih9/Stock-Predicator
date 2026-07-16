import { BrainCircuit, CloudDownload, Database, LayoutDashboard, Newspaper, ServerCog, SlidersHorizontal } from 'lucide-react'

import { PageHeader } from '../components/ui/PageHeader'

const nodes = [
  { id: 'binance', icon: CloudDownload, title: 'Binance', copy: 'Kripto spot ve türev verilerini sağlar.', group: 'source' },
  { id: 'twelve', icon: CloudDownload, title: 'Twelve Data', copy: 'ABD hisseleri ve ETF’ler için doğrulanmış EOD fiyatlarını sağlar.', group: 'source' },
  { id: 'news', icon: Newspaper, title: 'Haber / metadata', copy: 'Haber başlıklarını Shadow araştırması için ayrı bir kanalda saklar.', group: 'source' },
  { id: 'worker', icon: ServerCog, title: 'VPS Worker', copy: 'Veri toplama ve günlük inference işlemlerini otomatik çalıştırır.', group: 'process' },
  { id: 'postgres', icon: Database, title: 'PostgreSQL', copy: 'Doğrulanmış verilerin ve Shadow tahminlerin saklandığı sistem hafızasıdır.', group: 'process' },
  { id: 'features', icon: SlidersHorizontal, title: 'Feature üretimi', copy: 'Yalnız o anda erişilebilir olan verilerle sızıntısız model girdileri üretir.', group: 'model' },
  { id: 'models', icon: BrainCircuit, title: '4 aday model', copy: 'Kripto ve ABD piyasaları için 30 ve 90 ufuklarında olasılık, getiri ve risk üretir.', group: 'model' },
  { id: 'shadow', icon: BrainCircuit, title: 'Shadow kayıt', copy: 'Modelin kullanıcı sinyaline dönüşmeden canlı veri üzerinde sınandığı aşamadır.', group: 'output' },
  { id: 'dashboard', icon: LayoutDashboard, title: 'Dashboard', copy: 'Kanıt, belirsizlik ve sistem sağlığını kullanıcıya açıklar.', group: 'output' },
] as const

export function SystemFlowPage() {
  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Açıklanabilir mimari"
        title="Sistem akışı"
        description="Verinin kaynağından kullanıcı ekranına kadar her aşama denetlenebilir, zaman damgalı ve birbirinden ayrılmıştır."
      />

      <section className="surface architecture-flow" aria-label="Probora sistem mimarisi">
        <div className="flow-column sources">
          <span className="flow-label">Veri kaynakları</span>
          {nodes.filter((node) => node.group === 'source').map((node) => <FlowNode {...node} key={node.id} />)}
        </div>
        <div className="flow-connector"><i /><i /><i /></div>
        <div className="flow-column process">
          <span className="flow-label">Toplama ve hafıza</span>
          {nodes.filter((node) => node.group === 'process').map((node) => <FlowNode {...node} key={node.id} />)}
        </div>
        <div className="flow-connector"><i /><i /></div>
        <div className="flow-column model">
          <span className="flow-label">Model hattı</span>
          {nodes.filter((node) => node.group === 'model').map((node) => <FlowNode {...node} key={node.id} />)}
        </div>
        <div className="flow-connector"><i /><i /></div>
        <div className="flow-column output">
          <span className="flow-label">Kanıt ve görünüm</span>
          {nodes.filter((node) => node.group === 'output').map((node) => <FlowNode {...node} key={node.id} />)}
        </div>
      </section>

      <section className="flow-principles">
        <article><span>01</span><h2>As-of doğruluğu</h2><p>Bir tahminde yalnız o anda erişilebilir veri kullanılır. Gelecek bilgi eğitim veya inference hattına sızamaz.</p></article>
        <article><span>02</span><h2>Shadow ayrımı</h2><p>Test çıktıları kullanıcı sinyalinden ayrı tutulur ve production gibi sunulmaz.</p></article>
        <article><span>03</span><h2>Kanıt kapıları</h2><p>Baseline, Brier, ECE, risk ve kapsam koşulları geçilmeden promotion gerçekleşmez.</p></article>
      </section>
    </div>
  )
}

function FlowNode({ icon: Icon, title, copy }: { icon: typeof BrainCircuit; title: string; copy: string }) {
  return (
    <button className="flow-node" type="button">
      <Icon size={20} />
      <span><strong>{title}</strong><small>{copy}</small></span>
    </button>
  )
}
