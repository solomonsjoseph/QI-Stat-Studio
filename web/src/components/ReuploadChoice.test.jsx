import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReuploadChoice from './ReuploadChoice'

const { apiMock, appMock } = vi.hoisted(() => ({
  apiMock: { replaceUpload: vi.fn(), reuploadChoice: vi.fn() },
  appMock: { ctx: { projectId: 1, uploadId: 2 }, update: vi.fn() },
}))
vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: () => appMock }))

const pick = () => userEvent.upload(screen.getByLabelText('Choose a replacement file'), new File(['a'], 'a.csv', { type: 'text/csv' }))

beforeEach(() => { Object.values(apiMock).forEach(m => m.mockReset()); appMock.update.mockReset() })
afterEach(cleanup)

describe('ReuploadChoice', () => {
  it('asks keep or fresh for identical files and posts the choice', async () => {
    apiMock.replaceUpload.mockResolvedValue({ id: 9, choice_required: true, same_as_previous: true })
    apiMock.reuploadChoice.mockResolvedValue({})
    render(<ReuploadChoice />)
    await pick()
    expect(await screen.findByText('This looks like the exact files you used last time. Keep all the changes you made, or start fresh?')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Keep' }))
    await waitFor(() => expect(apiMock.reuploadChoice).toHaveBeenCalledWith(9, 'keep'))
    expect(await screen.findByText('Your earlier changes were kept.')).toBeTruthy()
  })

  it('sends fresh when Start fresh is chosen', async () => {
    apiMock.replaceUpload.mockResolvedValue({ id: 9, choice_required: true })
    apiMock.reuploadChoice.mockResolvedValue({})
    render(<ReuploadChoice />)
    await pick()
    await userEvent.click(await screen.findByRole('button', { name: 'Start fresh' }))
    await waitFor(() => expect(apiMock.reuploadChoice).toHaveBeenCalledWith(9, 'fresh'))
  })

  it('shows a History notice when the file differs', async () => {
    apiMock.replaceUpload.mockResolvedValue({ id: 9, started_fresh: true, choice_required: false })
    render(<ReuploadChoice />)
    await pick()
    expect(await screen.findByText(/new handoff was started.*saved in History/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Keep' })).toBeNull()
  })
})
