import React, { useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

function errorMessage(err) {
  return `${err.message || 'Could not save edits'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function EditReview() {
  const { ctx, update, next, prev } = useApp()
  const originalTitle = ctx.projectTitle || ''
  const originalCaption = ctx.editedCaption || ''
  const originalInterpretation = ctx.aiInterpretation || ctx.results?.interpretation || ''
  const [title, setTitle] = useState(ctx.editedTitle || originalTitle)
  const [caption, setCaption] = useState(originalCaption)
  const [interp, setInterp] = useState(ctx.editedInterp || originalInterpretation)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      for (const [field, orig, edited] of [
        ['title', originalTitle, title],
        ['caption', originalCaption, caption],
        ['interpretation', originalInterpretation, interp],
      ]) {
        if (edited !== orig) await api.saveProjectEdit(ctx.projectId, field, orig, edited)
      }
      if (title !== originalTitle) await api.updateProject(ctx.projectId, { title })
      update({ projectTitle: title, editedTitle: title, editedCaption: caption, editedInterp: interp })
      next()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="screen max-w-xl">
      <PageIntro step="edit" title="Edit & Review" />
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}
      {saving && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Saving report edits…</p>}
      <form onSubmit={submit} className="card flex flex-col gap-5">
        <label className="flex flex-col gap-1" htmlFor="edit-title">
          <span className="label">Report Title</span>
          <input id="edit-title" className="input" value={title} onChange={e => setTitle(e.target.value)} disabled={saving} />
        </label>
        <label className="flex flex-col gap-1" htmlFor="edit-caption">
          <span className="label">Figure Caption</span>
          <textarea id="edit-caption" className="input min-h-28" value={caption} onChange={e => setCaption(e.target.value)} placeholder="Describe what the figure shows..." disabled={saving} />
        </label>
        <label className="flex flex-col gap-1" htmlFor="edit-interpretation">
          <span className="label">Interpretation</span>
          <span className="text-xs text-ink-faint">Pre-filled from AI. Edit to match your voice.</span>
          <textarea id="edit-interpretation" className="input min-h-32" value={interp} onChange={e => setInterp(e.target.value)} disabled={saving} />
        </label>
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
