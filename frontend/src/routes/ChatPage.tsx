import { useState, type FormEvent } from 'react'
import { api, getErrorMessage } from '@/lib/api'
import type { QAResponse } from '@/types'

interface ChatEntry {
  question: string
  answer: string
  table: Record<string, unknown>[] | null
}

// POST /qa is routed through the supervisor, which can dispatch to the qa,
// forecast, or categorize agent depending on how the question is
// classified - each returns a differently-shaped "result", so pull out
// something readable regardless of which one actually handled it.
function extractAnswer(data: QAResponse): string {
  const result = data.result
  if (typeof result.answer === 'string') return result.answer
  if (typeof result.summary === 'string') return result.summary
  if (typeof result.message === 'string') return result.message
  if (typeof result.error === 'string') return result.error
  if (typeof result.category === 'string') {
    const flagged = result.is_anomaly ? ' (flagged as unusual spending)' : ''
    return `Categorized as "${result.category}"${flagged}.`
  }
  return "Done, but I'm not sure how to summarize that."
}

export default function ChatPage() {
  const [question, setQuestion] = useState('')
  const [history, setHistory] = useState<ChatEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!question.trim()) return

    setError(null)
    setLoading(true)
    const askedQuestion = question
    setQuestion('')

    try {
      const response = await api.post<QAResponse>('/qa', { question: askedQuestion })
      setHistory((prev) => [
        ...prev,
        { question: askedQuestion, answer: extractAnswer(response.data), table: response.data.table },
      ])
    } catch (err) {
      setError(getErrorMessage(err, 'Could not get an answer right now.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-ink">Ask FinSight</h1>
        <p className="text-sm text-ink-muted mt-1">
          Ask about your spending, budgets, or anything flagged as unusual.
        </p>
      </div>

      <div className="space-y-4">
        {history.length === 0 && !loading && (
          <p className="text-sm text-ink-muted bg-surface-card border border-border rounded-lg px-5 py-6">
            Try asking "How much did I spend on food this month?" or "What are my recent
            transactions?"
          </p>
        )}

        {history.map((entry, i) => (
          <div key={i} className="space-y-2">
            <div className="flex justify-end">
              <div className="bg-primary text-white text-sm rounded-lg rounded-br-sm px-4 py-2.5 max-w-lg">
                {entry.question}
              </div>
            </div>
            <div className="flex justify-start">
              <div className="bg-surface-card border border-border text-sm text-ink rounded-lg rounded-bl-sm px-4 py-2.5 max-w-2xl space-y-3">
                <p>{entry.answer}</p>
                {entry.table && entry.table.length > 0 && (
                  <div className="overflow-x-auto border border-border rounded-md">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-surface text-left text-ink-muted">
                          {Object.keys(entry.table[0]).map((key) => (
                            <th key={key} className="px-3 py-2 font-medium capitalize">
                              {key.replace(/_/g, ' ')}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {entry.table.map((row, rowIndex) => (
                          <tr key={rowIndex} className="border-t border-border">
                            {Object.keys(entry.table![0]).map((key) => (
                              <td key={key} className="px-3 py-2 tabular-figures text-ink">
                                {String(row[key] ?? '')}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-surface-card border border-border text-sm text-ink-muted rounded-lg rounded-bl-sm px-4 py-2.5">
              Thinking…
            </div>
          </div>
        )}
      </div>

      {error && (
        <p className="text-sm text-danger bg-danger-soft border border-danger/20 rounded-md px-3 py-2">
          {error}
        </p>
      )}

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about your spending…"
          className="flex-1 rounded-md border border-border bg-surface-card px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="bg-primary hover:bg-primary-hover disabled:opacity-60 text-white text-sm font-medium px-4 py-2.5 rounded-md transition-colors"
        >
          Send
        </button>
      </form>
    </div>
  )
}
