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
  source: TransactionSource
  is_anomaly: boolean
  is_over_budget: boolean
  created_at: string
  owner_id: number
  category_id: number | null
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

export interface ApiError {
  detail: string
}
