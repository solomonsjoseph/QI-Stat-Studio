import React, { useState } from 'react'
import { useApp } from '../App'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

const COL_TYPE_OPTIONS = ['Number', 'Category', 'Date', 'ID', 'Yes/No']

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
  const [file, setFile] = useState(null)
  const [dictionary, setDictionary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [phiViolations, setPhiViolations] = useState(null)
  const [intakeResult, setIntakeResult] = useState(null)
  const [colTypes, setColTypes] = useState({})

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    setError('')
    setPhiViolations(null)
    try {
      const result = await api.createProjectIntake({ title, description: desc, file, dictionary })
      setIntakeResult(result)
      setColTypes(result.upload.col_types || {})
      update({
        projectId: result.project.id,
        projectTitle: result.project.title,
        projectDesc: result.project.description || '',
        uploadId: result.upload.id,
      })
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

  async function confirmTypes(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await api.confirmColTypes(intakeResult.upload.id, colTypes)
      update({
        colTypes,
        qualityFlags: intakeResult.upload.quality_flags || [],
        rowCount: intakeResult.upload.preview_rows?.length,
        missingPct: {},
      })
      next()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  if (intakeResult) {
    const previewRows = intakeResult.upload.preview_rows || []
    const previewColumns = previewRows.length ? Object.keys(previewRows[0] || {}) : []
    return (
      <div className="screen">
        <PageIntro step="description" title="Confirm Column Types" lead="Review the detected column types and correct any that are wrong." />
        {error && <p role="alert" className="alert-error mb-4">{error}</p>}
        {saving && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Saving column types…</p>}
        {previewRows.length > 0 && (
          <section className="card mb-6" aria-labelledby="data-preview-heading">
            <h2 id="data-preview-heading" className="mb-3 font-medium text-ink">Data preview (first 5 rows)</h2>
            <div className="overflow-x-auto">
              <table className="table-clean">
                <thead>
                  <tr>{previewColumns.map(col => <th key={col}>{col}</th>)}</tr>
                </thead>
                <tbody>
                  {previewRows.map((row, idx) => (
                    <tr key={idx}>
                      {previewColumns.map(col => (
                        <td key={col}>{row[col] === null || row[col] === undefined || row[col] === '' ? '—' : String(row[col])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
        <form onSubmit={confirmTypes}>
          <div className="mb-6 overflow-x-auto">
            <table className="table-clean">
              <thead>
                <tr><th>Column</th><th>Type</th></tr>
              </thead>
              <tbody>
                {Object.entries(intakeResult.upload.col_types || {}).map(([col]) => (
                  <tr key={col}>
                    <td className="font-mono">{col}</td>
                    <td>
                      <label className="sr-only" htmlFor={`type-${col}`}>Type for {col}</label>
                      <select id={`type-${col}`} value={colTypes[col] || 'Category'} onChange={e => setColTypes(t => ({ ...t, [col]: e.target.value }))} disabled={saving} className="input min-w-32">
                        {COL_TYPE_OPTIONS.map(o => <option key={o}>{o}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={() => { setIntakeResult(null); setFile(null); setDictionary(null); setColTypes({}) }} disabled={saving} className="btn-secondary">
              Start over
            </button>
            <button type="submit" disabled={saving} className="btn-primary">
              {saving && <Spinner />}
              {saving ? 'Saving…' : 'Confirm Types →'}
            </button>
          </div>
        </form>
      </div>
    )
  }

  return (
    <div className="screen max-w-xl">
      <PageIntro
        step="description"
        title="Tell us about your project."
        lead="In one or two sentences, what is your QA/QI project about? Then upload your dataset and its data dictionary."
      />
      <div className="alert-warn mb-6">
        Do not upload files containing patient names, MRNs, or other direct identifiers. We scan every upload and reject anything that looks like PHI.
      </div>
      {phiViolations && (
        <div role="alert" className="alert-error mb-4">
          <p className="font-medium">We can't process this file — it may contain patient-identifying information:</p>
          <ul className="mt-2 list-disc pl-5">
            {Object.entries(phiViolations).map(([col, messages]) => (
              <li key={col}><span className="font-mono">{col}</span>: {messages.join(' ')}</li>
            ))}
          </ul>
          <p className="mt-2">Remove these and upload again.</p>
        </div>
      )}
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}
      {loading && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Saving project, scanning for PHI, and analyzing your data…</p>}
      <form onSubmit={submit} className="card flex flex-col gap-4">
        <label htmlFor="project-title" className="label">Project Title</label>
        <input id="project-title" className="input" value={title} onChange={e => setTitle(e.target.value)} disabled={loading} required />

        <label htmlFor="project-description" className="label">Project Description</label>
        <textarea
          id="project-description"
          className="input min-h-32"
          value={desc}
          onChange={e => setDesc(e.target.value)}
          placeholder="Describe your QI initiative in one or two sentences..."
          disabled={loading}
          required
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

        <label htmlFor="data-dictionary" className="label">Data Dictionary (PDF, Word, or text — required)</label>
        <input
          id="data-dictionary"
          type="file"
          accept=".pdf,.docx,.txt"
          aria-label="Data dictionary file"
          onChange={e => setDictionary(e.target.files[0])}
          disabled={loading}
        />
        {dictionary && <p className="text-sm text-ink-soft">Selected: <span className="font-medium text-ink">{dictionary.name}</span> ({formatFileSize(dictionary)})</p>}
        <p className="text-sm text-ink-faint">We require a data dictionary so we understand your columns from documentation rather than guessing from raw values.</p>

        <div className="flex flex-wrap gap-3 pt-2">
          <button type="submit" disabled={loading || !file || !dictionary} className="btn-primary">
            {loading && <Spinner />}
            {loading ? 'Processing…' : 'Continue'}
          </button>
        </div>
      </form>
    </div>
  )
}
