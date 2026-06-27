import React, { useState } from 'react'
import { useApp } from '../App'

export default function DataReview() {
  const { ctx, update, next } = useApp()
  const flags = ctx.qualityFlags || []
  const colTypes = ctx.colTypes || {}
  const [acknowledged, setAcknowledged] = useState({})

  function toggleAck(i) {
    setAcknowledged(a => ({ ...a, [i]: !a[i] }))
  }

  const allAcked = flags.every((_, i) => acknowledged[i])
  const canContinue = flags.length === 0 || allAcked

  function proceed() {
    update({ acknowledgedFlags: flags.filter((_, i) => acknowledged[i]) })
    next()
  }

  return (
    <div className="max-w-2xl mx-auto p-8 mt-8">
      <h2 className="text-2xl font-bold mb-4 text-blue-800">Data Review</h2>

      {/* Column summary */}
      <div className="mb-6">
        <h3 className="font-semibold mb-2">Column Types</h3>
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-100">
              <th className="border px-3 py-2 text-left">Column</th>
              <th className="border px-3 py-2 text-left">Type</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(colTypes).map(([col, type]) => (
              <tr key={col}>
                <td className="border px-3 py-2 font-mono">{col}</td>
                <td className="border px-3 py-2">{type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Quality flags */}
      {flags.length > 0 && (
        <div className="mb-6">
          <h3 className="font-semibold mb-2 text-yellow-700">Data Quality Flags</h3>
          <p className="text-sm text-gray-600 mb-3">
            Please acknowledge each issue before proceeding.
          </p>
          {flags.map((flag, i) => (
            <label key={i} className="flex items-start gap-2 mb-2 p-3 bg-yellow-50 border border-yellow-200 rounded">
              <input
                type="checkbox"
                checked={!!acknowledged[i]}
                onChange={() => toggleAck(i)}
                className="mt-1"
              />
              <div>
                <span className={`text-xs font-bold mr-2 ${flag.severity === 'ERROR' ? 'text-red-600' : 'text-yellow-700'}`}>
                  {flag.severity}
                </span>
                <span className="text-sm">{flag.msg}</span>
              </div>
            </label>
          ))}
        </div>
      )}

      {flags.length === 0 && (
        <p className="text-green-700 mb-6">✓ No data quality issues detected.</p>
      )}

      <button
        onClick={proceed}
        disabled={!canContinue}
        className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50"
      >
        Continue to Analysis Selection
      </button>
    </div>
  )
}
