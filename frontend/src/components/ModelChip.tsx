import { modelLabel } from '@/lib/modelLabels'

// Claude is FinSight's own default model family, styled with the app's
// primary navy (matching e.g. the chat "Send" button); everything else
// (Groq/Llama/GPT-OSS derivatives) gets the accent teal instead, so the
// two families read as visually distinct without introducing any new
// colors outside the app's existing palette.
function familyClasses(model: string): string {
  return model.startsWith('claude-') ? 'bg-primary-soft text-primary' : 'bg-accent-soft text-accent'
}

/** Small pill showing which model handled something, matching the visual
 * language of the existing Anomaly/Normal status badges (rounded-full,
 * soft background, small padding) rather than plain "via <name>" text.
 *
 * `fallback` is opt-in and only meant for places rendering real persisted
 * per-row data (the transactions table): transactions created before
 * categorized_by_model existed have a genuine null there forever, not a
 * bug, so showing a plain "-" (same convention DashboardPage already uses
 * for a missing amount/date) reads as "no data" instead of leaving a gap
 * that makes the row shorter than its neighbors. Sites where the model is
 * always populated when rendered at all (receipt/statement panels, the
 * Compare Models cards) skip it and keep rendering nothing.
 */
export function ModelChip({
  model,
  fallback,
}: {
  model: string | null | undefined
  fallback?: string
}) {
  const label = modelLabel(model)
  if (!label || !model) {
    if (fallback === undefined) return null
    return <span className="text-xs text-ink-muted/70">{fallback}</span>
  }

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full text-xs font-medium px-2 py-0.5 ${familyClasses(model)}`}
    >
      {label}
    </span>
  )
}
