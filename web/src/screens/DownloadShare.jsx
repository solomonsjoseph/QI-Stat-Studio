import React, { useState } from 'react'
import { useApp } from '../App'
import { api } from '../api'

function errorMessage(err) {
  return `${err.message || 'Could not create share link'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function DownloadShare() {
  const { ctx, update } = useApp()
  const [shareToken, setShareToken] = useState(ctx.shareToken || '')
  const [notificationStatus, setNotificationStatus] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const runId = ctx.runId

  async function createShare() {
    const q10 = ctx.answers?.q10 || {}
    const email = typeof q10 === 'object' ? q10.email : ''
    setSaving(true)
    setError('')
    try {
      const resp = await api.createShare(ctx.projectId, email)
      setShareToken(resp.token)
      update({ shareToken: resp.token })
      if (resp.notification_status) setNotificationStatus(resp.notification_status)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-xl mx-auto p-8 mt-8">
      <h1 className="text-2xl font-bold mb-6 text-blue-800">Download & Share</h1>
      {error && <p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
      {saving && <p aria-live="polite" className="mb-4 text-sm text-gray-500">Creating mentor share link…</p>}

      <div className="flex flex-col gap-4 mb-8">
        <a href={runId ? api.docxUrl(runId) : '#'} aria-disabled={!runId} download className={`px-5 py-3 border border-blue-600 text-blue-700 rounded font-medium text-center hover:bg-blue-50 ${!runId ? 'opacity-50 pointer-events-none' : ''}`}>Download Word (.docx)</a>
        <a href={runId ? api.pdfUrl(runId) : '#'} aria-disabled={!runId} download className={`px-5 py-3 border border-blue-600 text-blue-700 rounded font-medium text-center hover:bg-blue-50 ${!runId ? 'opacity-50 pointer-events-none' : ''}`}>Download PDF</a>
      </div>

      <div className="border-t pt-6">
        <h2 className="font-semibold mb-3">Share with Mentor</h2>
        {notificationStatus && <p className="text-sm text-gray-600 mb-2">Notification status: {notificationStatus}</p>}
        {shareToken ? (
          <div>
            <p className="text-sm text-gray-600 mb-2">Share this link:</p>
            <code className="block bg-gray-100 rounded px-3 py-2 text-sm break-all">{window.location.origin}/mentor/{shareToken}</code>
          </div>
        ) : (
          <button type="button" onClick={createShare} disabled={saving} className="px-5 py-2 bg-green-600 text-white rounded font-medium hover:bg-green-700 disabled:opacity-50">
            {saving ? 'Creating…' : 'Create Share Link'}
          </button>
        )}
      </div>
    </div>
  )
}
