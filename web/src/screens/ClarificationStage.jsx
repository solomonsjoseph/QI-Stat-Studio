import React, { useEffect, useState } from 'react'
import { useApp } from '../App'
import PageIntro from '../components/PageIntro'
import Spinner from '../components/Spinner'
import { api } from '../api'

function errorMessage(err) {
  return `${err.message || 'AI clarification failed'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function ClarificationStage() {
  const { ctx, update, next } = useApp()
  const [panelOpen, setPanelOpen] = useState(false)
  const [turns, setTurns] = useState([])
  const [confirmed, setConfirmed] = useState(false)
  const [suggestion, setSuggestion] = useState(null) // { title, description }
  const [input, setInput] = useState('')
  const [pendingRedacted, setPendingRedacted] = useState(null) // redacted text awaiting a second Share click
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    async function hydrate() {
      try {
        const project = await api.getProject(ctx.projectId)
        if (cancelled) return
        const state = project.ai_clarification_state
        if (state?.turns?.length) {
          setTurns(state.turns)
          setConfirmed(!!state.confirmed)
        }
      } catch {
        // No prior state yet -- fine, conversation starts fresh.
      }
    }
    hydrate()
    return () => { cancelled = true }
  }, [ctx.projectId])

  function applyClarifyResult(body) {
    setTurns(body.turns)
    setConfirmed(body.confirmed)
    if (body.suggested_title || body.suggested_description) {
      setSuggestion({ title: body.suggested_title, description: body.suggested_description })
    }
  }

  async function openPanelAndMaybeStart() {
    setPanelOpen(true)
    if (turns.length === 0) {
      setLoading(true)
      setError('')
      try {
        const body = await api.clarify(ctx.projectId, null)
        applyClarifyResult(body)
      } catch (err) {
        setError(errorMessage(err))
      } finally {
        setLoading(false)
      }
    }
  }

  async function handleContinue() {
    if (!confirmed) {
      await openPanelAndMaybeStart()
      return
    }
    setPanelOpen(false)
    next()
  }

  async function share() {
    const text = pendingRedacted ?? input
    if (!text.trim()) return
    if (pendingRedacted === null) {
      setLoading(true)
      setError('')
      try {
        const scan = await api.scrubPreview(text)
        if (scan.redacted) {
          setPendingRedacted(scan.text)
          setLoading(false)
          return
        }
      } catch (err) {
        setError(errorMessage(err))
        setLoading(false)
        return
      }
    }
    setLoading(true)
    setError('')
    try {
      const body = await api.clarify(ctx.projectId, text)
      applyClarifyResult(body)
      setInput('')
      setPendingRedacted(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function acceptSuggestion() {
    const title = suggestion.title || ctx.projectTitle
    const description = suggestion.description || ctx.projectDesc
    try {
      await api.updateProject(ctx.projectId, { title, description })
      update({ projectTitle: title, projectDesc: description })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSuggestion(null)
    }
  }

  function dismissSuggestion() {
    setSuggestion(null)
  }

  const lastAiTurn = [...turns].reverse().find(t => t.role === 'ai')

  return (
    <div className="screen max-w-xl" style={{ position: 'relative' }}>
      <PageIntro
        step="intake"
        title="Your project"
        lead="Confirm the details below with the AI before moving on."
      />
      <div className="card flex flex-col gap-4">
        <div>
          <span className="label">Project Title</span>
          <p className="font-medium text-ink">{ctx.projectTitle}</p>
        </div>
        <div>
          <span className="label">Project Description</span>
          <p className="text-ink-soft">{ctx.projectDesc}</p>
        </div>

        <div className="flex flex-wrap gap-3 pt-2">
          <button
            type="button"
            onClick={() => (panelOpen ? setPanelOpen(false) : openPanelAndMaybeStart())}
            disabled={loading}
            className="btn-secondary"
          >
            Chat with AI
          </button>
          <button type="button" onClick={handleContinue} disabled={loading} className="btn-primary">
            {loading && <Spinner />}
            Continue
          </button>
        </div>
        {!confirmed && <p className="text-sm text-ink-faint">Chat with the AI to confirm your project definition before continuing.</p>}
        {error && <p role="alert" className="alert-error">{error}</p>}
      </div>

      {panelOpen && (
        <div
          role="dialog"
          aria-label="AI Clarification"
          className="card"
          style={{ position: 'absolute', top: 0, right: '-420px', width: '380px', maxHeight: '80vh', display: 'flex', flexDirection: 'column' }}
        >
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-medium text-ink">AI Clarification</h2>
            <button type="button" onClick={() => setPanelOpen(false)} aria-label="Close AI clarification panel" className="btn-secondary px-2 py-1">
              ✕
            </button>
          </div>

          {suggestion && (suggestion.title || suggestion.description) && (
            <div className="alert-info mb-3">
              <p className="font-medium mb-1">Suggested rewrite:</p>
              {suggestion.title && <p><strong>Title:</strong> {suggestion.title}</p>}
              {suggestion.description && <p><strong>Description:</strong> {suggestion.description}</p>}
              <div className="flex gap-2 mt-2">
                <button type="button" onClick={acceptSuggestion} className="btn-primary px-3 py-1">Accept</button>
                <button type="button" onClick={dismissSuggestion} className="btn-secondary px-3 py-1">Dismiss</button>
              </div>
            </div>
          )}

          <div style={{ overflowY: 'auto', flex: 1 }} className="flex flex-col gap-2 mb-3">
            {turns.map((turn, i) => (
              <p key={i} className={turn.role === 'ai' ? 'text-ink' : 'text-ink-soft'}>
                <strong>{turn.role === 'ai' ? 'AI' : 'You'}:</strong> {turn.content}
              </p>
            ))}
          </div>

          {pendingRedacted !== null && (
            <p role="alert" className="alert-warn mb-2">
              We removed what looked like PHI from your message. Click Share again to send the redacted version below.
            </p>
          )}
          <textarea
            className="input mb-2"
            value={pendingRedacted ?? input}
            onChange={e => { setInput(e.target.value); setPendingRedacted(null) }}
            placeholder="Type your message..."
            disabled={loading}
          />
          <div className="flex items-center justify-between">
            {lastAiTurn?.reasoning ? (
              <span
                title={lastAiTurn.reasoning}
                aria-label="AI thinking"
                className="text-sm text-ink-faint"
                style={{ cursor: 'help' }}
              >
                (i) AI thinking
              </span>
            ) : <span />}
            <button type="button" onClick={share} disabled={loading} className="btn-primary">
              {loading && <Spinner />}
              Share
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
