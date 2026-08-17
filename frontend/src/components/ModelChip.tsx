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
 */
export function ModelChip({ model }: { model: string | null | undefined }) {
  const label = modelLabel(model)
  if (!label || !model) return null

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full text-xs font-medium px-2 py-0.5 ${familyClasses(model)}`}
    >
      {label}
    </span>
  )
}
