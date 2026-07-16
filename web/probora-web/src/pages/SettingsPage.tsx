import { Bell, Clock3, Database, ShieldCheck } from 'lucide-react'

import { PageHeader } from '../components/ui/PageHeader'
import { StatusBadge } from '../components/ui/StatusBadge'

export function SettingsPage() {
  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Araştırma tercihleri"
        title="Ayarlar"
        description="Probora’nın zaman, bildirim ve veri sunum tercihleri. İşlem emri veya otomatik al-sat özelliği bulunmaz."
      />
      <section className="settings-grid">
        <article className="surface setting-card">
          <Clock3 size={20} />
          <div><h2>Zaman standardı</h2><p>Tüm model cutoff, veri zamanı ve denetim kayıtları UTC olarak gösterilir.</p></div>
          <StatusBadge tone="info">UTC</StatusBadge>
        </article>
        <article className="surface setting-card">
          <Bell size={20} />
          <div><h2>Promotion bildirimleri</h2><p>Bir model değerlendirme kapısına ulaştığında sakin ve açıklayıcı bir durum bildirimi gösterilir.</p></div>
          <StatusBadge tone="muted">Yakında</StatusBadge>
        </article>
        <article className="surface setting-card">
          <Database size={20} />
          <div><h2>Veri kaynakları</h2><p>Binance ve Twelve Data kaynakları ayrı tutulur; eksik veri başarılı gibi gösterilmez.</p></div>
          <StatusBadge tone="success">Denetlenebilir</StatusBadge>
        </article>
        <article className="surface setting-card">
          <ShieldCheck size={20} />
          <div><h2>Hareket tercihi</h2><p>Arayüz işletim sistemindeki “hareketi azalt” tercihini otomatik olarak uygular.</p></div>
          <StatusBadge tone="success">Erişilebilir</StatusBadge>
        </article>
      </section>
      <section className="surface legal-settings">
        <p className="eyebrow">Ürün sınırı</p>
        <h2>Probora ne yapmaz?</h2>
        <ul>
          <li>Kesin yükselecek veya kesin düşecek iddiasında bulunmaz.</li>
          <li>Kişisel portföy önermez, alım-satım emri üretmez.</li>
          <li>Eksik veriyi sıfır değerle doldurup tahmin yayımlamaz.</li>
          <li>Shadow modelini production modeli gibi sunmaz.</li>
        </ul>
      </section>
    </div>
  )
}
