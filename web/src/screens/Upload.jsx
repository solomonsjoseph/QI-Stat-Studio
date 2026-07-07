import React, { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

const COL_TYPE_OPTIONS = ['Number', 'Category', 'Date', 'ID', 'Yes/No']

function errorMessage(err) {
  return `${err.message || 'Upload failed'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function Upload() {
  const { ctx, update, next } = useApp()
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

  if (uploadResult) {
    return (
      <div className="max-w-2xl mx-auto p-8 mt-8">
        <h1 className="text-2xl font-bold mb-4 text-blue-800">Confirm Column Types</h1>
        <p className="text-gray-600 mb-4">Review the detected column types and correct any that are wrong.</p>
        {error && <p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
        {saving && <p aria-live="polite" className="mb-4 text-sm text-gray-500">Saving column types…</p>}
        <form onSubmit={confirmTypes}>
          <table className="w-full text-sm border-collapse mb-6">
            <thead>
              <tr className="bg-gray-100">
                <th className="border px-3 py-2 text-left">Column</th>
                <th className="border px-3 py-2 text-left">Type</th>
                <th className="border px-3 py-2 text-left">Missing %</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(uploadResult.col_types || {}).map(([col]) => (
                <tr key={col}>
                  <td className="border px-3 py-2 font-mono">{col}</td>
                  <td className="border px-3 py-2">
                    <label className="sr-only" htmlFor={`type-${col}`}>Type for {col}</label>
                    <select
                      id={`type-${col}`}
                      value={colTypes[col] || 'Category'}
                      onChange={e => setColTypes(t => ({ ...t, [col]: e.target.value }))}
                      disabled={saving}
                      className="border rounded px-2 py-1"
                    >
                      {COL_TYPE_OPTIONS.map(o => <option key={o}>{o}</option>)}
                    </select>
                  </td>
                  <td className="border px-3 py-2">{((uploadResult.missing_pct || {})[col] || 0).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            type="submit"
            disabled={saving}
            className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Confirm Types →'}
          </button>
        </form>
      </div>
    )
  }

  return (
    <div className="max-w-xl mx-auto p-8 mt-8">
      <h1 className="text-2xl font-bold mb-6 text-blue-800">Upload Your Data</h1>
      <div className="bg-yellow-50 border border-yellow-400 text-yellow-800 rounded px-4 py-3 mb-6 text-sm">
        ⚠ Do not upload files containing patient names, MRNs, or other direct identifiers. Column headers and aggregate statistics only are sent to AI features.
      </div>
      {error && <p role="alert" className="text-red-700 mb-4 text-sm">{error}</p>}
      {loading && <p aria-live="polite" className="text-gray-500 mb-4 text-sm">Uploading and scanning file…</p>}
      <form onSubmit={handleUpload} className="flex flex-col gap-4">
        <label htmlFor="data-file" className="font-medium">CSV or Excel file</label>
        <input
          id="data-file"
          type="file"
          accept=".csv,.xlsx,.xls"
          onChange={e => setFile(e.target.files[0])}
          disabled={loading}
          required
          className="border rounded px-3 py-2"
        />
        <button
          type="submit"
          disabled={loading}
          className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50"
        >
          {loading ? 'Uploading…' : 'Upload CSV/Excel'}
        </button>
      </form>
    </div>
  )
}
