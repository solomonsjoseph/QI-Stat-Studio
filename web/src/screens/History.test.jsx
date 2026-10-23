import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import History from './History'

const { apiMock } = vi.hoisted(() => ({
  apiMock: { listProjects: vi.fn(), getHandoffHistory: vi.fn(), getHandoff: vi.fn(), deleteHandoff: vi.fn() },
}))
vi.mock('../api', () => ({ api: apiMock }))

const item = (o = {}) => ({ upload_id: 5, file_name: 'old.csv', created_at: '2026-01-01T00:00:00', replaced_at: '2026-02-01T00:00:00', status: 'replaced', revision: 2, change_log_entries: 2, ...o })

beforeEach(() => {
  Object.values(apiMock).forEach(m => m.mockReset())
  apiMock.listProjects.mockResolvedValue([{ id: 1, title: 'Falls' }])
  apiMock.getHandoffHistory.mockResolvedValue({ project_id: 1, items: [item(), item({ upload_id: 6, file_name: 'gone.csv', status: 'deleted' })] })
})
afterEach(cleanup)

describe('History', () => {
  it('lists items and opens one read-only', async () => {
    apiMock.getHandoff.mockResolvedValue({ upload_id: 5, markdown: 'DOC BODY', change_log: [], read_only: true })
    render(<History />)
    expect(await screen.findByText(/old\.csv/)).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Open handoff for old.csv' }))
    expect(await screen.findByText('DOC BODY')).toBeTruthy()
    expect(apiMock.getHandoff).toHaveBeenCalledWith(5)
  })

  it('offers delete only for replaced handoffs and confirms first', async () => {
    apiMock.deleteHandoff.mockResolvedValue({ ok: true })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<History />)
    await screen.findByText(/old\.csv/)
    expect(screen.queryByRole('button', { name: /Delete handoff document for gone\.csv/ })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /Delete handoff document for old\.csv/ }))
    expect(confirm.mock.calls[0][0]).toMatch(/change log is kept.*administrator/)
    expect(apiMock.deleteHandoff).toHaveBeenCalledWith(5)
    confirm.mockRestore()
  })

  it('does not delete when the confirm is cancelled', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<History />)
    await screen.findByText(/old\.csv/)
    await userEvent.click(screen.getByRole('button', { name: /Delete handoff document for old\.csv/ }))
    expect(apiMock.deleteHandoff).not.toHaveBeenCalled()
    confirm.mockRestore()
  })
})
