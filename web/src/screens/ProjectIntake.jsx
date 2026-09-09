import React, { useState } from 'react'
import { useApp } from '../App'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

function errorMessage(err) {
  return `${err.message || 'Could not save project'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function formatFileSize(file) {
  if (!file) return ''
  if (file.size < 1024 * 1024) return `${Math.max(1, Math.round(file.size / 1024))} KB`
  return `${(file.size / (1024 * 1024)).toFixed(1)} MB`
}

export default function ProjectIntake() {
  const { ctx, update, next } = useApp()
  const [title, setTitle] = useState(ctx.projectTitle || '')
  const [desc, setDesc] = useState(ctx.projectDesc || '')
  const [deadline, setDeadline] = useState(ctx.deadline || '')
  const [file, setFile] = useState(null)
  const [dictionary, setDictionary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [phiViolations, setPhiViolations] = useState(null)

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    setError('')
    setPhiViolations(null)
    try {
      const result = await api.createProjectIntake({
        title,
        description: desc,
        file,
        dictionary,
        deadline: deadline || null,
      })
      update({
        projectId: result.project.id,
        projectTitle: result.project.title,
        projectDesc: result.project.description || '',
        deadline: result.project.deadline || deadline || '',
        uploadId: result.upload.id,
        colTypes: result.upload.col_types || {},
        qualityFlags: result.upload.quality_flags || [],
        rowCount: result.upload.preview_rows?.length || 0,
        profile: result.upload.dataset_profile || result.profile || {},
      })
      next()
    } catch (err) {
      if (err.fieldErrors && Object.keys(err.fieldErrors).length > 0) {
        setPhiViolations(err.fieldErrors)
      } else {
        setError(errorMessage(err))
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="screen max-w-xl">
      <PageIntro
        step="description"
        title="Tell us about your project."
        lead="In one or two sentences, what is your QA/QI project about? Then upload your dataset and its data dictionary."
      />

      <div className="alert-info mb-6">
        This prototype is not HIPAA compliant. Do not upload files containing patient names, MRNs, or other identifying information.
      </div>

      {phiViolations && (
        <div role="alert" className="alert-error mb-4">
          <p className="font-medium">
            We can't process this file because it may contain patient-identifying information. Remove all names, MRNs, and other PHI, then upload it again.
          </p>
          <ul className="mt-2 list-disc pl-5">
            {Object.entries(phiViolations).map(([col, messages]) => (
              <li key={col}>
                <span className="font-mono">{col === 'dictionary' ? 'Data Dictionary' : col}</span>: {Array.isArray(messages) ? messages.join(' ') : String(messages)}
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => {
              setFile(null)
              setDictionary(null)
              setPhiViolations(null)
            }}
            className="btn-secondary mt-3 text-xs"
          >
            Remove file and choose another
          </button>
        </div>
      )}

      {error && <p role="alert" className="alert-error mb-4">{error}</p>}
      {loading && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Saving project, scanning for PHI, and analyzing your data…</p>}

      <form onSubmit={submit} className="card flex flex-col gap-4">
        <label htmlFor="project-title" className="label">Project Title</label>
        <input
          id="project-title"
          className="input"
          value={title}
          onChange={e => setTitle(e.target.value)}
          disabled={loading}
          required
        />

        <label htmlFor="project-description" className="label">Project Description (minimum 40 characters)</label>
        <textarea
          id="project-description"
          className="input min-h-32"
          value={desc}
          onChange={e => setDesc(e.target.value)}
          placeholder="Describe your QI initiative in one or two sentences (aim, setting, what you are trying to improve)..."
          disabled={loading}
          required
        />
        {desc.length > 0 && desc.trim().length < 40 && (
          <p className="text-xs text-ink-faint">{40 - desc.trim().length} more character(s) needed</p>
        )}

        <label htmlFor="project-deadline" className="label">Target Completion / Abstract Deadline (optional)</label>
        <input
          id="project-deadline"
          type="date"
          className="input"
          value={deadline}
          onChange={e => setDeadline(e.target.value)}
          disabled={loading}
        />

        <label htmlFor="data-file" className="label">Dataset (CSV or Excel)</label>
        <input
          id="data-file"
          type="file"
          accept=".csv,.xlsx,.xls"
          aria-label="CSV or Excel dataset"
          onChange={e => setFile(e.target.files[0])}
          disabled={loading}
        />
        {file && <p className="text-sm text-ink-soft">Selected: <span className="font-medium text-ink">{file.name}</span> ({formatFileSize(file)})</p>}

        <label htmlFor="data-dictionary" className="label">Data Dictionary (PDF, Word, or text — optional)</label>
        <input
          id="data-dictionary"
          type="file"
          accept=".pdf,.docx,.txt"
          aria-label="Data dictionary file"
          onChange={e => setDictionary(e.target.files[0])}
          disabled={loading}
        />
        {dictionary && <p className="text-sm text-ink-soft">Selected: <span className="font-medium text-ink">{dictionary.name}</span> ({formatFileSize(dictionary)})</p>}
        <p className="text-sm text-ink-faint">Optional — attaching one helps the AI read your columns correctly instead of guessing from raw values.</p>

        <div className="flex flex-wrap gap-3 pt-2">
          <button
            type="submit"
            disabled={loading || !file || desc.trim().length < 40}
            className="btn-primary"
          >
            {loading && <Spinner />}
            {loading ? 'Processing…' : 'Continue'}
          </button>
        </div>
      </form>
    </div>
  )
}
