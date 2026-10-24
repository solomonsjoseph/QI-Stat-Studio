import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Settings from './Settings'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    getSettings: vi.fn(),
    saveSetting: vi.fn(),
    getAiKeyStatus: vi.fn(),
    saveAiKey: vi.fn(),
    clearAiKey: vi.fn(),
    getAiModels: vi.fn(),
    saveAiModel: vi.fn(),
    clearAiModel: vi.fn(),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

const ADMIN = { email: 'a@x.org', role: 'admin' }

beforeEach(() => {
  apiMock.getSettings.mockResolvedValue({ items: [{ key: 'clinic_name', value: 'Ward A' }] })
  apiMock.saveSetting.mockReset()
  apiMock.getAiKeyStatus.mockReset().mockResolvedValue({ configured: true, source: 'settings', last4: '3456', provider: 'openrouter', advisor_available: true })
  apiMock.getAiModels.mockReset().mockResolvedValue({ provider: 'openrouter', current_model: 'v/a', chosen_by: 'default', current_listed: true, source: 'live', models: [{ id: 'v/a', name: 'A' }] })
  useAppMock.mockReset()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('Settings', () => {
  it('returns to the screen captured before settings instead of restarting the workflow', async () => {
    const goTo = vi.fn()
    useAppMock.mockReturnValue({ ctx: { previousScreen: 'results' }, goTo, user: ADMIN })

    const user = userEvent.setup()
    render(<Settings />)

    expect(await screen.findByText('clinic_name')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /back/i }))

    expect(goTo).toHaveBeenCalledWith('results')
  })

  it('shows the key masked with source and last4, and saves a new key without echoing it', async () => {
    useAppMock.mockReturnValue({ ctx: {}, goTo: vi.fn(), user: ADMIN, setAdvisorStatus: vi.fn() })
    apiMock.saveAiKey.mockResolvedValue({ configured: true, source: 'settings', last4: 'wxyz', provider: 'openrouter', advisor_available: true })
    const user = userEvent.setup()
    render(<Settings />)

    expect(await screen.findByText(/Key set from Settings, ending in 3456/)).toBeInTheDocument()
    const input = screen.getByLabelText('New key')
    expect(input).toHaveAttribute('type', 'password')
    await user.type(input, 'sk-or-v1-secretwxyz')
    await user.click(screen.getByRole('button', { name: 'Save key' }))

    expect(apiMock.saveAiKey).toHaveBeenCalledWith('sk-or-v1-secretwxyz')
    expect(await screen.findByText(/ending in wxyz/)).toBeInTheDocument()
    expect(input).toHaveValue('')
    expect(screen.queryByText(/secretwxyz/)).not.toBeInTheDocument()
    expect(screen.getByText(/belongs to your account only/)).toBeInTheDocument()
  })

  it('removes a saved key', async () => {
    const setAdvisorStatus = vi.fn()
    useAppMock.mockReturnValue({ ctx: {}, goTo: vi.fn(), user: ADMIN, setAdvisorStatus })
    const unset = { configured: false, source: 'none', last4: null, provider: 'openrouter', advisor_available: false }
    apiMock.clearAiKey.mockResolvedValue(unset)
    const user = userEvent.setup()
    render(<Settings />)

    await user.click(await screen.findByRole('button', { name: 'Remove saved key' }))
    expect(await screen.findByText(/No key set/)).toBeInTheDocument()
    expect(setAdvisorStatus).toHaveBeenCalledWith(unset)
  })

  it('does not call the admin-only settings endpoint for a non-admin and keeps the key section', async () => {
    useAppMock.mockReturnValue({ ctx: {}, goTo: vi.fn(), user: { email: 'r@x.org', role: 'resident' }, setAdvisorStatus: vi.fn() })
    render(<Settings />)
    expect(await screen.findByText(/Key set from Settings, ending in 3456/)).toBeInTheDocument()
    expect(apiMock.getSettings).not.toHaveBeenCalled()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText('Current Settings')).not.toBeInTheDocument()
    expect(screen.getByLabelText('New key')).toBeInTheDocument()
  })
})
