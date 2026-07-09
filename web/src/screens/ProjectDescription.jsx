import React, { useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

function errorMessage(err) {
  return `${err.message || 'Could not save project'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function ProjectDescription() {
  const { ctx, update, next, prev } = useApp()
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
    <div className="screen max-w-xl">
      <PageIntro
        step="description"
        title="Describe Your QI Project"
        lead="Imagine you're explaining it to a co-resident in the cafeteria. No jargon needed."
      />
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}
      {loading && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Saving description and checking for intake suggestions…</p>}
      <form onSubmit={submit} className="card flex flex-col gap-4">
        <label htmlFor="project-title" className="label">Project Title</label>
        <input id="project-title" className="input" value={title} onChange={e => setTitle(e.target.value)} disabled={loading} required />
        <label htmlFor="project-description" className="label">Project Description</label>
        <textarea
          id="project-description"
          className="input min-h-32"
          value={desc}
          onChange={e => setDesc(e.target.value)}
          placeholder="Describe your QI initiative in 1–3 sentences..."
          disabled={loading}
          required
        />
        <div className="flex flex-wrap gap-3 pt-2">
          <BackButton onClick={prev} disabled={loading} />
          <button type="submit" disabled={loading} className="btn-primary">
            {loading && <Spinner />}
            {loading ? 'Analyzing…' : 'Continue'}
          </button>
        </div>
      </form>
    </div>
  )
}
