import React, { useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'
import { TEMPLATE_LABELS } from '../templateLabels'

function errorMessage(err) {
  return `${err.message || 'Could not save edits'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function EditReview() {
  const { ctx, update, next, prev } = useApp()
  const runs = ctx.runs || []
  const originalTitle = ctx.projectTitle || ''

  const [title, setTitle] = useState(ctx.editedTitle || originalTitle)
  const [runEdits, setRunEdits] = useState(() => {
    const init = {}
    runs.forEach(r => {
      init[r.run_id] = {
        originalCaption: r.caption || '',
        caption: ctx.runEdits?.[r.run_id]?.caption ?? (r.caption || ''),
        originalInterpretation: r.ai_interpretation || r.interpretation || '',
        interpretation: ctx.runEdits?.[r.run_id]?.interpretation ?? (r.ai_interpretation || r.interpretation || ''),
      }
    })
    return init
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function setRunField(runId, field, value) {
    setRunEdits(prev => ({ ...prev, [runId]: { ...prev[runId], [field]: value } }))
  }

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      if (title !== originalTitle) {
        await api.saveProjectEdit(ctx.projectId, 'title', originalTitle, title)
        await api.updateProject(ctx.projectId, { title })
      }

      for (const run of runs) {
        const edit = runEdits[run.run_id]
        if (!edit) continue
        if (edit.caption !== edit.originalCaption) {
          await api.saveProjectEdit(ctx.projectId, 'caption', edit.originalCaption, edit.caption, run.run_id)
        }
        // Always record interpretation review, even when the resident accepts the AI text
        // as-is: resume's current_screen derivation gates "download" on an interpretation
        // EditHistory row existing, so an unmodified acceptance must still count as reviewed.
        await api.saveProjectEdit(ctx.projectId, 'interpretation', edit.originalInterpretation, edit.interpretation, run.run_id)
      }

      update({ projectTitle: title, editedTitle: title, runEdits })
      next()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="screen max-w-2xl">
      <PageIntro step="edit" title="Edit & Review" />
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}
      {saving && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Saving report edits…</p>}

      <form onSubmit={submit} className="flex flex-col gap-5">
        <div className="card flex flex-col gap-2">
          <label className="flex flex-col gap-1" htmlFor="edit-title">
            <span className="label">Report Title</span>
            <input id="edit-title" className="input" value={title} onChange={e => setTitle(e.target.value)} disabled={saving} />
          </label>
        </div>

        {runs.map(run => {
          const edit = runEdits[run.run_id] || { caption: '', interpretation: '' }
          const label = TEMPLATE_LABELS[run.template] || run.template
          return (
            <div key={run.run_id} className="card flex flex-col gap-4">
              <h3 className="font-medium text-ink">{label}</h3>
              <label className="flex flex-col gap-1" htmlFor={`edit-caption-${run.run_id}`}>
                <span className="label">Figure Caption</span>
                <textarea
                  id={`edit-caption-${run.run_id}`}
                  className="input min-h-24"
                  value={edit.caption}
                  onChange={e => setRunField(run.run_id, 'caption', e.target.value)}
                  placeholder="Describe what the figure shows..."
                  disabled={saving}
                />
              </label>
              <label className="flex flex-col gap-1" htmlFor={`edit-interpretation-${run.run_id}`}>
                <span className="label">Interpretation</span>
                <span className="text-xs text-ink-faint">Pre-filled from AI. Edit to match your voice.</span>
                <textarea
                  id={`edit-interpretation-${run.run_id}`}
                  className="input min-h-28"
                  value={edit.interpretation}
                  onChange={e => setRunField(run.run_id, 'interpretation', e.target.value)}
                  disabled={saving}
                />
              </label>
            </div>
          )
        })}

        <div className="flex flex-wrap gap-3 pt-1">
          <BackButton onClick={prev} disabled={saving} />
          <button type="submit" disabled={saving} className="btn-primary">
            {saving && <Spinner />}
            {saving ? 'Saving…' : 'Save & Continue'}
          </button>
        </div>
      </form>
    </div>
  )
}
