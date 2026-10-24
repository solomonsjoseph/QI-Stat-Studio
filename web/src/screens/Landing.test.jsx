import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Landing from './Landing'

const { apiMock, useAppMock } = vi.hoisted(() => ({
  apiMock: {
    listProjects: vi.fn(),
    createProject: vi.fn(),
    deleteProject: vi.fn(),
  },
  useAppMock: vi.fn(),
}))

vi.mock('../api', () => ({ api: apiMock }))
vi.mock('../App', () => ({ useApp: useAppMock }))

function renderLanding(overrides = {}) {
  const goTo = overrides.goTo ?? vi.fn()
  const update = overrides.update ?? vi.fn()
  const resetProject = overrides.resetProject ?? vi.fn()
  const resumeProject = overrides.resumeProject ?? vi.fn()
  useAppMock.mockReturnValue({
    goTo,
    update,
    resetProject,
    resumeProject,
    user: { email: 'resident@example.test' },
  })
  render(<Landing />)
  return { goTo, update, resetProject, resumeProject }
}

beforeEach(() => {
  apiMock.listProjects.mockReset()
  apiMock.createProject.mockReset()
  apiMock.deleteProject.mockReset()
  apiMock.listProjects.mockResolvedValue([])
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('Landing start new project', () => {
  it('clears stale context and routes straight to the unified intake screen without pre-creating a project', async () => {
    const user = userEvent.setup()
    const { update, resetProject, goTo } = renderLanding()

    await user.click(await screen.findByRole('button', { name: 'Start New Project' }))

    // A prior project's template/params/columnMap must not survive into the new
    // project: resetProject fully replaces ctx (setCtx(patch)). The project itself
    // is created inside the unified intake screen once title+file+dictionary are
    // submitted together, so no createProject call happens here.
    expect(resetProject).toHaveBeenCalledWith({})
    expect(resetProject).toHaveBeenCalledTimes(1)
    expect(apiMock.createProject).not.toHaveBeenCalled()
    expect(update).not.toHaveBeenCalled()
    expect(goTo).toHaveBeenCalledWith('description')
  })
})
