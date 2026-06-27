import React, { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

const COL_TYPE_OPTIONS = ['Number', 'Category', 'Date', 'ID', 'Yes/No']

export default function Upload() {
  const { ctx, update, next } = useApp()
  const [file, setFile] = useState(null)
  const [uploadResult, setUploadResult] = useState(null)
  const [colTypes, setColTypes] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleUpload(e) {
    e.preventDefault()
    if (!file) return
    setLoading(true); setError('')
    try {
      const result = await api.upload(ctx.projectId, file)
      setUploadResult(result)
      // Pre-populate col types from detected
      const detected = result.col_types || {}
      setColTypes(detected)
      update({ uploadId: result.upload_id })
    } catch (err) {
      setError(err.message)
    }
    setLoading(false)
  }

  async function confirmTypes(e) {
    e.preventDefault()
    await api.confirmColTypes(ctx.uploadId, colTypes)
    update({ colTypes, qualityFlags: uploadResult?.quality_flags })
    next()
  }

  if (uploadResult) {
    return (
      <div className="max-w-2xl mx-auto p-8 mt-8">
        <h2 className="text-2xl font-bold mb-4 text-blue-800">Confirm Column Types</h2>
        <p className="text-gray-600 mb-4">
          Review the detected column types and correct any that are wrong.
        </p>
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
                    <select
                      value={colTypes[col] || 'Category'}
                      onChange={e => setColTypes(t => ({ ...t, [col]: e.target.value }))}
                      className="border rounded px-2 py-1"
                    >
                      {COL_TYPE_OPTIONS.map(o => (
                        <option key={o}>{o}</option>
                      ))}
                    </select>
                  </td>
                  <td className="border px-3 py-2">
                    {((uploadResult.missing_pct || {})[col] || 0).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            type="submit"
            className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800"
          >
            Confirm Types →
          </button>
        </form>
      </div>
    )
  }

  return (
    <div className="max-w-xl mx-auto p-8 mt-8">
      <h2 className="text-2xl font-bold mb-6 text-blue-800">Upload Your Data</h2>
      {error && <p className="text-red-600 mb-4">{error}</p>}
      <form onSubmit={handleUpload} className="flex flex-col gap-4">
        <input
          type="file"
          accept=".csv"
          onChange={e => setFile(e.target.files[0])}
          required
          className="border rounded px-3 py-2"
        />
        <button
          type="submit"
          disabled={loading}
          className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50"
        >
          {loading ? 'Uploading…' : 'Upload CSV'}
        </button>
      </form>
    </div>
  )
}
