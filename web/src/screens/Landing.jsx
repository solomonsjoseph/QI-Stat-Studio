import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

function formatError(err) {
  return `${err.message || 'Something went wrong'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function formatDate(project) {
  const raw = project.updated_at || project.created_at
  return raw ? new Date(raw).toLocaleDateString() : 'No date available'
}

export default function Landing() {
  const { update, goTo, user, logout, resumeProject } = useApp()
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
    <div className="max-w-3xl mx-auto min-h-screen flex flex-col justify-center gap-6 p-8">
      <div className="text-center">
        <p className="text-sm text-gray-500 mb-2">Signed in as {user?.email}</p>
        <h1 className="text-4xl font-bold text-blue-800 mb-4">QI Stat Studio</h1>
        <p className="text-gray-600 max-w-md mx-auto text-lg">
          A guided statistical analysis tool for medical residents conducting quality improvement projects at Rutgers IM Clinic.
        </p>
      </div>

      {error && <p role="alert" className="text-sm text-red-700 text-center">{error}</p>}
      {loading && <p aria-live="polite" className="text-sm text-gray-500 text-center">Loading your projects…</p>}

      <div className="flex flex-wrap justify-center gap-3">
        <button
          type="button"
          onClick={start}
          disabled={saving}
          className="px-8 py-3 bg-blue-700 text-white rounded-lg text-lg font-medium hover:bg-blue-800 disabled:opacity-50"
        >
          {saving ? 'Working…' : 'Start New Project'}
        </button>
        <button
          type="button"
          onClick={logout}
          className="px-5 py-3 border border-gray-300 rounded-lg text-gray-700 font-medium hover:bg-white"
        >
          Logout
        </button>
      </div>

      <section className="bg-white border rounded-xl p-5 shadow-sm" aria-labelledby="project-list-heading">
        <h2 id="project-list-heading" className="text-xl font-semibold text-blue-900 mb-3">Resume Existing Project</h2>
        {!loading && projects.length === 0 && (
          <p className="text-sm text-gray-500">No active projects yet. Start a new project to begin.</p>
        )}
        <div className="flex flex-col gap-3">
          {projects.map(project => (
            <article key={project.id} className="border rounded-lg p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <h3 className="font-semibold text-gray-900">{project.title || 'Untitled project'}</h3>
                <p className="text-sm text-gray-500">Status: {project.status || 'draft'} · {formatDate(project)}</p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => resumeExistingProject(project)}
                  disabled={saving}
                  className="px-4 py-2 bg-blue-700 text-white rounded text-sm font-medium hover:bg-blue-800 disabled:opacity-50"
                >
                  Resume
                </button>
                <button
                  type="button"
                  onClick={() => archiveProject(project.id)}
                  disabled={saving}
                  className="px-4 py-2 border border-gray-300 text-gray-700 rounded text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
                >
                  Archive
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}
