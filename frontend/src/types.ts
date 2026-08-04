// Shared types mirroring backend/app/schemas.py - keep these in sync with
// the FastAPI response models they're named after.

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export type TransactionSource = 'manual' | 'receipt'

export interface Transaction {
  id: number
  merchant: string
  amount: number
  date: string
  date_estimated: boolean
  source: TransactionSource
  is_anomaly: boolean
  is_over_budget: boolean
  created_at: string
  owner_id: number
  category_id: number | null
  category_name: string | null
}

export interface TransactionCreate {
  merchant: string
  amount: number
  date: string
  category_id?: number | null
}

export interface QAResponse {
  question: string
  agent_used: string
  result: Record<string, unknown>
  trace: Record<string, unknown>[]
  table: Record<string, unknown>[] | null
}

export type ForecastComparisonType = 'budget' | 'historical_average' | 'no_data'

export interface ForecastEntry {
  category: string
  spent_so_far: number
  projected_total: number
  budget_limit: number | null
  historical_average: number | null
  comparison_type: ForecastComparisonType
  on_track_to_overspend: boolean
}

export interface ForecastResponse {
  forecasts: ForecastEntry[]
  summary: string
}

export interface CategorizeResult {
  transaction_id: number
  category: string
  category_id: number
  is_anomaly: boolean
  reason: string | null
  date_estimated?: boolean | null
}

export type ReceiptDocType = 'receipt' | 'statement'

export interface ReceiptUploadResponse {
  filename: string | null
  type: ReceiptDocType
  transactions_created: CategorizeResult[]
}

export interface ApiError {
  detail: string
}
