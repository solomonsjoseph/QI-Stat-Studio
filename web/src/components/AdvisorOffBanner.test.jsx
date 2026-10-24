import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AdvisorOffBanner from './AdvisorOffBanner'

const { useAppMock } = vi.hoisted(() => ({ useAppMock: vi.fn() }))
vi.mock('../App', () => ({ useApp: useAppMock }))

afterEach(() => cleanup())

describe('AdvisorOffBanner', () => {
  it('links to Settings when the advisor is off', async () => {
    const goTo = vi.fn()
    useAppMock.mockReturnValue({ advisorOff: true, goTo })
    render(<AdvisorOffBanner />)
    await userEvent.click(screen.getByRole('button', { name: /Settings/ }))
    expect(goTo).toHaveBeenCalledWith('settings')
  })

  it('renders nothing when the advisor is available', () => {
    useAppMock.mockReturnValue({ advisorOff: false, goTo: vi.fn() })
    const { container } = render(<AdvisorOffBanner />)
    expect(container).toBeEmptyDOMElement()
  })
})
