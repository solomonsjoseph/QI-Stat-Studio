import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
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
    <div className="screen max-w-xl">
      <div className="mb-6 flex items-start justify-between gap-4">
        <PageIntro title="Settings" />
        <button type="button" onClick={() => goTo(ctx.previousScreen || 'landing')} className="btn-secondary px-4 py-2">Back</button>
      </div>

      {loading && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />Loading settings…</p>}
      {error && <p role="alert" className="alert-error mb-4">{error}</p>}

      <section className="mb-6" aria-labelledby="current-settings-heading">
        <h2 id="current-settings-heading" className="mb-2 text-sm font-semibold text-ink">Current Settings</h2>
        {!loading && settings.length === 0 ? (
          <p className="text-sm text-ink-soft">No runtime settings configured.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="table-clean">
              <thead>
                <tr><th>Key</th><th>Value</th></tr>
              </thead>
              <tbody>
                {settings.map(item => (
                  <tr key={item.key}>
                    <td className="font-mono">{item.key}</td>
                    <td>{String(item.value ?? '')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <form onSubmit={save} className="card flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-ink">Add / Update Setting</h2>
        <label htmlFor="setting-key" className="label">Setting key</label>
        <input id="setting-key" className="input" placeholder="clinic_name" value={key} onChange={e => setKey(e.target.value)} required disabled={saving} />
        <label htmlFor="setting-value" className="label">Setting value</label>
        <input id="setting-value" className="input" placeholder="Value" value={val} onChange={e => setVal(e.target.value)} required disabled={saving} />
        <button type="submit" disabled={saving} className="btn-primary self-start">
          {saving && <Spinner />}
          {saving ? 'Saving…' : saved ? 'Saved' : 'Save'}
        </button>
      </form>
    </div>
  )
}
