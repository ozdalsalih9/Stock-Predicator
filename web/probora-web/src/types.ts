export type DataState = 'fresh' | 'stale' | 'missing'
export type AnalysisStatus = 'signal' | 'insufficient_confidence' | 'stale_data'

export interface Asset {
  symbol: string
  baseAsset: string
  quoteAsset: string
  displayName: string
  assetClass: 'crypto' | 'us_equity'
  exchange: string
  dataStartsAt: string
  latestPrice: number | null
  latestPriceAt: string | null
  dataState: DataState
}

export interface PriceBar {
  openTime: string
  closeTime: string
  interval: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  tradeCount: number
  isFinal: boolean
}

export interface Analysis {
  symbol: string
  analysisTime: string
  horizonDays: 30 | 90
  direction: { up: number; neutral: number; down: number }
  expectedReturn: { p10: number; p50: number; p90: number }
  riskScore: number
  riskLevel: string
  confidenceScore: number
  confidenceLevel: string
  status: AnalysisStatus
  isShadow: boolean
  directionEligible: boolean
  scenarioEligible: boolean
  positiveFactors: string[]
  negativeFactors: string[]
  dataFreshness: {
    priceDataAt: string | null
    featureDataAt: string | null
    newsDataAt: string | null
    state: DataState
  }
  modelVersion: string
  featureSetVersion: string
  datasetVersion: string
  limitations: string[]
}

export interface FreshnessItem {
  dataset: string
  symbol: string | null
  latestDataAt: string | null
  lastSuccessfulIngestionAt: string | null
  state: DataState
}

export interface SystemFreshness {
  checkedAt: string
  items: FreshnessItem[]
}

export interface MarketPriceUpdate {
  symbol: string
  price: number
  priceTime: string
  change24HoursPercent: number | null
}

export interface ShadowCollectorRun {
  startedAt: string
  completedAt: string | null
  status: string
  recordsRead: number
  recordsWritten: number
  durationSeconds: number | null
  error: string | null
}

export interface ShadowCollectorAsset {
  symbol: string
  latestSnapshotAt: string | null
  latestAvailableAt: string | null
  consecutiveDays: number
  requiredHistoryDays: number
  readinessPercent: number
  latestAvailabilityLatencyMinutes: number | null
  state: 'ready' | 'warming' | 'stale' | 'missing'
}

export interface ShadowCollectorDashboard {
  checkedAt: string
  currentCutoff: string
  state: 'healthy' | 'warming' | 'degraded' | 'no_data'
  totalAssets: number
  currentCutoffCompleteAssets: number
  modelReadyAssets: number
  requiredHistoryDays: number
  unresolvedQualityIssues: number
  sevenDayRuns: number
  sevenDayRunSuccessRate: number | null
  sevenDayOnTimeRate: number | null
  averageAvailabilityLatencyMinutes: number | null
  p95AvailabilityLatencyMinutes: number | null
  assets: ShadowCollectorAsset[]
  recentRuns: ShadowCollectorRun[]
}

export interface UsEquityShadowAsset {
  symbol: string
  displayName: string
  exchange: string
  barCount: number
  firstBarAt: string | null
  latestBarAt: string | null
  lastIngestedAt: string | null
  requiredHistoryBars: number
  readinessPercent: number
  state: 'ready' | 'warming' | 'stale' | 'missing'
}

export interface UsEquityShadowDashboard {
  checkedAt: string
  state: 'healthy' | 'warming' | 'degraded' | 'no_data'
  provider: string
  source: string
  totalAssets: number
  readyAssets: number
  totalBars: number
  requiredHistoryBars: number
  firstBarAt: string | null
  latestSessionAt: string | null
  unresolvedQualityIssues: number
  latestRun: ShadowCollectorRun | null
  assets: UsEquityShadowAsset[]
}

export interface ShadowPredictionModel {
  version: string
  assetClass: 'crypto' | 'us_equity'
  horizonUnit: 'calendar_days' | 'trading_sessions'
  horizonDays: number
  startedAt: string | null
  lastPredictionAt: string | null
  firstEvaluationAt: string | null
  calendarDaysElapsed: number
  requiredCalendarDays: number
  remainingCalendarDays: number
  predictionDays: number
  predictionCount: number
  maturedPredictionCount: number
  coveredAssets: number
  totalAssets: number
  coveragePercent: number
  state: 'waiting' | 'collecting' | 'evaluable'
}

export interface ShadowPredictionDashboard {
  checkedAt: string
  state: 'no_candidate' | 'waiting' | 'collecting' | 'evaluable'
  candidateCount: number
  totalPredictions: number
  totalMaturedPredictions: number
  models: ShadowPredictionModel[]
}

export interface ModelCard {
  version: string
  horizonDays: number
  featureSetVersion: string
  datasetVersion: string
  trainedAt: string
  isProduction: boolean
  directionEligible: boolean
  scenarioEligible: boolean
  metrics: Record<string, number>
  knownLimitations: string[]
}

export interface NewsArticle {
  id: string
  symbol: string
  title: string
  sourceName: string
  sourceUrl: string
  publishedAt: string
  retrievedAt: string
  language: string
  relevanceScore: number
  sentimentScore: number | null
  eventType: string
  noveltyScore: number
  shadowOnly: boolean
}
