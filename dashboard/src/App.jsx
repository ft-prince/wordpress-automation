import { useCallback, useEffect, useState } from 'react'
import { api, auth, authStatus, login, logoutServer, setupAccount, site } from './api'
import Overview from './components/Overview'
import Posts from './components/Posts'
import Jobs from './components/Jobs'
import JobDetail from './components/JobDetail'
import Schedule from './components/Schedule'
import Logs from './components/Logs'
import Health from './components/Health'
import Seo from './components/Seo'
import Sites from './components/Sites'
import ThemeFiles from './components/ThemeFiles'
import Topics from './components/Topics'
import { Secrets, Audit } from './components/SecretsAudit'

const NAV = [
  ['overview', 'Overview', 'M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10'],
  ['topics', 'Topics', 'M9 18h6M10 21h4M12 3a6 6 0 00-4 10c1 1 1 2 1 3h6c0-1 0-2 1-3a6 6 0 00-4-10z'],
  ['posts', 'Posts', 'M5 4h14v16H5zM8 8h8M8 12h8M8 16h5'],
  ['automations', 'Automations', 'M12 3v3m0 12v3M3 12h3m12 0h3M6 6l2 2m8 8 2 2M6 18l2-2m8-8 2-2M12 9a3 3 0 100 6 3 3 0 000-6z'],
  ['schedule', 'Schedule', 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4'],
  ['logs', 'Logs', 'M4 5h16M4 10h10M4 15h16M4 20h7'],
  ['seo', 'SEO', 'M10 10m-6 0a6 6 0 1112 0 6 6 0 11-12 0M14.5 14.5L21 21M8 10h4M10 8v4'],
  ['theme', 'Theme', 'M8 3v6a4 4 0 008 0V3M6 3h12M12 13v8M9 21h6'],
  ['sites', 'Sites', 'M12 3a9 9 0 100 18 9 9 0 000-18zM3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18'],
  ['health', 'Health', 'M3 12h4l2-6 4 12 2-6h6'],
  ['secrets', 'Secrets', 'M8 11V7a4 4 0 118 0v4M5 11h14v9H5z'],
  ['audit', 'Audit', 'M9 5h9v14H9zM6 5v14M9 9h9M9 13h9'],
]

function SiteSwitcher({ version, onChange }) {
  const [data, setData] = useState(null)
  useEffect(() => { api.sites().then(setData).catch(() => {}) }, [version])
  if (!data || data.sites.length === 0) return null
  const active = site.current() || data.default
  return (
    <select
      value={active}
      onChange={(e) => { site.set(e.target.value); onChange() }}
      aria-label="Active WordPress site"
      className="rounded-lg border border-edge bg-panel px-2.5 py-1.5 text-sm outline-none focus:border-accent"
    >
      {data.sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
    </select>
  )
}

function Bell({ onNavigate, version }) {
  const [items, setItems] = useState([])
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const load = () => api.notifications().then(setItems).catch(() => {})
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [version])
  const urgent = items.filter((i) => ['critical', 'error', 'warn', 'approval'].includes(i.level)).length
  const tone = { critical: 'var(--color-bad)', error: 'var(--color-bad)', warn: 'var(--color-accent)', approval: 'var(--color-accent)', success: 'var(--color-ok)' }
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} aria-label={`Notifications (${urgent} need attention)`} className="relative rounded-lg border border-edge p-2 hover:border-accent">
        <svg viewBox="0 0 24 24" className="h-4 w-4"><path d="M6 9a6 6 0 1112 0c0 5 2 6 2 6H4s2-1 2-6zM10 19a2 2 0 004 0" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" /></svg>
        {urgent > 0 && (
          <span className="absolute -right-1.5 -top-1.5 flex h-4.5 min-w-4.5 items-center justify-center rounded-full px-1 text-[10px] font-bold text-black" style={{ background: 'var(--color-accent)' }}>
            {urgent}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 top-11 z-50 w-96 rounded-xl border border-edge bg-panel p-2 shadow-2xl">
          <h3 className="px-2 py-1.5 text-xs uppercase tracking-widest text-dim">Notifications</h3>
          {items.length === 0 ? (
            <p className="px-2 py-4 text-sm text-dim">You're all caught up.</p>
          ) : (
            <ul className="max-h-96 overflow-y-auto">
              {items.map((n, i) => (
                <li key={i} className="rounded-lg px-2 py-2 text-sm hover:bg-edge/30">
                  <span className="mr-2 text-[10px] uppercase mono" style={{ color: tone[n.level] || 'var(--color-dim)' }}>{n.level}</span>
                  {n.text}
                  {n.ts && <div className="mt-0.5 text-xs text-dim mono">{new Date(/Z|[+-]\d\d:\d\d$/.test(n.ts) ? n.ts : n.ts + 'Z').toLocaleString()}</div>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function Login({ onDone }) {
  const [mode, setMode] = useState(null) // null=loading, 'setup', 'login'
  const [user, setUser] = useState('')
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    authStatus().then((s) => setMode(s.needs_setup ? 'setup' : 'login')).catch(() => setMode('login'))
  }, [])

  const submit = (e) => {
    e.preventDefault()
    if (mode === 'setup') {
      if (pw.length < 8) return setErr('Password must be at least 8 characters')
      if (pw !== pw2) return setErr('Passwords do not match')
    }
    setBusy(true)
    const req = mode === 'setup' ? setupAccount(user, pw) : login(user, pw)
    req.then(onDone).catch((e2) => setErr(e2.message)).finally(() => setBusy(false))
  }

  const input = 'mt-1 w-full rounded-lg border border-edge bg-base px-3 py-2 text-sm outline-none focus:border-accent'
  if (mode === null) return null

  return (
    <div className="flex min-h-screen items-center justify-center">
      <form onSubmit={submit} className="w-80 rounded-xl border border-edge bg-panel p-6">
        <h1 className="text-lg font-bold">automation<span className="text-accent">.</span></h1>
        <p className="mt-1 text-sm text-dim">
          {mode === 'setup' ? 'Welcome! Create your login to get started' : 'Sign in to continue'}
        </p>
        <label className="mt-4 block text-sm text-dim">Username
          <input autoFocus value={user} onChange={(e) => { setUser(e.target.value); setErr('') }}
            className={input} autoComplete="username" />
        </label>
        <label className="mt-3 block text-sm text-dim">Password
          <input type="password" value={pw} onChange={(e) => { setPw(e.target.value); setErr('') }}
            className={input} autoComplete={mode === 'setup' ? 'new-password' : 'current-password'} />
        </label>
        {mode === 'setup' && (
          <label className="mt-3 block text-sm text-dim">Confirm password
            <input type="password" value={pw2} onChange={(e) => { setPw2(e.target.value); setErr('') }}
              className={input} autoComplete="new-password" />
          </label>
        )}
        {err && <p className="mt-2 text-sm" style={{ color: 'var(--color-bad)' }}>{err}</p>}
        <button type="submit" disabled={!user || !pw || busy}
          className="mt-4 w-full rounded-lg bg-accent px-4 py-2 text-sm font-medium text-black disabled:opacity-40">
          {busy ? 'Working…' : mode === 'setup' ? 'Create account' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}

const PAGES = ['overview', 'topics', 'posts', 'automations', 'schedule', 'logs', 'seo', 'theme', 'sites', 'health', 'secrets', 'audit']

function pathToState() {
  const parts = window.location.pathname.split('/').filter(Boolean)
  if (parts[0] === 'automations' && parts[1]) return { page: 'job', jobId: parts[1] }
  if (parts[0] === 'posts' && parts[1]) return { page: 'posts', jobId: parts[1] }
  if (PAGES.includes(parts[0])) return { page: parts[0], jobId: null }
  return { page: 'overview', jobId: null }
}

function stateToPath(page, jobId) {
  if (page === 'job' && jobId) return `/automations/${jobId}`
  if (page === 'posts' && jobId) return `/posts/${jobId}`
  return page === 'overview' ? '/overview' : `/${page}`
}

export default function App() {
  const initial = pathToState()
  const [page, setPage] = useState(initial.page)
  const [jobId, setJobId] = useState(initial.jobId)
  const [toasts, setToasts] = useState([])
  const [authed, setAuthed] = useState(() => Boolean(auth.token()))

  useEffect(() => {
    const onExpired = () => setAuthed(false)
    window.addEventListener('auth-required', onExpired)
    return () => window.removeEventListener('auth-required', onExpired)
  }, [])

  const notify = useCallback((message, isError = false) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, message, isError }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000)
  }, [])

  const [siteVersion, setSiteVersion] = useState(0)
  const onSiteChange = () => setSiteVersion((v) => v + 1)

  const navigate = (p, id = null) => {
    const nextPage = id && p === 'automations' ? 'job' : p
    setJobId(id)
    setPage(nextPage)
    const path = stateToPath(nextPage, id)
    if (window.location.pathname !== path) window.history.pushState({}, '', path)
  }

  useEffect(() => {
    const onPop = () => { const s = pathToState(); setPage(s.page); setJobId(s.jobId) }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); navigate('posts') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!authed) return <Login onDone={() => setAuthed(true)} />

  return (
    <div className="flex min-h-screen">
      {/* sidebar */}
      <aside className="sticky top-0 flex h-screen w-52 shrink-0 flex-col border-r border-edge bg-panel/50 max-md:w-14">
        <div className="px-4 py-5 max-md:px-3">
          <h1 className="text-lg font-bold tracking-tight max-md:hidden">automation<span className="text-accent">.</span></h1>
          <span className="hidden text-lg font-bold max-md:block">a<span className="text-accent">.</span></span>
        </div>
        <nav className="flex flex-col gap-0.5 px-2" aria-label="Main">
          {NAV.map(([key, label, d]) => (
            <button key={key} onClick={() => navigate(key)}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors duration-200 max-md:justify-center max-md:px-2 ${
                page === key || (page === 'job' && key === 'automations') ? 'bg-edge text-ink' : 'text-dim hover:text-ink'}`}
              title={label}>
              <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0"><path d={d} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
              <span className="max-md:hidden">{label}</span>
            </button>
          ))}
        </nav>
        <div className="mt-auto px-2 pb-4">
          <button onClick={() => logoutServer().then(() => setAuthed(false))}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-dim hover:text-ink max-md:justify-center max-md:px-2" title="Log out">
            <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0"><path d="M15 4h5v16h-5M10 17l5-5-5-5M15 12H3" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
            <span className="max-md:hidden">Log out</span>
          </button>
          <div className="px-3 pt-2 text-xs text-dim mono max-md:hidden">⌘K posts</div>
        </div>
      </aside>

      {/* main */}
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 border-b border-edge bg-base/90 backdrop-blur">
          <div className="flex items-center gap-4 px-6 py-3">
            <h2 className="text-base font-bold capitalize">{page === 'job' ? 'Automation detail' : page}</h2>
            <div className="ml-auto flex items-center gap-3">
              <SiteSwitcher version={siteVersion} onChange={onSiteChange} />
              <Bell onNavigate={navigate} version={siteVersion} />
            </div>
          </div>
        </header>
        <main className="p-6" key={siteVersion}>
          {page === 'overview' && <Overview onNavigate={navigate} notify={notify} />}
          {page === 'topics' && <Topics notify={notify} />}
          {page === 'posts' && <Posts notify={notify} initialEdit={jobId} />}
          {page === 'automations' && <Jobs onOpenJob={(id) => navigate('automations', id)} notify={notify} />}
          {page === 'job' && jobId && <JobDetail jobId={jobId} onBack={() => navigate('automations')} notify={notify} />}
          {page === 'schedule' && <Schedule notify={notify} />}
          {page === 'logs' && <Logs notify={notify} />}
          {page === 'seo' && <Seo notify={notify} onNavigate={navigate} />}
          {page === 'theme' && <ThemeFiles notify={notify} />}
          {page === 'sites' && <Sites notify={notify} onSiteChange={onSiteChange} />}
          {page === 'health' && <Health />}
          {page === 'secrets' && <Secrets notify={notify} />}
          {page === 'audit' && <Audit />}
        </main>
      </div>

      <div className="fixed bottom-4 right-4 z-50 space-y-2" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="log-line rounded-lg border px-4 py-2.5 text-sm shadow-lg"
            style={{ background: 'var(--color-panel)', borderColor: t.isError ? 'var(--color-bad)' : 'var(--color-edge)', color: t.isError ? 'var(--color-bad)' : 'var(--color-ink)' }}>
            {t.message}
          </div>
        ))}
      </div>
    </div>
  )
}
