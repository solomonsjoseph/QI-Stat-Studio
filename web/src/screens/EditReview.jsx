import React, { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

export default function EditReview() {
  const { ctx, update, next } = useApp()
  const [title, setTitle] = useState(ctx.projectTitle || '')
  const [caption, setCaption] = useState('')
  const [interp, setInterp] = useState(ctx.aiInterpretation || '')
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    // Save all three edits
    for (const [field, orig, edited] of [
      ['title', ctx.projectTitle || '', title],
      ['caption', '', caption],
      ['interpretation', ctx.aiInterpretation || '', interp],
    ]) {
      if (edited !== orig) {
        await fetch(`/api/projects/${ctx.projectId}/edits`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ field, original_text: orig, edited_text: edited }),
        })
      }
    }
    update({ editedTitle: title, editedCaption: caption, editedInterp: interp })
    setSaving(false)
    next()
  }

  return (
    <div className="max-w-xl mx-auto p-8 mt-8">
      <h2 className="text-2xl font-bold mb-6 text-blue-800">Edit & Review</h2>
      <form onSubmit={submit} className="flex flex-col gap-5">
        <label className="flex flex-col gap-1">
          <span className="font-medium">Report Title</span>
          <input
            className="border rounded px-3 py-2"
            value={title}
            onChange={e => setTitle(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium">Figure Caption</span>
          <textarea
            className="border rounded px-3 py-2 h-20"
            value={caption}
            onChange={e => setCaption(e.target.value)}
            placeholder="Describe what the figure shows..."
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium">Interpretation</span>
          <p className="text-xs text-gray-500">Pre-filled from AI. Edit to match your voice.</p>
          <textarea
            className="border rounded px-3 py-2 h-32"
            value={interp}
            onChange={e => setInterp(e.target.value)}
          />
        </label>
        <button
          type="submit"
          disabled={saving}
          className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50 self-start"
        >
          {saving ? 'Saving…' : 'Save & Continue'}
        </button>
      </form>
    </div>
  )
}
