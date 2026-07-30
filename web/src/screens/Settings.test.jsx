import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Settings from './Settings'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    getSettings: vi.fn(),
    saveSetting: vi.fn(),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

beforeEach(() => {
  apiMock.getSettings.mockResolvedValue({ items: [{ key: 'clinic_name', value: 'Ward A' }] })
  apiMock.saveSetting.mockReset()
  useAppMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('Settings', () => {
  it('returns to the screen captured before settings instead of restarting the workflow', async () => {
    const goTo = vi.fn()
    useAppMock.mockReturnValue({ ctx: { previousScreen: 'results' }, goTo })

    const user = userEvent.setup()
    render(<Settings />)

    expect(await screen.findByText('clinic_name')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /back/i }))

    expect(goTo).toHaveBeenCalledWith('results')
  })
})
