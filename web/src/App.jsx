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
import { api } from './api'

export const AppCtx = createContext(null)
export const useApp = () => useContext(AppCtx)

const SCREENS = [
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

const STEP_LABELS = {
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

function Progress({ screen }) {
  if (screen === 'landing' || screen === 'settings') return null
  return (
    <nav className="max-w-5xl mx-auto px-4 pt-4" aria-label="Wizard progress">
      <ol className="flex flex-wrap gap-2 text-xs text-gray-600">
        {SCREENS.filter(s => s !== 'landing').map(step => (
          <li key={step} aria-current={screen === step ? 'step' : undefined} className={`px-2 py-1 rounded ${screen === step ? 'bg-blue-700 text-white' : 'bg-white border'}`}>
            {STEP_LABELS[step]}
          </li>
        ))}
      </ol>
    </nav>
  )
}

export default function App() {
  const [screen, setScreen] = useState('landing')
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

  function applyResume(resume, requestedScreen, replaceHistory = false) {
    const nextCtx = ctxFromResume(resume)
    const fallbackScreen = ROUTE_SCREENS.has(resume.current_screen) ? resume.current_screen : 'description'
    const targetScreen = ROUTE_SCREENS.has(requestedScreen) ? requestedScreen : fallbackScreen
    setCtx(c => ({ ...c, ...nextCtx }))
    setScreen(targetScreen)
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
    setScreen(s)
    if (ctx.projectId && ROUTE_SCREENS.has(s)) {
      window.history.pushState({}, '', `/app/${ctx.projectId}/${s}`)
      window.localStorage.setItem('qiss:lastProjectId', String(ctx.projectId))
    }
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
    return <div className="min-h-screen p-8 text-center text-gray-600" aria-live="polite">Checking session…</div>
  }

  if (!user) {
    return <Auth onAuthenticated={setUser} />
  }


  const Screen = COMPONENTS[screen] || Landing

  return (
    <AppCtx.Provider value={{ ctx, update, next, prev, goTo, screen, user, logout, resumeProject }}>
      <div className="min-h-screen bg-gray-50">
        <Progress screen={screen} />
        {hydrating && (
          <div className="p-3 text-center text-sm text-gray-600" aria-live="polite">
            Restoring project…
          </div>
        )}
        {screen !== 'landing' && (
          <button
            type="button"
            onClick={() => goTo('settings')}
            className="fixed top-3 right-4 text-gray-500 hover:text-gray-800 text-xl z-10"
            title="Settings"
            aria-label="Open settings"
            disabled={hydrating}
          >
            ⚙
          </button>
        )}
        <main ref={headingScopeRef} aria-busy={hydrating} className={hydrating ? 'pointer-events-none opacity-60' : ''}>
          <Screen />
        </main>
      </div>
    </AppCtx.Provider>
  )
}
