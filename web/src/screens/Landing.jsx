import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import Spinner from '../components/Spinner'
import { api } from '../api'

function formatError(err) {
  return `${err.message || 'Something went wrong'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function formatDate(project) {
  const raw = project.updated_at || project.created_at
  return raw ? new Date(raw).toLocaleDateString() : 'No date available'
}

function SkeletonRows() {
  return (
    <div className="space-y-3 p-5" aria-hidden="true">
      {[0, 1, 2].map(i => <div key={i} className="h-12 rounded-lg bg-line/60 animate-pulse" />)}
    </div>
  )
}

export default function Landing() {
  const { update, goTo, user, resumeProject, resetProgress } = useApp()
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function loadProjects() {
    setLoading(true)
    setError('')
    try {
      setProjects(await api.listProjects({ limit: 25, order: 'created_desc' }))
    } catch (err) {
      setError(formatError(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadProjects()
  }, [])

  async function start() {
    setSaving(true)
    setError('')
    try {
      const project = await api.createProject({ title: 'New QI Project', description: '' })
      update({ projectId: project.id, projectTitle: project.title, projectDesc: project.description || '' })
      resetProgress()
      goTo('description')
    } catch (err) {
      setError(formatError(err))
    } finally {
      setSaving(false)
    }
  }

  async function archiveProject(projectId) {
    setSaving(true)
    setError('')
    try {
      await api.deleteProject(projectId)
      await loadProjects()
    } catch (err) {
      setError(formatError(err))
    } finally {
      setSaving(false)
    }
  }

  async function resumeExistingProject(project) {
    setSaving(true)
    setError('')
    try {
      await resumeProject(project.id)
    } catch (err) {
      setError(formatError(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="screen max-w-3xl">
      <section className="py-16 text-center" aria-labelledby="landing-heading">
        <p className="mb-2 text-sm text-ink-soft">Signed in as {user?.email}</p>
        <h1 id="landing-heading" className="mb-4 text-4xl font-semibold text-ink">QI Stat Studio</h1>
        <p className="mx-auto max-w-md text-lg leading-8 text-ink-soft">
          A guided statistical analysis tool for medical residents conducting quality improvement projects at Rutgers IM Clinic.
        </p>
      </section>

      {error && (
        <div className="mb-6 text-center">
          <p role="alert" className="alert-error mb-3 text-left">{error}</p>
          <button type="button" onClick={loadProjects} className="btn-secondary">
            Retry
          </button>
        </div>
      )}

      {loading && <p aria-live="polite" className="sr-only">Loading your projects…</p>}

      <div className="mb-8 flex flex-wrap justify-center gap-3">
        <button type="button" onClick={start} disabled={saving} className="btn-primary px-8 text-base">
          {saving && <Spinner />}
          {saving ? 'Working…' : 'Start New Project'}
        </button>
      </div>

      <section className="card p-0" aria-labelledby="project-list-heading">
        <div className="border-b border-line px-5 py-4">
          <h2 id="project-list-heading" className="text-lg font-semibold text-ink">Resume Existing Project</h2>
        </div>
        {loading ? (
          <SkeletonRows />
        ) : projects.length === 0 ? (
          <div className="px-5 py-12 text-center text-sm text-ink-soft">No active projects yet. Start a new project to begin.</div>
        ) : (
          <div className="divide-y divide-line">
            {projects.map(project => (
              <article key={project.id} className="flex flex-col gap-3 px-5 py-4 transition hover:bg-canvas sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 className="font-medium text-ink">{project.title || 'Untitled project'}</h3>
                  <p className="text-sm text-ink-faint">Status: {project.status || 'draft'} · {formatDate(project)}</p>
                </div>
                <div className="flex gap-2">
                  <button type="button" onClick={() => resumeExistingProject(project)} disabled={saving} className="btn-primary px-4 py-1.5">
                    Resume
                  </button>
                  <button type="button" onClick={() => archiveProject(project.id)} disabled={saving} className="btn-secondary px-4 py-1.5">
                    Archive
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
