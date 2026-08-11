// Shared model-name -> display-label mapping, so every page that shows
// which model handled a request (Dashboard, Forecast, Chat) renders the
// same human-readable name instead of the raw API model string.
export const MODEL_LABELS: Record<string, string> = {
  'claude-sonnet-5': 'Claude Sonnet 5',
  'claude-haiku-4-5': 'Claude Haiku 4.5',
  'llama-3.3-70b-versatile': 'Llama 3.3 70B (Groq)',
}

export function modelLabel(model: string | null | undefined): string | null {
  if (!model) return null
  return MODEL_LABELS[model] ?? model
}
