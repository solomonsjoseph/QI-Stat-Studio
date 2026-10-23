import React from 'react'
import AiKeyField from './AiKeyField'

export default function NoKeyPrompt({ onSaved, onSkip }) {
  return (
    <div className="screen max-w-xl">
      <h1 className="text-2xl font-semibold text-ink">The QI Stat Advisor needs an AI key</h1>
      <p className="mt-2 text-sm leading-6 text-ink-soft">
        The advisor reads your data warnings, proposes fixes, and writes interpretations. No key is configured yet.
      </p>

      <section className="card mt-6" aria-labelledby="nokey-enter">
        <h2 id="nokey-enter" className="mb-2 text-sm font-semibold text-ink">Enter a key here</h2>
        <AiKeyField onSaved={onSaved} />
        <p className="mt-3 text-xs leading-5 text-ink-soft">
          A saved key is app-wide. It replaces the key for everyone using this build.
        </p>
      </section>

      <section className="card mt-4" aria-labelledby="nokey-env">
        <h2 id="nokey-env" className="mb-2 text-sm font-semibold text-ink">Or set it in .env</h2>
        <p className="text-sm leading-6 text-ink-soft">
          Put the provider key in <code className="font-mono">.env</code> and restart with <code className="font-mono">make real</code>.
        </p>
      </section>

      <button type="button" onClick={onSkip} className="btn-secondary mt-6">Continue without the QI Stat Advisor</button>
    </div>
  )
}
