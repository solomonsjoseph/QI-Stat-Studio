import React from 'react'
import { useApp } from '../App'

// Render on screens that would use the advisor. Shows nothing while the advisor is available.
export default function AdvisorOffBanner() {
  const { advisorOff, goTo } = useApp()
  if (!advisorOff) return null
  return (
    <div role="status" className="alert-warn mb-4 flex flex-wrap items-center justify-between gap-2">
      <span>The QI Stat Advisor is off because no AI key is set. You can continue manually.</span>
      <button type="button" onClick={() => goTo('settings')} className="underline">Add a key in Settings</button>
    </div>
  )
}
