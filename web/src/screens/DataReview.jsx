import React, { useState } from 'react'
import { useApp } from '../App'

export default function DataReview() {
  const { ctx, update, next, prev } = useApp()
  const flags = ctx.qualityFlags || []
  const colTypes = ctx.colTypes || {}
  const missingPct = ctx.missingPct || {}
  const rowCount = ctx.rowCount

  const errors = flags.filter(f => f.severity === 'ERROR')
  const warnings = flags.filter(f => f.severity !== 'ERROR')

  const [acknowledged, setAcknowledged] = useState({})

  function toggleAck(i) {
    setAcknowledged(a => ({ ...a, [i]: !a[i] }))
  }

  const allWarningsAcked = warnings.every((_, i) => acknowledged[i])
  const canContinue = errors.length === 0 && (warnings.length === 0 || allWarningsAcked)

  function proceed() {
    update({ acknowledgedFlags: warnings.filter((_, i) => acknowledged[i]) })
    next()
  }

  return (
    <div className="max-w-2xl mx-auto p-8 mt-8">
      <h2 className="text-2xl font-bold mb-4 text-blue-800">Data Review</h2>

      {/* Row count */}
      {rowCount != null && (
        <p className="text-sm text-gray-600 mb-4">{rowCount.toLocaleString()} rows loaded</p>
      )}

      {/* Column summary */}
      <div className="mb-6">
        <h3 className="font-semibold mb-2">Column Types</h3>
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-100">
              <th className="border px-3 py-2 text-left">Column</th>
              <th className="border px-3 py-2 text-left">Type</th>
              <th className="border px-3 py-2 text-left">Missing %</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(colTypes).map(([col, type]) => (
              <tr key={col}>
                <td className="border px-3 py-2 font-mono">{col}</td>
                <td className="border px-3 py-2">{type}</td>
                <td className="border px-3 py-2">
                  {missingPct[col] != null ? `${missingPct[col].toFixed(1)}%` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ERRORs block progression */}
      {errors.length > 0 && (
        <div className="mb-6 p-4 bg-red-50 border border-red-300 rounded">
          <h3 className="font-semibold text-red-700 mb-2">Data Errors (must fix before continuing)</h3>
          {errors.map((flag, i) => (
            <p key={i} className="text-sm text-red-700 mb-1">
              <span className="font-bold mr-1">ERROR:</span>{flag.msg}
            </p>
          ))}
          <button
            onClick={prev}
            className="mt-3 px-5 py-2 bg-red-600 text-white rounded font-medium hover:bg-red-700"
          >
            Re-upload corrected file
          </button>
        </div>
      )}

      {/* WARNINGs require acknowledgment */}
      {warnings.length > 0 && (
        <div className="mb-6">
          <h3 className="font-semibold mb-2 text-yellow-700">Data Quality Warnings</h3>
          <p className="text-sm text-gray-600 mb-3">
            Please acknowledge each issue before proceeding.
          </p>
          {warnings.map((flag, i) => (
            <label key={i} className="flex items-start gap-2 mb-2 p-3 bg-yellow-50 border border-yellow-200 rounded">
              <input
                type="checkbox"
                checked={!!acknowledged[i]}
                onChange={() => toggleAck(i)}
                className="mt-1"
              />
              <div>
                <span className="text-xs font-bold text-yellow-700 mr-2">WARNING</span>
                <span className="text-sm">{flag.msg}</span>
              </div>
            </label>
          ))}
        </div>
      )}

      {flags.length === 0 && (
        <p className="text-green-700 mb-6">✓ No data quality issues detected.</p>
      )}

      {errors.length === 0 && (
        <button
          onClick={proceed}
          disabled={!canContinue}
          className="px-6 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50"
        >
          Continue to Analysis Selection
        </button>
      )}
    </div>
  )
}
