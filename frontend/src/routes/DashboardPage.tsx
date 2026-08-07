import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, getErrorMessage } from '@/lib/api'
import type { ReceiptDocType, ReceiptUploadResponse, Transaction, TransactionCreate } from '@/types'

const todayIso = () => new Date().toISOString().slice(0, 10)
const ACCEPTED_RECEIPT_TYPES = 'image/png,image/jpeg,image/gif,image/webp,application/pdf'

interface EnrichedTransaction {
  transaction_id: number
  merchant: string
  amount: number | null
  date: string | null
  category: string
  is_anomaly: boolean
  reason: string | null
}

export default function DashboardPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [merchant, setMerchant] = useState('')
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState(todayIso())
  const [submitting, setSubmitting] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [approvingId, setApprovingId] = useState<number | null>(null)

  const receiptFileInputRef = useRef<HTMLInputElement>(null)
  const [receiptFile, setReceiptFile] = useState<File | null>(null)
  const [receiptDocType, setReceiptDocType] = useState<ReceiptDocType | null>(null)
  const [receiptTransactions, setReceiptTransactions] = useState<EnrichedTransaction[]>([])
  const [uploadingReceipt, setUploadingReceipt] = useState(false)
  const [receiptError, setReceiptError] = useState<string | null>(null)

  async function loadTransactions() {
    setLoading(true)
    setError(null)
    try {
      const response = await api.get<Transaction[]>('/transactions')
      setTransactions(response.data)
    } catch (err) {
      setError(getErrorMessage(err, 'Could not load transactions.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTransactions()
  }, [])

  async function handleAdd(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)

    const payload: TransactionCreate = {
      merchant,
      amount: Number(amount),
      date,
    }

    try {
      await api.post('/transactions', payload)
      setMerchant('')
      setAmount('')
      setDate(todayIso())
      await loadTransactions()
    } catch (err) {
      setError(getErrorMessage(err, 'Could not add that transaction.'))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm('Delete this transaction? This cannot be undone.')) return

    setError(null)
    setDeletingId(id)

    try {
      await api.delete(`/transactions/${id}`)
      await loadTransactions()
    } catch (err) {
      setError(getErrorMessage(err, 'Could not delete that transaction.'))
    } finally {
      setDeletingId(null)
    }
  }

  async function handleApprove(id: number) {
    setError(null)
    setApprovingId(id)

    try {
      await api.patch(`/transactions/${id}/approve`)
      await loadTransactions()
    } catch (err) {
      setError(getErrorMessage(err, 'Could not approve that transaction.'))
    } finally {
      setApprovingId(null)
    }
  }

  function enrichReceiptResult(
    result: ReceiptUploadResponse,
    allTransactions: Transaction[],
  ): EnrichedTransaction[] {
    // /receipts/upload only returns category + anomaly info per transaction,
    // not merchant/amount/date - pull those from the already-fetched
    // transaction list so the result is actually readable instead of a
    // bare ID, without firing a second /transactions request for it.
    const byId = new Map(allTransactions.map((t) => [t.id, t]))

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

  async function handleUploadReceipt(e: FormEvent) {
    e.preventDefault()
    if (!receiptFile) return

    setReceiptError(null)
    setReceiptDocType(null)
    setReceiptTransactions([])
    setUploadingReceipt(true)

    const formData = new FormData()
    formData.append('file', receiptFile)

    try {
      const response = await api.post<ReceiptUploadResponse>('/receipts/upload', formData)
      // Single refetch of /transactions - reused both to enrich the
      // upload result (merchant/amount/date) and to refresh the table
      // below, instead of fetching it twice.
      setError(null)
      const refreshed = await api.get<Transaction[]>('/transactions')
      setTransactions(refreshed.data)
      setReceiptDocType(response.data.type)
      setReceiptTransactions(enrichReceiptResult(response.data, refreshed.data))
      setReceiptFile(null)
      if (receiptFileInputRef.current) receiptFileInputRef.current.value = ''
    } catch (err) {
      setReceiptError(getErrorMessage(err, 'Could not process that file.'))
    } finally {
      setUploadingReceipt(false)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-ink">Dashboard</h1>
        <p className="text-sm text-ink-muted mt-1">
          Every transaction is automatically categorized and checked for unusual spending.
        </p>
      </div>

      <section className="bg-surface-card border border-border rounded-lg p-5">
        <h2 className="text-sm font-semibold text-ink mb-4">Add a transaction</h2>
        <form onSubmit={handleAdd} className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
          <div className="sm:col-span-2">
            <label htmlFor="merchant" className="block text-xs font-medium text-ink-muted mb-1">
              Merchant
            </label>
            <input
              id="merchant"
              required
              value={merchant}
              onChange={(e) => setMerchant(e.target.value)}
              placeholder="e.g. Trader Joe's"
              className="w-full rounded-md border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            />
          </div>
          <div>
            <label htmlFor="amount" className="block text-xs font-medium text-ink-muted mb-1">
              Amount
            </label>
            <input
              id="amount"
              type="number"
              step="0.01"
              min="0"
              required
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
              className="w-full rounded-md border border-border px-3 py-2 text-sm tabular-figures focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            />
          </div>
          <div>
            <label htmlFor="date" className="block text-xs font-medium text-ink-muted mb-1">
              Date
            </label>
            <input
              id="date"
              type="date"
              required
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-full rounded-md border border-border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            />
          </div>
          <div className="sm:col-span-4">
            <button
              type="submit"
              disabled={submitting}
              className="bg-primary hover:bg-primary-hover disabled:opacity-60 text-white text-sm font-medium px-4 py-2 rounded-md transition-colors"
            >
              {submitting ? 'Adding…' : 'Add transaction'}
            </button>
          </div>
        </form>
      </section>

      <section className="bg-surface-card border border-border rounded-lg p-5">
        <h2 className="text-sm font-semibold text-ink mb-1">Upload a receipt or statement</h2>
        <p className="text-sm text-ink-muted mb-4">
          Upload an image or PDF - transactions are extracted, categorized, and checked for
          anomalies automatically.
        </p>
        <form onSubmit={handleUploadReceipt} className="space-y-4">
          <div>
            <label htmlFor="receipt-file" className="block text-xs font-medium text-ink-muted mb-1">
              Image or PDF
            </label>
            <input
              id="receipt-file"
              ref={receiptFileInputRef}
              type="file"
              accept={ACCEPTED_RECEIPT_TYPES}
              required
              onChange={(e) => setReceiptFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-ink file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-primary file:text-white hover:file:bg-primary-hover file:cursor-pointer cursor-pointer"
            />
          </div>

          <button
            type="submit"
            disabled={!receiptFile || uploadingReceipt}
            className="bg-primary hover:bg-primary-hover disabled:opacity-60 text-white text-sm font-medium px-4 py-2 rounded-md transition-colors"
          >
            {uploadingReceipt ? 'Processing…' : 'Upload'}
          </button>

          {uploadingReceipt && (
            <p className="text-sm text-ink-muted">
              Reading the file and categorizing transactions - this can take a few seconds…
            </p>
          )}
        </form>

        {receiptError && (
          <p className="mt-4 text-sm text-danger bg-danger-soft border border-danger/20 rounded-md px-3 py-2">
            {receiptError}
          </p>
        )}

        {receiptDocType === 'receipt' && receiptTransactions.length > 0 && (
          <div className="mt-4 border border-border rounded-lg p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-ink">Receipt processed</h3>
              {receiptTransactions[0].is_anomaly && (
                <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft text-danger text-xs font-medium px-2 py-0.5">
                  Anomaly
                </span>
              )}
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <dt className="text-ink-muted">Merchant</dt>
              <dd className="text-ink">{receiptTransactions[0].merchant}</dd>
              <dt className="text-ink-muted">Amount</dt>
              <dd className="tabular-figures text-ink">
                {receiptTransactions[0].amount !== null
                  ? `Rs. ${receiptTransactions[0].amount.toFixed(2)}`
                  : '—'}
              </dd>
              <dt className="text-ink-muted">Date</dt>
              <dd className="text-ink">{receiptTransactions[0].date ?? '—'}</dd>
              <dt className="text-ink-muted">Category</dt>
              <dd className="text-ink capitalize">{receiptTransactions[0].category}</dd>
              {receiptTransactions[0].reason && (
                <>
                  <dt className="text-ink-muted">Why flagged</dt>
                  <dd className="text-danger">{receiptTransactions[0].reason}</dd>
                </>
              )}
            </dl>
          </div>
        )}

        {receiptDocType === 'statement' && receiptTransactions.length > 0 && (
          <div className="mt-4 border border-border rounded-lg overflow-hidden">
            <div className="px-4 py-3 border-b border-border flex items-center justify-between">
              <h3 className="text-sm font-semibold text-ink">Statement processed</h3>
              <span className="text-xs text-ink-muted">
                {receiptTransactions.length} transaction{receiptTransactions.length === 1 ? '' : 's'}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs font-medium text-ink-muted border-b border-border">
                    <th className="px-4 py-2 font-medium">Merchant</th>
                    <th className="px-4 py-2 font-medium">Amount</th>
                    <th className="px-4 py-2 font-medium">Date</th>
                    <th className="px-4 py-2 font-medium">Category</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {receiptTransactions.map((tx) => (
                    <tr key={tx.transaction_id} className="border-b border-border last:border-0">
                      <td className="px-4 py-2 text-ink">{tx.merchant}</td>
                      <td className="px-4 py-2 tabular-figures text-ink">
                        {tx.amount !== null ? `Rs. ${tx.amount.toFixed(2)}` : '—'}
                      </td>
                      <td className="px-4 py-2 text-ink-muted">{tx.date ?? '—'}</td>
                      <td className="px-4 py-2 text-ink-muted capitalize">{tx.category}</td>
                      <td className="px-4 py-2">
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
          </div>
        )}
      </section>

      {error && (
        <p className="text-sm text-danger bg-danger-soft border border-danger/20 rounded-md px-3 py-2">
          {error}
        </p>
      )}

      <section className="bg-surface-card border border-border rounded-lg overflow-hidden">
        <div className="px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-ink">Transactions</h2>
        </div>

        {loading ? (
          <p className="px-5 py-6 text-sm text-ink-muted">Loading…</p>
        ) : transactions.length === 0 ? (
          <p className="px-5 py-6 text-sm text-ink-muted">No transactions yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium text-ink-muted border-b border-border">
                  <th className="px-5 py-3 font-medium">Merchant</th>
                  <th className="px-5 py-3 font-medium">Amount</th>
                  <th className="px-5 py-3 font-medium">Date</th>
                  <th className="px-5 py-3 font-medium">Source</th>
                  <th className="px-5 py-3 font-medium">Category</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((tx) => (
                  <tr key={tx.id} className="border-b border-border last:border-0">
                    <td className="px-5 py-3 text-ink">{tx.merchant}</td>
                    <td className="px-5 py-3 tabular-figures text-ink">Rs. {tx.amount.toFixed(2)}</td>
                    <td className="px-5 py-3 text-ink-muted">
                      {tx.date}
                      {tx.date_estimated && (
                        <span
                          className="ml-1.5 text-xs italic text-ink-muted/70"
                          title="The exact date wasn't legible on the uploaded receipt, so today's date was used instead."
                        >
                          (estimated)
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-ink-muted capitalize">{tx.source}</td>
                    <td className="px-5 py-3 text-ink-muted capitalize">
                      {tx.category_name ?? 'Uncategorized'}
                    </td>
                    <td className="px-5 py-3">
                      {tx.is_anomaly ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft text-danger text-xs font-medium px-2 py-0.5">
                          Anomaly
                        </span>
                      ) : (
                        <span className="text-ink-muted text-xs">Normal</span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-right whitespace-nowrap">
                      {tx.is_anomaly && (
                        <button
                          type="button"
                          onClick={() => handleApprove(tx.id)}
                          disabled={approvingId === tx.id}
                          className="text-xs font-medium text-primary hover:text-primary-hover disabled:opacity-60 transition-colors mr-3"
                        >
                          {approvingId === tx.id ? 'Approving…' : 'Approve'}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleDelete(tx.id)}
                        disabled={deletingId === tx.id}
                        className="text-xs font-medium text-ink-muted hover:text-danger disabled:opacity-60 transition-colors"
                      >
                        {deletingId === tx.id ? 'Deleting…' : 'Delete'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
