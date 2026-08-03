import { useRef, useState, type FormEvent } from 'react'
import { api, getErrorMessage } from '@/lib/api'
import type { ReceiptDocType, ReceiptUploadResponse, Transaction } from '@/types'

const ACCEPTED_TYPES = 'image/png,image/jpeg,image/gif,image/webp,application/pdf'

interface EnrichedTransaction {
  transaction_id: number
  merchant: string
  amount: number | null
  date: string | null
  category: string
  is_anomaly: boolean
  reason: string | null
}

export default function ReceiptsPage() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [docType, setDocType] = useState<ReceiptDocType | null>(null)
  const [transactions, setTransactions] = useState<EnrichedTransaction[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function enrich(result: ReceiptUploadResponse): Promise<EnrichedTransaction[]> {
    // /receipts/upload only returns category + anomaly info per transaction,
    // not merchant/amount/date - pull those from /transactions so the
    // result is actually readable instead of a bare ID.
    let byId = new Map<number, Transaction>()
    try {
      const response = await api.get<Transaction[]>('/transactions')
      byId = new Map(response.data.map((t) => [t.id, t]))
    } catch {
      // non-fatal - the upload itself already succeeded, just fall back
      // to showing what we have without merchant/amount/date.
    }

    return result.transactions_created.map((c) => {
      const tx = byId.get(c.transaction_id)
      return {
        transaction_id: c.transaction_id,
        merchant: tx?.merchant ?? `Transaction #${c.transaction_id}`,
        amount: tx?.amount ?? null,
        date: tx?.date ?? null,
        category: c.category,
        is_anomaly: c.is_anomaly,
        reason: c.reason,
      }
    })
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!file) return

    setError(null)
    setDocType(null)
    setTransactions([])
    setUploading(true)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const response = await api.post<ReceiptUploadResponse>('/receipts/upload', formData)
      const enriched = await enrich(response.data)
      setDocType(response.data.type)
      setTransactions(enriched)
      setFile(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
    } catch (err) {
      setError(getErrorMessage(err, 'Could not process that file.'))
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-ink">Upload a receipt</h1>
        <p className="text-sm text-ink-muted mt-1">
          Upload an image or PDF of a receipt or bank/credit card statement - transactions are
          extracted, categorized, and checked for anomalies automatically.
        </p>
      </div>

      <section className="bg-surface-card border border-border rounded-lg p-5">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="receipt-file" className="block text-xs font-medium text-ink-muted mb-1">
              Image or PDF
            </label>
            <input
              id="receipt-file"
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_TYPES}
              required
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-ink file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-primary file:text-white hover:file:bg-primary-hover file:cursor-pointer cursor-pointer"
            />
          </div>

          <button
            type="submit"
            disabled={!file || uploading}
            className="bg-primary hover:bg-primary-hover disabled:opacity-60 text-white text-sm font-medium px-4 py-2 rounded-md transition-colors"
          >
            {uploading ? 'Processing…' : 'Upload'}
          </button>

          {uploading && (
            <p className="text-sm text-ink-muted">
              Reading the file and categorizing transactions - this can take a few seconds…
            </p>
          )}
        </form>
      </section>

      {error && (
        <p className="text-sm text-danger bg-danger-soft border border-danger/20 rounded-md px-3 py-2">
          {error}
        </p>
      )}

      {docType === 'receipt' && transactions.length > 0 && (
        <section className="bg-surface-card border border-border rounded-lg p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-ink">Receipt processed</h2>
            {transactions[0].is_anomaly && (
              <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft text-danger text-xs font-medium px-2 py-0.5">
                Anomaly
              </span>
            )}
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <dt className="text-ink-muted">Merchant</dt>
            <dd className="text-ink">{transactions[0].merchant}</dd>
            <dt className="text-ink-muted">Amount</dt>
            <dd className="tabular-figures text-ink">
              {transactions[0].amount !== null ? `$${transactions[0].amount.toFixed(2)}` : '—'}
            </dd>
            <dt className="text-ink-muted">Date</dt>
            <dd className="text-ink">{transactions[0].date ?? '—'}</dd>
            <dt className="text-ink-muted">Category</dt>
            <dd className="text-ink capitalize">{transactions[0].category}</dd>
            {transactions[0].reason && (
              <>
                <dt className="text-ink-muted">Why flagged</dt>
                <dd className="text-danger">{transactions[0].reason}</dd>
              </>
            )}
          </dl>
        </section>
      )}

      {docType === 'statement' && transactions.length > 0 && (
        <section className="bg-surface-card border border-border rounded-lg overflow-hidden">
          <div className="px-5 py-4 border-b border-border flex items-center justify-between">
            <h2 className="text-sm font-semibold text-ink">Statement processed</h2>
            <span className="text-xs text-ink-muted">
              {transactions.length} transaction{transactions.length === 1 ? '' : 's'}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium text-ink-muted border-b border-border">
                  <th className="px-5 py-3 font-medium">Merchant</th>
                  <th className="px-5 py-3 font-medium">Amount</th>
                  <th className="px-5 py-3 font-medium">Date</th>
                  <th className="px-5 py-3 font-medium">Category</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((tx) => (
                  <tr key={tx.transaction_id} className="border-b border-border last:border-0">
                    <td className="px-5 py-3 text-ink">{tx.merchant}</td>
                    <td className="px-5 py-3 tabular-figures text-ink">
                      {tx.amount !== null ? `$${tx.amount.toFixed(2)}` : '—'}
                    </td>
                    <td className="px-5 py-3 text-ink-muted">{tx.date ?? '—'}</td>
                    <td className="px-5 py-3 text-ink-muted capitalize">{tx.category}</td>
                    <td className="px-5 py-3">
                      {tx.is_anomaly ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft text-danger text-xs font-medium px-2 py-0.5">
                          Anomaly
                        </span>
                      ) : (
                        <span className="text-ink-muted text-xs">Normal</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
