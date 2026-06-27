import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

export default function Settings() {
  const { goTo } = useApp()
  const [settings, setSettings] = useState({})
  const [key, setKey] = useState('')
  const [val, setVal] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.getSettings().then(setSettings)
  }, [])

  async function save(e) {
    e.preventDefault()
    await api.saveSetting(key, val)
    const updated = await api.getSettings()
    setSettings(updated)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
    setKey(''); setVal('')
  }

  return (
    <div className="max-w-xl mx-auto p-8 mt-8">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-blue-800">Settings</h2>
        <button onClick={() => goTo('landing')} className="text-sm text-gray-500 underline">Back</button>
      </div>

      <div className="mb-6">
        <h3 className="font-semibold mb-2 text-sm">Current Settings</h3>
        {Object.keys(settings).length === 0
          ? <p className="text-gray-400 text-sm">No settings configured.</p>
          : (
            <table className="w-full text-sm border-collapse">
              <tbody>
                {Object.entries(settings).map(([k, v]) => (
                  <tr key={k}>
                    <td className="border px-3 py-2 font-mono">{k}</td>
                    <td className="border px-3 py-2">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </div>

      <form onSubmit={save} className="flex flex-col gap-3">
        <h3 className="font-semibold text-sm">Add / Update Setting</h3>
        <input className="border rounded px-3 py-2 text-sm" placeholder="Key (e.g. clinic_name)" value={key} onChange={e => setKey(e.target.value)} required />
        <input className="border rounded px-3 py-2 text-sm" placeholder="Value" value={val} onChange={e => setVal(e.target.value)} required />
        <button type="submit" className="px-5 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 self-start">
          {saved ? 'Saved ✓' : 'Save'}
        </button>
      </form>
    </div>
  )
}
