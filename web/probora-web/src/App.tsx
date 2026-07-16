import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from './components/layout/AppShell'
import { LoadingSkeleton } from './components/ui/DataStates'
import { ProboraDataProvider } from './context/ProboraDataContext'

const OverviewPage = lazy(() => import('./pages/OverviewPage').then((module) => ({ default: module.OverviewPage })))
const AssetsPage = lazy(() => import('./pages/AssetsPage').then((module) => ({ default: module.AssetsPage })))
const AssetDetailPage = lazy(() => import('./pages/AssetDetailPage').then((module) => ({ default: module.AssetDetailPage })))
const ShadowPage = lazy(() => import('./pages/ShadowPage').then((module) => ({ default: module.ShadowPage })))
const ModelsPage = lazy(() => import('./pages/ModelsPage').then((module) => ({ default: module.ModelsPage })))
const DataHealthPage = lazy(() => import('./pages/DataHealthPage').then((module) => ({ default: module.DataHealthPage })))
const SystemFlowPage = lazy(() => import('./pages/SystemFlowPage').then((module) => ({ default: module.SystemFlowPage })))
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })))

export default function App() {
  return (
    <ProboraDataProvider>
      <Suspense fallback={<div className="route-loading"><LoadingSkeleton rows={6} /></div>}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<OverviewPage />} />
            <Route path="assets" element={<AssetsPage />} />
            <Route path="assets/:symbol" element={<AssetDetailPage />} />
            <Route path="shadow" element={<ShadowPage />} />
            <Route path="models" element={<ModelsPage />} />
            <Route path="health" element={<DataHealthPage />} />
            <Route path="flow" element={<SystemFlowPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Suspense>
    </ProboraDataProvider>
  )
}
