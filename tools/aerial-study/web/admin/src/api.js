export async function api(path, options = {}) {
  const init = { ...options, headers: { ...(options.headers || {}) } }
  if (init.body && !(init.body instanceof FormData)) {
    init.headers['Content-Type'] = 'application/json'
    if (typeof init.body !== 'string') init.body = JSON.stringify(init.body)
  }
  const response = await fetch(path, init)
  if (response.status === 401) { window.location.href = '/admin/login'; throw new Error('login required') }
  let data = null
  try { data = await response.json() } catch (_) {}
  if (!response.ok) throw new Error((data && (data.detail || data.error)) || `HTTP ${response.status}`)
  return data
}
