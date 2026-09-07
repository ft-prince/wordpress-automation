export const site = {
  current: () => localStorage.getItem('dash_site') || '',
  set: (id) => localStorage.setItem('dash_site', id || ''),
}
const sq = (sep = '?') => (site.current() ? `${sep}site=${encodeURIComponent(site.current())}` : '')

export const auth = {
  token: () => localStorage.getItem('dash_token') || '',
  set: (t) => localStorage.setItem('dash_token', t),
  clear: () => localStorage.removeItem('dash_token'),
}

const json = (r) => {
  if (r.status === 401) {
    auth.clear()
    window.dispatchEvent(new Event('auth-required'))
    return Promise.reject(new Error('unauthorized'))
  }
  if (!r.ok) return r.json().then((b) => Promise.reject(new Error(b.detail || r.statusText)))
  return r.json()
}
const headers = () => ({ 'Content-Type': 'application/json', 'X-Auth-Token': auth.token() })
const authedFetch = (url) => fetch(url, { headers: headers() }).then(json)
const send = (url, method, body) =>
  fetch(url, {
    method,
    headers: headers(),
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then(json)

const credCall = (path, username, password) =>
  fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  }).then((r) => (r.ok ? r.json() : r.json().then((b) => Promise.reject(new Error(b.detail || 'failed')))))
    .then((d) => auth.set(d.token))

export const login = (username, password) => credCall('/api/login', username, password)
export const setupAccount = (username, password) => credCall('/api/setup', username, password)
export const authStatus = () => fetch('/api/auth/status').then((r) => r.json())
export const logoutServer = () =>
  fetch('/api/logout', { method: 'POST', headers: { 'X-Auth-Token': auth.token() } }).finally(() => auth.clear())

export const api = {
  // automations
  jobs: () => authedFetch('/api/jobs' + sq()),
  job: (id) => authedFetch(`/api/jobs/${id}`),
  createJob: (body) => send('/api/jobs', 'POST', body),
  patch: (id, body) => send(`/api/jobs/${id}`, 'PATCH', body),
  duplicateJob: (id) => send(`/api/jobs/${id}/duplicate`, 'POST'),
  deleteJob: (id) => send(`/api/jobs/${id}`, 'DELETE'),
  saveSource: (id, body) => send(`/api/jobs/${id}/source`, 'PUT', { body }),
  run: (id, dryRun = false) => send(`/api/jobs/${id}/run`, 'POST', { dry_run: dryRun }),
  stop: (runId) => send(`/api/runs/${runId}/stop`, 'POST'),
  retry: (runId) => send(`/api/runs/${runId}/retry`, 'POST'),
  runs: (params = {}) => authedFetch('/api/runs?' + new URLSearchParams(site.current() ? { ...params, site: site.current() } : params)),
  logs: (runId) => authedFetch(`/api/runs/${runId}/logs`),
  // system
  overview: () => authedFetch('/api/overview' + sq()),
  metrics: () => authedFetch('/api/metrics' + sq()),
  health: () => authedFetch('/api/health' + sq()),
  alerts: () => authedFetch('/api/alerts' + sq()),
  notifications: () => authedFetch('/api/notifications' + sq()),
  pipeline: () => authedFetch('/api/pipeline' + sq()),
  secrets: () => authedFetch('/api/secrets'),
  setSecret: (key, value) => send(`/api/secrets/${key}`, 'PUT', { value }),
  audit: () => authedFetch('/api/audit'),
  // wordpress posts
  posts: (params = {}) => authedFetch('/api/wp/posts?' + new URLSearchParams(site.current() ? { ...params, site: site.current() } : params)),
  post: (id) => authedFetch(`/api/wp/posts/${id}` + sq()),
  createPost: (body) => send('/api/wp/posts' + sq(), 'POST', body),
  updatePost: (id, body) => send(`/api/wp/posts/${id}` + sq(), 'PATCH', body),
  deletePost: (id, force = false) => send(`/api/wp/posts/${id}?force=${force}` + sq('&'), 'DELETE'),
  restorePost: (id) => send(`/api/wp/posts/${id}/restore` + sq(), 'POST'),
  revisions: (id) => authedFetch(`/api/wp/posts/${id}/revisions` + sq()),
  setFeatured: (id, url) => send(`/api/wp/posts/${id}/featured` + sq(), 'POST', { url }),
  terms: () => authedFetch('/api/wp/terms' + sq()),
  createTerm: (kind, name) => send('/api/wp/terms' + sq(), 'POST', { kind, name }),
  bulk: (ids, action, value) => send('/api/wp/posts/bulk' + sq(), 'POST', { ids, action, value }),
  generate: (topic, words = 800) => send('/api/generate', 'POST', { topic, words }),
  sites: () => authedFetch('/api/sites'),
  // content: profile / briefs / changes
  profile: () => authedFetch('/api/profile' + sq()),
  saveProfile: (body) => send('/api/profile' + sq(), 'PUT', body),
  draftProfile: () => send('/api/profile/draft' + sq(), 'POST'),
  changes: (status) => authedFetch('/api/changes?' + new URLSearchParams({ ...(status ? { status } : {}), ...(site.current() ? { site: site.current() } : {}) })),
  changeAction: (id, action) => send(`/api/changes/${id}/${action}`, 'POST'),
  briefs: () => authedFetch('/api/briefs' + sq()),
  brief: (id) => authedFetch(`/api/briefs/${id}`),
  createBrief: (body) => send('/api/briefs' + sq(), 'POST', body),
  patchBrief: (id, body) => send(`/api/briefs/${id}`, 'PATCH', body),
  briefAction: (id, action, body) => send(`/api/briefs/${id}/${action}` + sq(), 'POST', body),
  // keywords
  keywords: () => authedFetch('/api/keywords' + sq()),
  addKeyword: (text) => send('/api/keywords' + sq(), 'POST', { text }),
  keywordRun: (step) => send(`/api/keywords/${step}` + sq(), 'POST'),
  keywordMove: (id, cluster_id) => send(`/api/keywords/${id}/move`, 'POST', { cluster_id }),
  keywordPrimary: (id) => send(`/api/keywords/${id}/primary`, 'POST'),
  deleteKeyword: (id) => send(`/api/keywords/${id}`, 'DELETE'),
  cannibalization: () => authedFetch('/api/keywords/cannibalization' + sq()),
  gaps: () => authedFetch('/api/keywords/gaps' + sq()),
  patchCluster: (id, body) => send(`/api/clusters/${id}`, 'PATCH', body),
  mergeCluster: (id, from_id) => send(`/api/clusters/${id}/merge`, 'POST', { from_id }),
  splitCluster: (id, keyword_ids, name) => send(`/api/clusters/${id}/split`, 'POST', { keyword_ids, name }),
  deleteCluster: (id) => send(`/api/clusters/${id}`, 'DELETE'),
  // google + insights
  googleStatus: () => authedFetch('/api/google/status' + sq()),
  googleAuthUrl: () => authedFetch('/api/google/auth-url'),
  googleDisconnect: () => send('/api/google/disconnect', 'POST'),
  googleProperties: () => authedFetch('/api/google/properties'),
  googleSync: () => send('/api/google/sync' + sq(), 'POST'),
  siteSettings: (id, body) => send(`/api/sites/${id}/settings`, 'PATCH', body),
  insights: () => authedFetch('/api/insights' + sq()),
  adoptKeywords: () => send('/api/insights/adopt-keywords' + sq(), 'POST'),
  // seo
  technicalSeo: () => authedFetch('/api/seo/technical' + sq()),
  startCrawl: () => send('/api/seo/crawl' + sq(), 'POST'),
  seoPage: (id) => authedFetch(`/api/seo/pages/${id}` + sq()),
  suggestOnpage: (id) => send(`/api/seo/pages/${id}/suggest` + sq(), 'POST'),
  applyOnpage: (id, field, value) => send(`/api/seo/pages/${id}/apply` + sq(), 'POST', { field, value }),
  addSite: (body) => send('/api/sites', 'POST', body),
  testSite: (body) => send('/api/sites/test', 'POST', body),
  removeSite: (id) => send(`/api/sites/${id}`, 'DELETE'),
}

// Live tail by polling the log cursor. Same contract as the old WebSocket helper.
export const liveLog = (runId, onLine, onDone) => {
  let cursor = 0
  let stopped = false
  const tick = () =>
    authedFetch(`/api/runs/${runId}/logs?after=${cursor}`)
      .then((d) => {
        if (stopped) return
        d.lines.forEach((l) => { cursor = l.id; onLine(l) })
        if (d.done) { onDone?.(d.status); stopped = true }
      })
      .catch(() => {})
  tick()
  const t = setInterval(() => { if (!stopped) tick(); else clearInterval(t) }, 700)
  return () => { stopped = true; clearInterval(t) }
}
