import { useEffect, useState, type FormEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import { api, getErrorMessage } from '@/lib/api'
import type { Category, ForecastEntry, ForecastResponse } from '@/types'

function comparisonLabel(entry: ForecastEntry): string {
  switch (entry.comparison_type) {
    case 'budget':
      return 'vs budget'
    case 'historical_average':
      return 'vs your average'
    default:
      return 'insufficient history'
  }
}

function statusLabel(entry: ForecastEntry): { text: string; danger: boolean } {
  if (entry.comparison_type === 'no_data') {
    return { text: 'No data yet', danger: false }
  }
  if (entry.on_track_to_overspend) {
    return entry.comparison_type === 'budget'
      ? { text: 'Over budget', danger: true }
      : { text: 'Above your average', danger: true }
  }
  return { text: 'On track', danger: false }
}

function baselineValue(entry: ForecastEntry): number | null {
  if (entry.comparison_type === 'budget') return entry.budget_limit
  if (entry.comparison_type === 'historical_average') return entry.historical_average
  return null
}

export default function ForecastPage() {
  const [data, setData] = useState<ForecastResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [categories, setCategories] = useState<Category[]>([])
  const [budgetCategoryId, setBudgetCategoryId] = useState('')
  const [budgetLimit, setBudgetLimit] = useState('')
  const [settingBudget, setSettingBudget] = useState(false)
  const [budgetError, setBudgetError] = useState<string | null>(null)

  async function loadForecast() {
    setLoading(true)
    setError(null)
    try {
      const response = await api.get<ForecastResponse>('/forecast')
      setData(response.data)
    } catch (err) {
      setError(getErrorMessage(err, 'Could not load your forecast.'))
    } finally {
      setLoading(false)
    }
  }

  async function loadCategories() {
    try {
      const response = await api.get<Category[]>('/categories')
      setCategories(response.data)
      if (response.data.length > 0) {
        setBudgetCategoryId((current) => current || String(response.data[0].id))
      }
    } catch {
      // non-fatal - the budget form just won't have options if this fails
    }
  }

  useEffect(() => {
    loadForecast()
    loadCategories()
  }, [])

  async function handleSetBudget(e: FormEvent) {
    e.preventDefault()
    if (!budgetCategoryId || !budgetLimit) return

    setBudgetError(null)
    setSettingBudget(true)

    try {
      await api.post('/budgets', {
        category_id: Number(budgetCategoryId),
        monthly_limit: Number(budgetLimit),
      })
      setBudgetLimit('')
      await loadForecast()
    } catch (err) {
      setBudgetError(getErrorMessage(err, 'Could not set that budget.'))
    } finally {
      setSettingBudget(false)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-ink">Forecast</h1>
        <p className="text-sm text-ink-muted mt-1">
          A month-end projection for each category, based on your spending pace so far.
        </p>
      </div>

      <section className="bg-surface-card border border-border rounded-lg p-5">
        <h2 className="text-sm font-semibold text-ink mb-4">Set a budget</h2>
        <form onSubmit={handleSetBudget} className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
          <div className="sm:col-span-2">
            <label htmlFor="budget-category" className="block text-xs font-medium text-ink-muted mb-1">
              Category
            </label>
            <select
              id="budget-category"
              required
              value={budgetCategoryId}
              onChange={(e) => setBudgetCategoryId(e.target.value)}
              className="w-full rounded-md border border-border px-3 py-2 text-sm capitalize focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            >
              {categories.map((cat) => (
                <option key={cat.id} value={cat.id} className="capitalize">
                  {cat.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="budget-limit" className="block text-xs font-medium text-ink-muted mb-1">
              Monthly limit
            </label>
            <input
              id="budget-limit"
              type="number"
              step="0.01"
              min="0"
              required
              value={budgetLimit}
              onChange={(e) => setBudgetLimit(e.target.value)}
              placeholder="0.00"
              className="w-full rounded-md border border-border px-3 py-2 text-sm tabular-figures focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            />
          </div>
          <div>
            <button
              type="submit"
              disabled={settingBudget || categories.length === 0}
              className="w-full bg-primary hover:bg-primary-hover disabled:opacity-60 text-white text-sm font-medium px-4 py-2 rounded-md transition-colors"
            >
              {settingBudget ? 'Saving…' : 'Set budget'}
            </button>
          </div>
        </form>
        {budgetError && (
          <p className="mt-3 text-sm text-danger bg-danger-soft border border-danger/20 rounded-md px-3 py-2">
            {budgetError}
          </p>
        )}
      </section>

      {error && (
        <p className="text-sm text-danger bg-danger-soft border border-danger/20 rounded-md px-3 py-2">
          {error}
        </p>
      )}

      {loading ? (
        <p className="text-sm text-ink-muted">Loading…</p>
      ) : data ? (
        <>
          <section className="bg-surface-card border border-border rounded-lg p-5">
            <h2 className="text-sm font-semibold text-ink mb-2">Summary</h2>
            <div
              className="text-sm text-ink leading-relaxed [&_strong]:font-semibold [&_h1]:text-sm [&_h1]:font-semibold [&_h2]:text-sm [&_h2]:font-semibold [&_h1]:mb-1 [&_h2]:mb-1 [&_p]:mb-2 [&_p:last-child]:mb-0 [&_ul]:list-disc [&_ul]:pl-5"
            >
              <ReactMarkdown>{data.summary}</ReactMarkdown>
            </div>
          </section>

          <section className="bg-surface-card border border-border rounded-lg overflow-hidden">
            <div className="px-5 py-4 border-b border-border">
              <h2 className="text-sm font-semibold text-ink">By category</h2>
            </div>

            {data.forecasts.length === 0 ? (
              <p className="px-5 py-6 text-sm text-ink-muted">No spending recorded yet this month.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs font-medium text-ink-muted border-b border-border">
                      <th className="px-5 py-3 font-medium">Category</th>
                      <th className="px-5 py-3 font-medium">Spent so far</th>
                      <th className="px-5 py-3 font-medium">Projected total</th>
                      <th className="px-5 py-3 font-medium">Baseline</th>
                      <th className="px-5 py-3 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.forecasts.map((entry) => {
                      const status = statusLabel(entry)
                      const baseline = baselineValue(entry)
                      return (
                        <tr key={entry.category} className="border-b border-border last:border-0">
                          <td className="px-5 py-3 text-ink capitalize">{entry.category}</td>
                          <td className="px-5 py-3 tabular-figures text-ink">
                            ${entry.spent_so_far.toFixed(2)}
                          </td>
                          <td
                            className={`px-5 py-3 tabular-figures font-medium ${
                              entry.on_track_to_overspend ? 'text-danger' : 'text-ink'
                            }`}
                          >
                            ${entry.projected_total.toFixed(2)}
                          </td>
                          <td className="px-5 py-3 tabular-figures text-ink-muted">
                            {baseline !== null ? `$${baseline.toFixed(2)}` : '—'}
                            <div className="text-xs italic text-ink-muted/70 mt-0.5">
                              {comparisonLabel(entry)}
                            </div>
                          </td>
                          <td className="px-5 py-3">
                            {status.danger ? (
                              <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft text-danger text-xs font-medium px-2 py-0.5 border border-danger/20">
                                {status.text}
                              </span>
                            ) : (
                              <span className="text-ink-muted text-xs">{status.text}</span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}
    </div>
  )
}
