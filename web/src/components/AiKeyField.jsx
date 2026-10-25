import React, { useState } from 'react'
import Spinner from './Spinner'
import { api } from '../api'

// Masked key entry. The typed key is cleared after a save and never shown again.
export default function AiKeyField({ onSaved, label = 'AI key', saveLabel = 'Save key' }) {
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      const status = await api.saveAiKey(value.trim())
      setValue('')
      onSaved?.(status)
    } catch (err) {
      setError(err.fieldErrors?.key?.join(', ') || err.message || 'Could not save the key')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <label htmlFor="ai-key-input" className="label">{label}</label>
      <input
        id="ai-key-input"
        type="password"
        autoComplete="off"
        className="input"
        value={value}
        onChange={e => setValue(e.target.value)}
        disabled={saving}
        required
      />
      {error && <p role="alert" className="alert-error">{error}</p>}
      <button type="submit" disabled={saving || !value.trim()} className="btn-primary self-start">
        {saving && <Spinner />}
        {saving ? 'Saving…' : saveLabel}
      </button>
    </form>
  )
}
