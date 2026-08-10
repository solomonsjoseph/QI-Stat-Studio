import React, { createContext, useContext, useState, useEffect, useRef } from 'react'
import Auth from './screens/Auth'
import Landing from './screens/Landing'
import ProjectDescription from './screens/ProjectDescription'
import IntakeQuestions from './screens/IntakeQuestions'
import Upload from './screens/Upload'
import DataReview from './screens/DataReview'
import AnalysisSelection from './screens/AnalysisSelection'
import ParameterSelection from './screens/ParameterSelection'
import Results from './screens/Results'
import EditReview from './screens/EditReview'
import DownloadShare from './screens/DownloadShare'
import Settings from './screens/Settings'
import MentorView from './screens/MentorView'
import Spinner from './components/Spinner'
import { api } from './api'

export const AppCtx = createContext(null)
export const useApp = () => useContext(AppCtx)

export const SCREENS = [
  'landing', 'description', 'intake', 'upload', 'review',
  'analysis', 'params', 'results', 'edit', 'download',
]

const ROUTE_SCREENS = new Set([...SCREENS, 'settings'])

const COMPONENTS = {
  landing: Landing,
  description: ProjectDescription,
  intake: IntakeQuestions,
  upload: Upload,
  review: DataReview,
  analysis: AnalysisSelection,
  params: ParameterSelection,
  results: Results,
  edit: EditReview,
  download: DownloadShare,
  settings: Settings,
}

export const STEP_LABELS = {
  description: 'Description',
  intake: 'Intake',
  upload: 'Upload',
  review: 'Review',
  analysis: 'Analysis',
  params: 'Parameters',
  results: 'Results',
  edit: 'Edits',
  download: 'Download',
}

function routeFromPath() {
  const match = window.location.pathname.match(/^\/app\/(\d+)\/([^/]+)$/)
  if (!match) return null
  const projectId = Number(match[1])
  const screen = ROUTE_SCREENS.has(match[2]) ? match[2] : null
  return projectId ? { projectId, screen } : null
}

function ctxFromResume(resume) {
  const latestUpload = resume.latest_upload
  const latestRun = resume.latest_run
  const latestShare = resume.latest_share
  return {
    projectId: resume.project.id,
    projectTitle: resume.project.title,
    projectDesc: resume.project.description || '',
    answers: resume.answers || {},
    uploadId: latestUpload?.id,
    colTypes: latestUpload?.col_types || {},
    columnMap: latestUpload?.column_map || {},
    qualityFlags: latestUpload?.quality_flags || [],
    acknowledgedFlags: latestUpload?.acknowledged_flags || [],
    runId: latestRun?.id,
    template: latestRun?.template,
    params: latestRun?.parameters || {},
    results: latestRun?.result || {},
    resultSummary: latestRun?.result?.result_summary,
    aiInterpretation: latestRun?.result?.interpretation || '',
    shareToken: latestShare?.token,
  }
}

function CheckIcon() {
  return (
    <svg className="h-3 w-3" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M13.25 4.75 6.75 11.25 3.5 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function GearIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" stroke="currentColor" strokeWidth="1.8" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.36a1.7 1.7 0 0 0-1 .6V20a2 2 0 0 1-4 0v-.08a1.7 1.7 0 0 0-1-.6 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.64 15a1.7 1.7 0 0 0-.6-1H4a2 2 0 0 1 0-4h.08a1.7 1.7 0 0 0 .6-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.64a1.7 1.7 0 0 0 1-.6V4a2 2 0 0 1 4 0v.08a1.7 1.7 0 0 0 1 .6 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.36 9c.22.35.43.7.6 1H20a2 2 0 0 1 0 4h-.08a1.7 1.7 0 0 0-.52 1Z" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Progress({ screen, maxStepIdx, goTo, hydrating }) {
  if (screen === 'landing' || screen === 'settings') return null
  const steps = SCREENS.filter(s => s !== 'landing')
  return (
    <nav className="border-b border-line bg-surface" aria-label="Wizard progress">
      <div className="mx-auto max-w-5xl overflow-x-auto px-6 py-3">
        <ol className="flex min-w-max items-center text-xs text-ink-soft">
          {steps.map((step, i) => {
            const stepIdx = SCREENS.indexOf(step)
            const isCurrent = screen === step
            const isComplete = stepIdx < SCREENS.indexOf(screen)
            const enabled = stepIdx <= maxStepIdx && !hydrating
            return (
              <li key={step} className="flex items-center">
                {i > 0 && <span className="mx-3 h-px w-8 bg-line" aria-hidden="true" />}
                <button
                  type="button"
                  onClick={() => goTo(step)}
                  disabled={!enabled}
                  aria-current={isCurrent ? 'step' : undefined}
                  className={`group inline-flex items-center gap-2 whitespace-nowrap transition disabled:cursor-not-allowed ${isCurrent ? 'text-ink font-medium' : enabled ? 'text-ink-soft hover:text-ink' : 'text-ink-faint'}`}
                >
                  <span className={`flex h-5 w-5 items-center justify-center rounded-md border text-[11px] ${isCurrent ? 'border-brand bg-brand text-white' : isComplete ? 'border-line text-ink-soft group-hover:border-brand-ring' : 'border-line bg-canvas text-ink-faint'}`}>
                    {isComplete ? <CheckIcon /> : stepIdx}
                  </span>
                  <span>{STEP_LABELS[step]}</span>
                </button>
              </li>
            )
          })}
        </ol>
      </div>
    </nav>
  )
}

export default function App() {
  const [screen, setScreen] = useState('landing')
  const [maxStepIdx, setMaxStepIdx] = useState(0)
  const [ctx, setCtx] = useState({})
  const [user, setUser] = useState(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [hydrating, setHydrating] = useState(false)
  const headingScopeRef = useRef(null)

  const path = window.location.pathname
  const isMentor = path.startsWith('/mentor/')

  const update = (patch) => setCtx(c => {
    const nextCtx = { ...c, ...patch }
    if (nextCtx.projectId) window.localStorage.setItem('qiss:lastProjectId', String(nextCtx.projectId))
    return nextCtx
  })

  const showScreen = (s) => {
    setScreen(s)
    const i = SCREENS.indexOf(s)
    if (i >= 0) setMaxStepIdx(m => Math.max(m, i))
  }

  function applyResume(resume, requestedScreen, replaceHistory = false) {
    const nextCtx = ctxFromResume(resume)
    const fallbackScreen = ROUTE_SCREENS.has(resume.current_screen) ? resume.current_screen : 'description'
    const targetScreen = ROUTE_SCREENS.has(requestedScreen) ? requestedScreen : fallbackScreen
    setCtx(nextCtx)
    const serverIdx = SCREENS.indexOf(resume.current_screen)
    const targetIdx = SCREENS.indexOf(targetScreen)
    setMaxStepIdx(Math.max(serverIdx >= 0 ? serverIdx : 0, targetIdx >= 0 ? targetIdx : 0))
    showScreen(targetScreen)
    window.localStorage.setItem('qiss:lastProjectId', String(nextCtx.projectId))
    const targetPath = `/app/${nextCtx.projectId}/${targetScreen}`
    if (window.location.pathname !== targetPath) {
      const method = replaceHistory ? 'replaceState' : 'pushState'
      window.history[method]({}, '', targetPath)
    }
  }

  const resumeProject = async (projectId, requestedScreen, options = {}) => {
    setHydrating(true)
    try {
      const resume = await api.resumeProject(projectId)
      applyResume(resume, requestedScreen, options.replaceHistory)
      return resume
    } finally {
      setHydrating(false)
    }
  }

  const goTo = (s) => {
    if (s === 'settings') {
      setCtx(c => ({ ...c, previousScreen: screen === 'settings' ? c.previousScreen : screen }))
    }
    showScreen(s)
    if (ctx.projectId && ROUTE_SCREENS.has(s)) {
      window.history.pushState({}, '', `/app/${ctx.projectId}/${s}`)
      window.localStorage.setItem('qiss:lastProjectId', String(ctx.projectId))
    }
  }
  const resetProject = (patch) => {
    setCtx(patch)
    setMaxStepIdx(0)
    if (patch.projectId) window.localStorage.setItem('qiss:lastProjectId', String(patch.projectId))
  }
  const next = () => {
    const idx = SCREENS.indexOf(screen)
    if (idx < SCREENS.length - 1) goTo(SCREENS[idx + 1])
  }
  const prev = () => {
    const idx = SCREENS.indexOf(screen)
    if (idx > 0) goTo(SCREENS[idx - 1])
  }
  const logout = async () => {
    await api.logout().catch(() => null)
    window.localStorage.removeItem('qiss:lastProjectId')
    setCtx({})
    setMaxStepIdx(0)
    setScreen('landing')
    setUser(null)
  }

  useEffect(() => {
    if (isMentor) return
    let cancelled = false
    api.me()
      .then(currentUser => {
        if (!cancelled) setUser(currentUser)
      })
      .catch(() => {
        if (!cancelled) setUser(null)
      })
      .finally(() => {
        if (!cancelled) setAuthChecked(true)
      })
    return () => { cancelled = true }
  }, [isMentor])

  useEffect(() => {
    if (isMentor || !authChecked || !user) return
    const route = routeFromPath()
    const storedProjectId = window.localStorage.getItem('qiss:lastProjectId')
    const projectId = route?.projectId || (storedProjectId ? Number(storedProjectId) : null)
    if (!projectId) return

    let cancelled = false
    setHydrating(true)
    api.resumeProject(projectId)
      .then(resume => {
        if (cancelled) return
        applyResume(resume, route?.screen, true)
      })
      .catch(() => {
        if (!cancelled) window.localStorage.removeItem('qiss:lastProjectId')
      })
      .finally(() => {
        if (!cancelled) setHydrating(false)
      })
    return () => { cancelled = true }
  }, [isMentor, authChecked, user])

  useEffect(() => {
    if (isMentor || !ctx.projectId || screen === 'landing' || !ROUTE_SCREENS.has(screen)) return
    const targetPath = `/app/${ctx.projectId}/${screen}`
    if (window.location.pathname !== targetPath) {
      window.history.replaceState({}, '', targetPath)
    }
    window.localStorage.setItem('qiss:lastProjectId', String(ctx.projectId))
  }, [ctx.projectId, screen, isMentor])

  useEffect(() => {
    if (isMentor) return
    const onPop = () => {
      const route = routeFromPath()
      if (!route) {
        setScreen('landing')
        return
      }
      if (route.projectId === ctx.projectId) {
        if (route.screen) showScreen(route.screen)
      } else {
        resumeProject(route.projectId, route.screen, { replaceHistory: true }).catch(() => setScreen('landing'))
      }
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [isMentor, ctx.projectId])

  useEffect(() => {
    const heading = headingScopeRef.current?.querySelector('h1, h2')
    if (heading) {
      if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1')
      heading.focus()
    }
  }, [screen])

  if (isMentor) {
    const token = path.split('/mentor/')[1]
    return <MentorView token={token} />
  }

  if (!authChecked) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2 text-sm text-ink-soft" aria-live="polite">
        <Spinner />
        Checking session…
      </div>
    )
  }

  if (!user) {
    return <Auth onAuthenticated={setUser} />
  }

  const Screen = COMPONENTS[screen] || Landing

  return (
    <AppCtx.Provider value={{ ctx, update, next, prev, goTo, screen, user, logout, resumeProject, resetProject }}>
      <div className="min-h-screen bg-canvas">
        <header className="sticky top-0 z-10 border-b border-line bg-surface/95 backdrop-blur-sm">
          <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-6">
            <button type="button" onClick={() => goTo('landing')} className="text-sm font-semibold tracking-tight text-ink">
              QI Stat Studio
            </button>
            <div className="flex items-center gap-3 text-sm text-ink-soft">
              <span className="hidden sm:inline">{user.email}</span>
              <button type="button" onClick={() => goTo('settings')} disabled={hydrating} aria-label="Open settings" className="btn-secondary px-3 py-2">
                <GearIcon />
              </button>
              <button type="button" onClick={logout} className="btn-secondary px-3 py-2">
                Sign out
              </button>
            </div>
          </div>
        </header>
        <Progress screen={screen} maxStepIdx={maxStepIdx} goTo={goTo} hydrating={hydrating} />
        {hydrating && (
          <div className="flex items-center justify-center gap-2 px-6 py-3 text-sm text-ink-soft" aria-live="polite">
            <Spinner />
            Restoring project…
          </div>
        )}
        <main ref={headingScopeRef} aria-busy={hydrating} className={hydrating ? 'pointer-events-none opacity-60' : ''}>
          <Screen />
        </main>
      </div>
    </AppCtx.Provider>
  )
}
