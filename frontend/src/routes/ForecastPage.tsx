import { useEffect, useState } from 'react'
import { api, getErrorMessage } from '@/lib/api'
import type { ForecastResponse } from '@/types'

export default function ForecastPage() {
  const [data, setData] = useState<ForecastResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
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
    load()
  }, [])

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-ink">Forecast</h1>
        <p className="text-sm text-ink-muted mt-1">
          A month-end projection for each category, based on your spending pace so far.
        </p>
      </div>

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
            <p className="text-sm text-ink leading-relaxed">{data.summary}</p>
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
                      <th className="px-5 py-3 font-medium">Budget</th>
                      <th className="px-5 py-3 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.forecasts.map((entry) => (
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
                          {entry.budget_limit !== null ? `$${entry.budget_limit.toFixed(2)}` : '—'}
                        </td>
                        <td className="px-5 py-3">
                          {entry.on_track_to_overspend ? (
                            <span className="inline-flex items-center gap-1 rounded-full bg-danger-soft text-danger text-xs font-medium px-2 py-0.5 border border-danger/20">
                              Over budget
                            </span>
                          ) : (
                            <span className="text-ink-muted text-xs">On track</span>
                          )}
                        </td>
                      </tr>
                    ))}
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
