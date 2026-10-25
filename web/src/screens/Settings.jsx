import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import AiKeyField from '../components/AiKeyField'
import ModelPicker from '../components/ModelPicker'
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
  const { ctx, goTo, setAdvisorStatus, user } = useApp()
  const isAdmin = user?.role === 'admin'
  const [keyStatus, setKeyStatus] = useState(null)
  const [keyError, setKeyError] = useState('')
  const [removing, setRemoving] = useState(false)
  const [keyVersion, setKeyVersion] = useState(0)  // bumps when the key changes so the model list reloads with it
  const [settings, setSettings] = useState([])
  const [key, setKey] = useState('')
  const [val, setVal] = useState('')
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(isAdmin)
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
    if (isAdmin) load()
    api.getAiKeyStatus().then(setKeyStatus).catch(err => setKeyError(errorMessage(err)))
  }, [isAdmin])

  function keySaved(status) {
    setKeyStatus(status)
    setKeyError('')
    setKeyVersion(v => v + 1)
    setAdvisorStatus?.(status)
  }

  async function removeKey() {
    setRemoving(true)
    setKeyError('')
    try {
      keySaved(await api.clearAiKey())
    } catch (err) {
      setKeyError(errorMessage(err))
    } finally {
      setRemoving(false)
    }
  }

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

      <section className="card mb-6 flex flex-col gap-3" aria-labelledby="ai-key-heading">
        <h2 id="ai-key-heading" className="text-sm font-semibold text-ink">AI key</h2>
        <p className="text-sm text-ink-soft" aria-live="polite">
          {!keyStatus ? 'Checking key status…'
            : keyStatus.configured
              ? `Key set from ${keyStatus.source === 'env' ? '.env' : 'Settings'}, ending in ${keyStatus.last4}.`
              : 'No key set. The QI Stat Advisor is off.'}
        </p>
        {keyError && <p role="alert" className="alert-error">{keyError}</p>}
        <AiKeyField onSaved={keySaved} label="New key" />
        <p className="text-xs leading-5 text-ink-soft">
          Your saved key belongs to your account only. Nobody else can use it. It overrides the key in .env for you.
        </p>
        {keyStatus?.source === 'settings' && (
          <button type="button" onClick={removeKey} disabled={removing} className="btn-secondary self-start">
            {removing ? 'Removing…' : 'Remove saved key'}
          </button>
        )}
      </section>

      <ModelPicker refreshKey={keyVersion} />

      {isAdmin && <>
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
      </>}
    </div>
  )
}
