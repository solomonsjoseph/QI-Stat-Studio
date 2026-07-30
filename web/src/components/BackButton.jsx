import React from 'react'

export default function BackButton({ onClick, children = '← Back', disabled }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} className="btn-secondary">
      {children}
    </button>
  )
}
