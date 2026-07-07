import React, { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

function errorMessage(err) {
  return `${err.message || 'Could not save project'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function ProjectDescription() {
  const { ctx, update, next } = useApp()
  const [title, setTitle] = useState(ctx.projectTitle || '')
  const [desc, setDesc] = useState(ctx.projectDesc || ctx.answers?.q1 || '')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await api.updateProject(ctx.projectId, { title, description: desc })
      await api.saveAnswers(ctx.projectId, { q1: desc })
      update({
        projectTitle: title,
        projectDesc: desc,
        answers: { ...(ctx.answers || {}), q1: desc },
      })

      try {
        const prefill = await api.prefillIntake(ctx.projectId, desc)
        update({ aiSuggestions: prefill.answers || {} })
      } catch {
        // AI unavailable — proceed without suggestions.
      }

      next()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-xl mx-auto p-8 mt-12">
      <h1 className="text-2xl font-bold mb-6 text-blue-800">Describe Your QI Project</h1>
      {error && <p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
      {loading && <p aria-live="polite" className="mb-4 text-sm text-gray-500">Saving description and checking for intake suggestions…</p>}
      <form onSubmit={submit} className="flex flex-col gap-4">
        <label htmlFor="project-title" className="font-medium">Project Title</label>
        <input
          id="project-title"
          className="border rounded px-3 py-2"
          value={title}
          onChange={e => setTitle(e.target.value)}
          disabled={loading}
          required
        />
        <label htmlFor="project-description" className="font-medium">Project Description</label>
        <textarea
          id="project-description"
          className="border rounded px-3 py-2 h-28"
          value={desc}
          onChange={e => setDesc(e.target.value)}
          placeholder="Describe your QI initiative in 1–3 sentences..."
          disabled={loading}
          required
        />
        <button
          type="submit"
          disabled={loading}
          className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50"
        >
          {loading ? 'Analyzing…' : 'Continue'}
        </button>
      </form>
    </div>
  )
}
