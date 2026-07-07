import React, { useState } from 'react'
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
    <main className="min-h-screen flex items-center justify-center p-6 bg-gray-50">
      <section className="w-full max-w-md bg-white border rounded-xl shadow-sm p-6" aria-labelledby="auth-heading">
        <h1 id="auth-heading" tabIndex="-1" className="text-3xl font-bold text-blue-800 mb-2">QI Stat Studio</h1>
        <p className="text-sm text-gray-600 mb-6">Sign in to create, resume, and share resident QI projects.</p>

        <div className="grid grid-cols-2 gap-2 mb-6" role="tablist" aria-label="Authentication mode">
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'login'}
            onClick={() => { setMode('login'); setError('') }}
            className={`px-4 py-2 rounded font-medium ${mode === 'login' ? 'bg-blue-700 text-white' : 'bg-gray-100 text-gray-700'}`}
          >
            Login
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'register'}
            onClick={() => { setMode('register'); setError('') }}
            className={`px-4 py-2 rounded font-medium ${mode === 'register' ? 'bg-blue-700 text-white' : 'bg-gray-100 text-gray-700'}`}
          >
            Register
          </button>
        </div>

        {error && <p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
        {loading && <p aria-live="polite" className="mb-4 text-sm text-gray-500">{mode === 'login' ? 'Signing in…' : 'Creating account…'}</p>}

        <form onSubmit={submit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 font-medium text-sm" htmlFor="auth-email">
            Email
            <input
              id="auth-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              disabled={loading}
              required
              className="border rounded px-3 py-2 font-normal"
            />
          </label>
          <label className="flex flex-col gap-1 font-medium text-sm" htmlFor="auth-password">
            Password
            <input
              id="auth-password"
              type="password"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              value={password}
              onChange={e => setPassword(e.target.value)}
              disabled={loading}
              required
              className="border rounded px-3 py-2 font-normal"
            />
          </label>
          <button
            type="submit"
            disabled={loading}
            className="px-5 py-2 bg-blue-700 text-white rounded font-medium hover:bg-blue-800 disabled:opacity-50"
          >
            {loading ? 'Please wait…' : mode === 'login' ? 'Login' : 'Create Account'}
          </button>
        </form>
      </section>
    </main>
  )
}
