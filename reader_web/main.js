// foliate-js wrapper: exposes a small API to Python over QWebChannel.
import './foliate-js/view.js'

const view = document.createElement('foliate-view')
view.id = 'view'
document.body.append(view)

let bridge = null

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

function themeCss(mode) {
  if (mode === 'dark') {
    return 'body{background:#1f2227;} foliate-view::part(filter){filter:invert(1) hue-rotate(180deg);}'
  }
  if (mode === 'sepia') {
    return 'body{background:#f4ecd8;} foliate-view::part(filter){filter:sepia(0.4) saturate(1.1);}'
  }
  return 'body{background:#ffffff;}'
}

window.api = {
  open: async (url) => {
    try {
      await view.open(url)
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
  zoom: (pt) => {
    document.getElementById('zoom').textContent =
      `foliate-view { font-size: ${pt}px; }`
  },
  theme: (mode) => {
    document.getElementById('theme').textContent = themeCss(mode)
  },
  toc: () => {
    const toc = (view.book && view.book.toc) || []
    emit('toc', JSON.stringify(toc))
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
