import React, { useState } from 'react'
import { useApp } from '../App'
import BackButton from '../components/BackButton'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

const COL_TYPE_OPTIONS = ['Number', 'Category', 'Date', 'ID', 'Yes/No']

function errorMessage(err) {
  return `${err.message || 'Upload failed'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function UploadIcon() {
  return (
    <svg className="mx-auto mb-4 h-8 w-8 text-ink-soft" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 16V4m0 0 4 4m-4-4-4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 16.5V18a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

function formatFileSize(file) {
  if (!file) return ''
  if (file.size < 1024 * 1024) return `${Math.max(1, Math.round(file.size / 1024))} KB`
  return `${(file.size / (1024 * 1024)).toFixed(1)} MB`
}

export default function Upload() {
  const { ctx, update, next, prev } = useApp()
  const [file, setFile] = useState(null)
  const [uploadResult, setUploadResult] = useState(null)
  const [colTypes, setColTypes] = useState({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleUpload(e) {
    e.preventDefault()
    if (!file) return
    setLoading(true)
    setError('')
    try {
      const result = await api.upload(ctx.projectId, file)
      setUploadResult(result)
      const detected = result.col_types || {}
      setColTypes(detected)
      update({ uploadId: result.id || result.upload_id })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function confirmTypes(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await api.confirmColTypes(ctx.uploadId, colTypes)
      update({
        colTypes,
        qualityFlags: uploadResult?.quality_flags || [],
        rowCount: uploadResult?.row_count,
        missingPct: uploadResult?.missing_pct || {},
      })
      next()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const isExcelUpload = /\.xlsx?$/i.test(file?.name || '')
  const detectedColumnCount = uploadResult ? Object.keys(uploadResult.col_types || {}).length : 0
  const previewRows = uploadResult?.preview_rows || []
  const previewColumns = previewRows.length ? Object.keys(previewRows[0] || {}) : []


  if (uploadResult) {
    return (
      <div className="screen">
        <PageIntro step="upload" title="Confirm Column Types" lead="Review the detected column types and correct any that are wrong." />
        {error && <p role="alert" className="alert-error mb-4">{error}</p>}
        {saving && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Saving column types…</p>}
        {isExcelUpload && (
          <div className="alert-info mb-4">
            We read your Excel file "{file.name}" and converted it automatically — {uploadResult.row_count ?? 0} rows and {detectedColumnCount} columns from the first sheet. Review the detected types below.
          </div>
        )}
        {previewRows.length > 0 && (
          <section className="card mb-6" aria-labelledby="data-preview-heading">
            <h2 id="data-preview-heading" className="mb-3 font-medium text-ink">Data preview (first 5 rows)</h2>
            <div className="overflow-x-auto">
              <table className="table-clean">
                <thead>
                  <tr>
                    {previewColumns.map(col => <th key={col}>{col}</th>)}
                  </tr>
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
                <tr><th>Column</th><th>Type</th><th>Missing %</th></tr>
              </thead>
              <tbody>
                {Object.entries(uploadResult.col_types || {}).map(([col]) => (
                  <tr key={col}>
                    <td className="font-mono">{col}</td>
                    <td>
                      <label className="sr-only" htmlFor={`type-${col}`}>Type for {col}</label>
                      <select id={`type-${col}`} value={colTypes[col] || 'Category'} onChange={e => setColTypes(t => ({ ...t, [col]: e.target.value }))} disabled={saving} className="input min-w-32">
                        {COL_TYPE_OPTIONS.map(o => <option key={o}>{o}</option>)}
                      </select>
                    </td>
                    <td>{((uploadResult.missing_pct || {})[col] || 0).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={() => { setUploadResult(null); setFile(null); setColTypes({}) }} disabled={saving} className="btn-secondary">
              Choose a different file
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
      <PageIntro step="upload" title="Upload Your Data" />
      <div className="alert-warn mb-6">
        Do not upload files containing patient names, MRNs, or other direct identifiers. Column headers and aggregate statistics only are sent to AI features.
      </div>
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}
      {loading && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Uploading and scanning file…</p>}
      <form onSubmit={handleUpload} className="flex flex-col gap-4">
        <label
          htmlFor="data-file"
          className="rounded-xl border-2 border-dashed border-line px-8 py-12 text-center transition hover:border-brand-ring cursor-pointer"
          onDragOver={e => e.preventDefault()}
          onDrop={e => {
            e.preventDefault()
            if (e.dataTransfer.files?.[0]) setFile(e.dataTransfer.files[0])
          }}
        >
          <UploadIcon />
          <span className="block font-medium text-ink">Choose a CSV or Excel file</span>
          <span className="mt-1 block text-sm text-ink-soft">or drag it here</span>
          <input
            id="data-file"
            type="file"
            accept=".csv,.xlsx,.xls"
            aria-label="CSV or Excel file"
            onChange={e => setFile(e.target.files[0])}
            disabled={loading}
            className="sr-only"
          />
        </label>
        {file && <p className="text-sm text-ink-soft">Selected: <span className="font-medium text-ink">{file.name}</span> ({formatFileSize(file)})</p>}
        <div className="flex flex-wrap gap-3">
          <BackButton onClick={prev} disabled={loading} />
          <button type="submit" disabled={loading || !file} className="btn-primary">
            {loading && <Spinner />}
            {loading ? 'Uploading…' : 'Upload CSV/Excel'}
          </button>
        </div>
      </form>
    </div>
  )
}
