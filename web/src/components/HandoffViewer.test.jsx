import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import HandoffViewer, { renderMarkdown } from './HandoffViewer'

vi.mock('../api', () => ({ api: { getHandoff: vi.fn() } }))
afterEach(() => cleanup())

const md = [
  '# Handoff', '', 'Intro <script>window.__pwned = true</script> text', '',
  '| Column | Type |', '| --- | --- |', '| age | number |', '',
  '```', '<img src=x onerror="window.__pwned=true">', '```', '', '- first', '- second',
].join('\n')

describe('HandoffViewer', () => {
  it('renders headings, tables, lists and code, and never executes markup', () => {
    const { container } = render(<HandoffViewer handoff={{ upload_id: 1, revision: 2, markdown: md, change_log: [
      { revision: 2, kind: 'apply', actor: 'advisor', created_at: '2026-10-23T10:00:00', summary: 'Merged MG' },
    ] }} />)
    expect(screen.getByRole('heading', { name: 'Handoff' })).toBeInTheDocument()
    expect(screen.getByRole('table')).toHaveTextContent('age')
    expect(screen.getByText('first')).toBeInTheDocument()
    expect(screen.getByText(/Intro <script>/)).toBeInTheDocument()
    expect(container.querySelector('script, img')).toBeNull()
    expect(window.__pwned).toBeUndefined()
    expect(screen.getByText('Revision 2')).toBeInTheDocument()
    expect(screen.getByText('Merged MG')).toBeInTheDocument()
  })
  it('shows one example per warning and folds the rest into a collapsed details element', () => {
    const doc = ['## Quality warnings', '', '- `case_inconsistent:sex` [WARNING] Mixed case.', '  - Examples: M; m; F; f', '- `x:y` [WARNING] One value.', '  - Examples: only'].join('\n')
    const { container } = render(<HandoffViewer handoff={{ upload_id: 1, revision: 1, markdown: doc, change_log: [] }} />)
    expect(screen.getByText(/Example: M/)).toBeInTheDocument()
    const details = container.querySelector('details')
    expect(details).not.toBeNull()
    expect(details.open).toBe(false)
    expect(screen.getByText('Show 3 more examples')).toBeInTheDocument()
    expect(container.querySelectorAll('details')).toHaveLength(1) // a single example has nothing to fold
    expect(screen.getByText('Examples: only')).toBeInTheDocument()
  })
})

describe('inline formatting', () => {
  it('shows inline code and bold as formatted text, not raw backticks or asterisks', () => {
    const { container } = render(<div>{renderMarkdown('## Quality warnings\n\n- `case_inconsistent:period` [WARNING] Mixed **case** in period\n\nPlain `x` text.')}</div>)
    expect(container.querySelectorAll('code')).toHaveLength(2)
    expect(container.querySelector('strong')).toHaveTextContent('case')
    expect(container.textContent).not.toMatch(/[`*]/)
  })
})
