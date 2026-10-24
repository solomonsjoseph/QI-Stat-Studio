import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ModelPicker from './ModelPicker'

const { apiMock } = vi.hoisted(() => ({ apiMock: { getAiModels: vi.fn(), saveAiModel: vi.fn(), clearAiModel: vi.fn() } }))
vi.mock('../api', () => ({ api: apiMock }))

const LIST = {
  provider: 'openrouter', current_model: 'v/old', chosen_by: 'default', current_listed: false, source: 'live',
  models: [
    { id: 'v/new', name: 'Vendor: New', prompt_price_per_million: 3 },
    { id: 'v/other', name: 'Vendor: Other' },
  ],
}

beforeEach(() => {
  apiMock.getAiModels.mockReset().mockResolvedValue(LIST)
  apiMock.saveAiModel.mockReset().mockResolvedValue({ provider: 'openrouter', current_model: 'v/new', chosen_by: 'you' })
  apiMock.clearAiModel.mockReset().mockResolvedValue({ provider: 'openrouter', current_model: 'v/old', chosen_by: 'default' })
})
afterEach(cleanup)

describe('ModelPicker', () => {
  it('lists the models the provider returned, flags a model the provider no longer lists, and saves a choice', async () => {
    const user = userEvent.setup()
    render(<ModelPicker refreshKey={0} />)

    expect(await screen.findByText(/no longer lists this model/i)).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Vendor: New \(v\/new\)/ })).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText(/^Model/), 'v/new')
    await user.click(screen.getByRole('button', { name: 'Use this model' }))

    expect(apiMock.saveAiModel).toHaveBeenCalledWith('v/new')
    expect(await screen.findByText('Saved')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Use the default' })).toBeInTheDocument()
  })

  it('shows the provider problem with a way to retry and fetches fresh on Refresh', async () => {
    apiMock.getAiModels.mockRejectedValueOnce(Object.assign(new Error('The provider rejected your AI key, so the model list could not be loaded. Check the key in Settings.'), { requestId: 'req-9' }))
    const user = userEvent.setup()
    render(<ModelPicker refreshKey={0} />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('rejected your AI key')
    expect(alert).toHaveTextContent('Request ID: req-9')
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(apiMock.getAiModels).toHaveBeenLastCalledWith(true)
    expect(await screen.findByText(/Current model:/)).toBeInTheDocument()
  })

  it('filters the list by what the resident types', async () => {
    const user = userEvent.setup()
    render(<ModelPicker refreshKey={0} />)
    await screen.findByLabelText('Filter models')
    await user.type(screen.getByLabelText('Filter models'), 'other')
    expect(screen.queryByRole('option', { name: /Vendor: New/ })).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Vendor: Other/ })).toBeInTheDocument()
  })
})
