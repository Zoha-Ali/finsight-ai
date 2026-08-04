import { useEffect, useState, type FormEvent } from 'react'
import { api, getErrorMessage } from '@/lib/api'
import type { Transaction, TransactionCreate } from '@/types'

const todayIso = () => new Date().toISOString().slice(0, 10)

export default function DashboardPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [merchant, setMerchant] = useState('')
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState(todayIso())
  const [submitting, setSubmitting] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)

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
                    <td className="px-5 py-3 tabular-figures text-ink">${tx.amount.toFixed(2)}</td>
                    <td className="px-5 py-3 text-ink-muted">{tx.date}</td>
                    <td className="px-5 py-3 text-ink-muted capitalize">{tx.source}</td>
                    <td className="px-5 py-3 text-ink-muted">
                      {tx.category_id !== null ? `#${tx.category_id}` : '—'}
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
                    <td className="px-5 py-3 text-right">
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
