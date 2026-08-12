import { useState, type FormEvent } from 'react'
import { api, getErrorMessage } from '@/lib/api'
import { modelLabel } from '@/lib/modelLabels'
import type { CompareModelsResponse, ModelCompareResult, QAResponse } from '@/types'

interface ChatEntry {
  question: string
  answer: string | null
  table: Record<string, unknown>[] | null
  compare: CompareModelsResponse | null
  modelUsed: string | null
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

function ModelAnswerCard({ result }: { result: ModelCompareResult }) {
  return (
    <div className="bg-surface-card border border-border rounded-lg px-4 py-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-primary">{modelLabel(result.model)}</span>
        <span className="text-xs text-ink-muted tabular-figures">{result.elapsed_seconds.toFixed(2)}s</span>
      </div>
      {result.recovery_path === 'sonnet_fallback' && (
        <p className="text-xs font-medium text-danger">⚠️ Llama failed, showing Sonnet instead</p>
      )}
      <p className="text-sm text-ink">{result.answer}</p>
      {result.table && result.table.length > 0 && (
        <div className="overflow-x-auto border border-border rounded-md">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-surface text-left text-ink-muted">
                {Object.keys(result.table[0]).map((key) => (
                  <th key={key} className="px-3 py-2 font-medium capitalize">
                    {key.replace(/_/g, ' ')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.table.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-t border-border">
                  {Object.keys(result.table![0]).map((key) => (
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
      {result.tools_used.length > 0 && (
        <p className="text-xs italic text-ink-muted/70">tools used: {result.tools_used.join(', ')}</p>
      )}
    </div>
  )
}

export default function ChatPage() {
  const [question, setQuestion] = useState('')
  const [history, setHistory] = useState<ChatEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [compareMode, setCompareMode] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!question.trim()) return

    setError(null)
    setLoading(true)
    const askedQuestion = question
    setQuestion('')

    try {
      if (compareMode) {
        const response = await api.post<CompareModelsResponse>('/qa/compare', { question: askedQuestion })
        setHistory((prev) => [
          ...prev,
          { question: askedQuestion, answer: null, table: null, compare: response.data, modelUsed: null },
        ])
      } else {
        const response = await api.post<QAResponse>('/qa', { question: askedQuestion })
        const modelUsed = typeof response.data.result.model_used === 'string' ? response.data.result.model_used : null
        setHistory((prev) => [
          ...prev,
          {
            question: askedQuestion,
            answer: extractAnswer(response.data),
            table: response.data.table,
            compare: null,
            modelUsed,
          },
        ])
      }
    } catch (err) {
      setError(getErrorMessage(err, 'Could not get an answer right now.'))
    } finally {
      setLoading(false)
    }
  }

  const inputArea = (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-sm text-ink-muted cursor-pointer w-fit">
        <input
          type="checkbox"
          checked={compareMode}
          onChange={(e) => setCompareMode(e.target.checked)}
          disabled={loading}
          className="rounded border-border text-primary focus:ring-primary/30"
        />
        Compare models (Claude Sonnet 5 vs Llama 3.3 70B on Groq)
      </label>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about your spending…"
          disabled={loading}
          className="flex-1 rounded-md border border-border bg-surface-card px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="bg-primary hover:bg-primary-hover disabled:opacity-60 text-white text-sm font-medium px-4 py-2.5 rounded-md transition-colors"
        >
          Send
        </button>
      </form>
      {loading && (
        <p className="text-sm text-ink-muted">{compareMode ? 'Asking both models…' : 'Thinking…'}</p>
      )}
    </div>
  )

  // Before any messages exist, the input sits in its normal place in the
  // page flow. Once there's history, it switches to a bar FIXED to the
  // bottom of the viewport - like a normal chat interface, so new
  // messages append above a fixed input instead of the input drifting
  // below an ever-growing conversation. This has to be position:fixed,
  // not sticky - sticky only pins once its container has scrollable
  // overflow, so with just one short message (page shorter than the
  // viewport) a sticky bar just sits in normal flow wherever it falls,
  // nowhere near the bottom. pb-40 on the page reserves room for the
  // fixed bar's own height so the last message isn't hidden behind it.
  const hasHistory = history.length > 0

  return (
    <div className={hasHistory ? 'space-y-6 pb-40' : 'space-y-6'}>
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
            {entry.compare ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <ModelAnswerCard result={entry.compare.sonnet} />
                <ModelAnswerCard result={entry.compare.groq} />
              </div>
            ) : (
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
                  {entry.modelUsed && (
                    <p className="text-xs text-ink-muted/70">via {modelLabel(entry.modelUsed)}</p>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {error && (
        <p className="text-sm text-danger bg-danger-soft border border-danger/20 rounded-md px-3 py-2">
          {error}
        </p>
      )}

      {hasHistory ? (
        <div className="fixed inset-x-0 bottom-0 bg-surface border-t border-border">
          <div className="max-w-5xl mx-auto px-6 py-3">{inputArea}</div>
        </div>
      ) : (
        inputArea
      )}
    </div>
  )
}
