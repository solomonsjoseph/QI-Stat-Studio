import React, { useState } from 'react'
import Spinner from '../components/Spinner'
import { api } from '../api'

function errorMessage(err) {
  return `${err.message || 'Authentication failed'}${err.requestId ? ` (Request ID: ${err.requestId})` : ''}`
}

export default function Auth({ onAuthenticated }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const user = mode === 'login'
        ? await api.login(email, password)
        : await api.register(email, password)
      onAuthenticated(user)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-6 py-10">
      <section className="card w-full max-w-md" aria-labelledby="auth-heading">
        <div className="mb-6">
          <h1 id="auth-heading" tabIndex="-1" className="text-3xl font-semibold text-ink">QI Stat Studio</h1>
          <p className="mt-2 text-sm leading-6 text-ink-soft">Sign in to create, resume, and share resident QI projects.</p>
        </div>

        <div className="mb-6 grid grid-cols-2 rounded-lg border border-line p-1" role="tablist" aria-label="Authentication mode">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'login'}
            onClick={() => { setMode('login'); setError('') }}
            className={`rounded-md px-4 py-2 text-sm font-medium transition ${mode === 'login' ? 'bg-ink text-white' : 'text-ink-soft hover:text-ink'}`}
          >
            Login
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'register'}
            onClick={() => { setMode('register'); setError('') }}
            className={`rounded-md px-4 py-2 text-sm font-medium transition ${mode === 'register' ? 'bg-ink text-white' : 'text-ink-soft hover:text-ink'}`}
          >
            Register
          </button>
        </div>

        {error && <p role="alert" className="alert-error mb-4">{error}</p>}
        {loading && <p aria-live="polite" className="mb-4 flex items-center gap-2 text-sm text-ink-soft"><Spinner />{mode === 'login' ? 'Signing in…' : 'Creating account…'}</p>}

        <form onSubmit={submit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1" htmlFor="auth-email">
            <span className="label">Email</span>
            <input
              id="auth-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              disabled={loading}
              required
              className="input"
            />
          </label>
          <label className="flex flex-col gap-1" htmlFor="auth-password">
            <span className="label">Password</span>
            <input
              id="auth-password"
              type="password"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              value={password}
              onChange={e => setPassword(e.target.value)}
              disabled={loading}
              required
              className="input"
            />
          </label>
          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading && <Spinner />}
            {loading ? 'Please wait…' : mode === 'login' ? 'Login' : 'Create Account'}
          </button>
        </form>
      </section>
    </main>
  )
}
