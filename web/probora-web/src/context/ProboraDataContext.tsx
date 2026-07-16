/* eslint-disable react-refresh/only-export-components */
import { createContext, type ReactNode, useContext } from 'react'

import { useMarketData } from '../hooks/useMarketData'
import { useOperationsDashboard } from '../hooks/useOperationsDashboard'

type MarketData = ReturnType<typeof useMarketData>
type OperationsData = ReturnType<typeof useOperationsDashboard>

interface ProboraDataContextValue {
  market: MarketData
  operations: OperationsData
}

const ProboraDataContext = createContext<ProboraDataContextValue | null>(null)

export function ProboraDataProvider({ children }: { children: ReactNode }) {
  const market = useMarketData('BTCUSDT', 30)
  const operations = useOperationsDashboard(true)

  return (
    <ProboraDataContext.Provider value={{ market, operations }}>
      {children}
    </ProboraDataContext.Provider>
  )
}

export function useProboraData() {
  const value = useContext(ProboraDataContext)
  if (value === null) throw new Error('useProboraData must be used inside ProboraDataProvider.')
  return value
}
