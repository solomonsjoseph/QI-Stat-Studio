import React, { useCallback, useEffect, useMemo, useState } from 'react'
import Spinner from './Spinner'
import { api } from '../api'

function describe(err) {
  return `${err.message || 'Could not load the model list'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

function price(model) {
  if (model.prompt_price_per_million == null) return ''
  return ` · $${model.prompt_price_per_million}/M in`
}

// The list is fetched from the provider with the signed-in user's key each time it is opened or refreshed.
// refreshKey changes when the key is saved or removed, so the list follows the key.
export default function ModelPicker({ refreshKey }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [choice, setChoice] = useState('')
  const [filter, setFilter] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState('')

  const load = useCallback(async (refresh = false) => {
    setLoading(true)
    setError('')
    try {
      const result = await api.getAiModels(refresh)
      setData(result)
      setChoice(result.current_model)
    } catch (err) {
      setData(null)
      setError(describe(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(false) }, [load, refreshKey])

  const options = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    const list = (data?.models || []).filter(m => !needle || m.id.toLowerCase().includes(needle) || m.name.toLowerCase().includes(needle))
    // Keep the chosen model selectable even when a filter hides it or the provider no longer lists it.
    if (data && choice && !list.some(m => m.id === choice)) list.unshift({ id: choice, name: choice })
    return list
  }, [data, filter, choice])

  async function persist(action) {
    setSaving(true)
    setError('')
    setSaved('')
    try {
      const result = await action()
      setData(d => ({ ...d, current_model: result.current_model, chosen_by: result.chosen_by, current_listed: d.models.some(m => m.id === result.current_model) }))
      setChoice(result.current_model)
      setSaved(result.chosen_by === 'you' ? 'Saved' : 'Using the default')
    } catch (err) {
      setError(describe(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="card mb-6 flex flex-col gap-3" aria-labelledby="model-heading">
      <h2 id="model-heading" className="text-sm font-semibold text-ink">QI Stat Advisor model</h2>
      <p className="text-xs leading-5 text-ink-soft">
        This list comes from your AI provider, using your key, each time you open this page. It is not built into the app.
      </p>
      {loading && <p aria-live="polite" className="flex items-center gap-2 text-sm text-ink-soft"><Spinner />Loading models…</p>}
      {error && <p role="alert" className="alert-error">{error}</p>}
      {data && !loading && <>
        <p className="text-sm text-ink-soft" aria-live="polite">
          Current model: <span className="font-mono">{data.current_model}</span> ({data.chosen_by === 'you' ? 'your choice' : 'default'}).
        </p>
        {!data.current_listed && (
          <p className="text-xs leading-5 text-ink-soft">
            Your provider no longer lists this model. It may still work as an alias, but pick one from the list to be sure.
          </p>
        )}
        <label htmlFor="model-filter" className="label">Filter models</label>
        <input id="model-filter" className="input" value={filter} onChange={e => setFilter(e.target.value)} placeholder="Type part of a name" disabled={saving} />
        <label htmlFor="model-select" className="label">Model ({data.models.length} available)</label>
        <select id="model-select" className="input" value={choice} onChange={e => setChoice(e.target.value)} disabled={saving}>
          {options.map(m => <option key={m.id} value={m.id}>{`${m.name}${m.name === m.id ? '' : ` (${m.id})`}${price(m)}`}</option>)}
        </select>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-primary" disabled={saving || choice === data.current_model} onClick={() => persist(() => api.saveAiModel(choice))}>
            {saving ? 'Saving…' : 'Use this model'}
          </button>
          {data.chosen_by === 'you' && (
            <button type="button" className="btn-secondary" disabled={saving} onClick={() => persist(() => api.clearAiModel())}>Use the default</button>
          )}
          <button type="button" className="btn-secondary" disabled={saving || loading} onClick={() => load(true)}>Refresh list</button>
        </div>
        {saved && <p role="status" className="text-sm text-ink-soft">{saved}</p>}
      </>}
      {!data && !loading && <button type="button" className="btn-secondary self-start" onClick={() => load(true)}>Try again</button>}
    </section>
  )
}
