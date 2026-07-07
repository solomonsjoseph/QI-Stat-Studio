import React, { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

function errorMessage(err) {
  return `${err.message || 'Could not save edits'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function EditReview() {
  const { ctx, update, next } = useApp()
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
    <div className="max-w-xl mx-auto p-8 mt-8">
      <h1 className="text-2xl font-bold mb-6 text-blue-800">Edit & Review</h1>
      {error && <p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
      {saving && <p aria-live="polite" className="mb-4 text-sm text-gray-500">Saving report edits…</p>}
      <form onSubmit={submit} className="flex flex-col gap-5">
        <label className="flex flex-col gap-1" htmlFor="edit-title">
          <span className="font-medium">Report Title</span>
          <input id="edit-title" className="border rounded px-3 py-2" value={title} onChange={e => setTitle(e.target.value)} disabled={saving} />
        </label>
        <label className="flex flex-col gap-1" htmlFor="edit-caption">
          <span className="font-medium">Figure Caption</span>
          <textarea id="edit-caption" className="border rounded px-3 py-2 h-20" value={caption} onChange={e => setCaption(e.target.value)} placeholder="Describe what the figure shows..." disabled={saving} />
        </label>
        <label className="flex flex-col gap-1" htmlFor="edit-interpretation">
          <span className="font-medium">Interpretation</span>
          <span className="text-xs text-gray-500">Pre-filled from AI. Edit to match your voice.</span>
          <textarea id="edit-interpretation" className="border rounded px-3 py-2 h-32" value={interp} onChange={e => setInterp(e.target.value)} disabled={saving} />
        </label>
        <button type="submit" disabled={saving} className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50 self-start">
          {saving ? 'Saving…' : 'Save & Continue'}
        </button>
      </form>
    </div>
  )
}
