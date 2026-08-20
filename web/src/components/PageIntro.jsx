import React from 'react'
import * as AppModule from '../App'

const FALLBACK_SCREENS = [
  'landing', 'description', 'intake', 'review',
  'analysis', 'params', 'results', 'edit', 'download',
]

const FALLBACK_STEP_LABELS = {
  description: 'Project Intake',
  intake: 'Intake',
  review: 'Review',
  analysis: 'Analysis',
  params: 'Parameters',
  results: 'Results',
  edit: 'Edits',
  download: 'Download',
}

function appConstants() {
  try {
    return {
      screens: AppModule.SCREENS || FALLBACK_SCREENS,
      labels: AppModule.STEP_LABELS || FALLBACK_STEP_LABELS,
    }
  } catch {
    return { screens: FALLBACK_SCREENS, labels: FALLBACK_STEP_LABELS }
  }
}

export default function PageIntro({ step, title, lead }) {
  const { screens, labels } = appConstants()
  const stepIdx = screens.indexOf(step)
  const label = labels[step]

  return (
    <div className="mb-6">
      {step && stepIdx > 0 && label && (
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-faint">
          Step {stepIdx} of {screens.length - 1} · {label}
        </p>
      )}
      <h1 className="text-2xl font-semibold text-ink">{title}</h1>
      {lead && <p className="mt-2 text-sm leading-6 text-ink-soft">{lead}</p>}
    </div>
  )
}
