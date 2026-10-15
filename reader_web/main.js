// foliate-js wrapper: exposes a small API to Python over QWebChannel.
import './foliate-js/view.js'

const view = document.createElement('foliate-view')
view.id = 'view'
document.body.append(view)

let bridge = null

// --- reading style (applied to the book's section documents) ----------------
let currentTheme = 'light'
let currentZoom = 16
let currentFont = 'serif'
let currentLine = 1.5

function themeCss(mode) {
  if (mode === 'dark') {
    return 'html, body { background: #1f2227; color: #e8eaed; }'
      + ' img, video, svg { filter: invert(1) hue-rotate(180deg); }'
  }
  if (mode === 'sepia') {
    return 'html, body { background: #f4ecd8; color: #4a3f2f; }'
      + ' img, video, svg { filter: sepia(0.4) saturate(1.1); }'
  }
  return 'html, body { background: #ffffff; color: #1c1e21; }'
}

function pageBackground(mode) {
  if (mode === 'dark') return '#1f2227'
  if (mode === 'sepia') return '#f4ecd8'
  return '#ffffff'
}

function applyStyles() {
  const family = currentFont ? `body, p, div, span, li { font-family: ${currentFont}; }` : ''
  const css = `html { font-size: ${currentZoom}px; }\n`
    + `body { line-height: ${currentLine}; }\n`
    + family + '\n' + themeCss(currentTheme)
  document.body.style.background = pageBackground(currentTheme)
  if (view.renderer && typeof view.renderer.setStyles === 'function') {
    try { view.renderer.setStyles(css) } catch (e) { /* renderer not ready */ }
  }
}

function emit(name, ...args) {
  if (bridge && typeof bridge[name] === 'function') {
    try { bridge[name](...args) } catch (e) { /* ignore */ }
  }
}

view.addEventListener('relocate', (e) => {
  const d = e.detail || {}
  emit('on_relocated', d.cfi || '', d.fraction || 0,
       (d.tocItem && d.tocItem.href) || '')
})
view.addEventListener('load', () => emit('on_loaded', ''))
view.addEventListener('error', (e) => emit('on_error', String((e.detail) || e)))

window.api = {
  open: async (url) => {
    try {
      await view.open(url)
      applyStyles()
      emit('on_opened', view.book ? JSON.stringify(view.book.metadata || {}) : '{}')
    } catch (err) { emit('on_error', String(err)) }
  },
  goTo: async (target) => {
    try { await view.goTo(target) } catch (e) { emit('on_error', String(e)) }
  },
  next: () => { try { view.next() } catch (e) { emit('on_error', String(e)) } },
  prev: () => { try { view.prev() } catch (e) { emit('on_error', String(e)) } },
  setAttr: (name, value) => {
    if (value === null || value === undefined) view.removeAttribute(name)
    else view.setAttribute(name, value)
  },
  zoom: (pt) => { currentZoom = pt; applyStyles() },
  theme: (mode) => { currentTheme = mode; applyStyles() },
  font: (family) => { currentFont = family || ''; applyStyles() },
  line: (value) => { currentLine = value || 1.5; applyStyles() },
  setStyles: (css) => {
    if (view.renderer && typeof view.renderer.setStyles === 'function') {
      try { view.renderer.setStyles(css) } catch (e) { /* ignore */ }
    }
  },
  toc: () => {
    const toc = (view.book && view.book.toc) || []
    emit('on_toc', JSON.stringify(toc))
  },
}

function connectChannel() {
  if (!(window.qt && window.qt.webChannelTransport)) return false
  new QWebChannel(window.qt.webChannelTransport, (channel) => {
    bridge = channel.objects.reader
    emit('on_ready', '')
  })
  return true
}

// Qt injects `window.qt.webChannelTransport` asynchronously: retry until it is
// available instead of checking only once at module-evaluation time.
if (!connectChannel()) {
  const timer = setInterval(() => { if (connectChannel()) clearInterval(timer) }, 50)
}
