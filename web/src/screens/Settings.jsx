import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

function errorMessage(err) {
  const fieldText = err.fieldErrors ? Object.entries(err.fieldErrors).map(([field, values]) => `${field}: ${values.join(', ')}`).join('; ') : ''
  const base = fieldText || err.message || 'Could not save settings'
  return `${base}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function normalizeSettings(data) {
  if (Array.isArray(data)) return data
  if (data?.items && Array.isArray(data.items)) return data.items
  return Object.entries(data || {}).map(([key, value]) => ({ key, value, type: 'string', runtime: true }))
}

export default function Settings() {
  const { ctx, goTo } = useApp()
  const [settings, setSettings] = useState([])
  const [key, setKey] = useState('')
  const [val, setVal] = useState('')
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      setSettings(normalizeSettings(await api.getSettings()))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function save(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await api.saveSetting(key, val)
      setSettings(normalizeSettings(await api.getSettings()))
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
      setKey('')
      setVal('')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-xl mx-auto p-8 mt-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-blue-800">Settings</h1>
        <button type="button" onClick={() => goTo(ctx.previousScreen || 'landing')} className="text-sm text-gray-600 underline">Back</button>
      </div>

      {loading && <p aria-live="polite" className="mb-4 text-sm text-gray-500">Loading settings…</p>}
      {error && <p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}

      <div className="mb-6">
        <h2 className="font-semibold mb-2 text-sm">Current Settings</h2>
        {!loading && settings.length === 0 ? (
          <p className="text-gray-400 text-sm">No runtime settings configured.</p>
        ) : (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-gray-100">
                <th className="border px-3 py-2 text-left">Key</th>
                <th className="border px-3 py-2 text-left">Value</th>
              </tr>
            </thead>
            <tbody>
              {settings.map(item => (
                <tr key={item.key}>
                  <td className="border px-3 py-2 font-mono">{item.key}</td>
                  <td className="border px-3 py-2">{String(item.value ?? '')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <form onSubmit={save} className="flex flex-col gap-3">
        <h2 className="font-semibold text-sm">Add / Update Setting</h2>
        <label htmlFor="setting-key" className="text-sm font-medium">Setting key</label>
        <input id="setting-key" className="border rounded px-3 py-2 text-sm" placeholder="clinic_name" value={key} onChange={e => setKey(e.target.value)} required disabled={saving} />
        <label htmlFor="setting-value" className="text-sm font-medium">Setting value</label>
        <input id="setting-value" className="border rounded px-3 py-2 text-sm" placeholder="Value" value={val} onChange={e => setVal(e.target.value)} required disabled={saving} />
        <button type="submit" disabled={saving} className="px-5 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50 self-start">
          {saving ? 'Saving…' : saved ? 'Saved ✓' : 'Save'}
        </button>
      </form>
    </div>
  )
}
