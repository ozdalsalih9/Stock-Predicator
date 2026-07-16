import {
  Activity,
  BarChart3,
  BrainCircuit,
  DatabaseZap,
  LayoutDashboard,
  Menu,
  Network,
  Settings,
  ShieldCheck,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { useProboraData } from '../../context/ProboraDataContext'
import { relativeTime } from '../../lib/format'
import { BrandMark } from '../ui/BrandMark'
import { StatusBadge } from '../ui/StatusBadge'

const navigation = [
  { to: '/', label: 'Genel Bakış', icon: LayoutDashboard },
  { to: '/assets', label: 'Varlıklar', icon: BarChart3 },
  { to: '/shadow', label: 'Shadow Tahminler', icon: BrainCircuit },
  { to: '/models', label: 'Model Performansı', icon: Activity },
  { to: '/health', label: 'Veri Sağlığı', icon: DatabaseZap },
  { to: '/flow', label: 'Sistem Akışı', icon: Network },
  { to: '/settings', label: 'Ayarlar', icon: Settings },
] as const

const pageNames: Record<string, string> = {
  '/': 'Genel Bakış',
  '/assets': 'Varlıklar',
  '/shadow': 'Shadow Tahminler',
  '/models': 'Model Performansı',
  '/health': 'Veri Sağlığı',
  '/flow': 'Sistem Akışı',
  '/settings': 'Ayarlar',
}

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const { market, operations } = useProboraData()
  const shadowActive = (operations.predictionDashboard?.candidateCount ?? 0) > 0
  const currentPage = location.pathname.startsWith('/assets/') ? 'Varlık Detayı' : pageNames[location.pathname] ?? 'Probora'

  return (
    <div className="product-shell">
      <a href="#content" className="skip-link">İçeriğe geç</a>
      <aside className={`sidebar ${mobileOpen ? 'open' : ''}`} aria-label="Ana navigasyon">
        <div className="sidebar-brand">
          <BrandMark />
          <div><strong>Probora</strong><span>Market intelligence</span></div>
          <button className="mobile-close" onClick={() => setMobileOpen(false)} aria-label="Menüyü kapat"><X size={18} /></button>
        </div>
        <nav>
          {navigation.map(({ to, label, icon: Icon }) => (
            <NavLink to={to} end={to === '/'} key={to} onClick={() => setMobileOpen(false)}>
              <Icon size={17} /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-status">
          <div className="sidebar-status-head"><ShieldCheck size={16} /><strong>Sistem durumu</strong></div>
          <dl>
            <div><dt>API</dt><dd><i className={market.connectionState === 'connected' ? 'ok' : 'bad'} />{market.connectionState === 'connected' ? 'Bağlı' : 'Bekleniyor'}</dd></div>
            <div><dt>Worker</dt><dd><i className={operations.error === '' ? 'ok' : 'warn'} />{operations.error === '' ? 'Çalışıyor' : 'Kontrol gerekli'}</dd></div>
            <div><dt>Shadow</dt><dd><i className={shadowActive ? 'ai' : 'warn'} />{shadowActive ? 'Aktif' : 'Bekliyor'}</dd></div>
          </dl>
          <p>Son kontrol {operations.predictionDashboard === null ? '—' : relativeTime(operations.predictionDashboard.checkedAt)}</p>
        </div>
      </aside>

      {mobileOpen && <button className="mobile-scrim" aria-label="Menüyü kapat" onClick={() => setMobileOpen(false)} />}

      <div className="workspace">
        <header className="workspace-topbar">
          <button className="mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Menüyü aç"><Menu size={20} /></button>
          <div><span>Probora Research</span><strong>{currentPage}</strong></div>
          <StatusBadge tone={market.connectionState === 'connected' ? 'success' : 'danger'}>
            {market.connectionState === 'connected' ? 'Sistem çalışıyor' : 'Servis bekleniyor'}
          </StatusBadge>
        </header>
        <main id="content" tabIndex={-1}>
          <Outlet />
        </main>
        <footer className="workspace-footer">
          <span>© 2026 Probora Research</span>
          <span>UTC verileri · Denetlenebilir model sürümleri · Yatırım tavsiyesi değildir</span>
        </footer>
      </div>
    </div>
  )
}
