// Noesis bridge: connects foliate's reader engine to the Qt/Python side.
// The book is opened by foliate's reader.js from the `?url=` query parameter;
// here we only expose a small API and forward reading events.

let bridge = null
let zoom = 16
let theme = 'light'
let font = 'serif'
let spacing = 1.5
let justify = true
let hyphenate = true

function emit(name, ...args) {
  if (bridge && typeof bridge[name] === 'function') {
    try { bridge[name](...args) } catch (e) { /* ignore */ }
  }
}

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
  const view = globalThis.reader && globalThis.reader.view
  const renderer = view && view.renderer
  const base = '@namespace epub "http://www.idpf.org/2007/ops";'
    + `p, li, blockquote, dd { line-height: ${spacing};`
    + ` text-align: ${justify ? 'justify' : 'start'};`
    + ` -webkit-hyphens: ${hyphenate ? 'auto' : 'manual'};`
    + ` hyphens: ${hyphenate ? 'auto' : 'manual'}; }`
    + 'pre { white-space: pre-wrap !important; }'
  const css = `html { font-size: ${zoom}px; }\nbody { line-height: ${spacing}; }\n`
    + (font ? `body, p, div, span, li { font-family: ${font}; }` : '')
    + base + themeCss(theme)
  document.body.style.background = pageBackground(theme)
  if (renderer && typeof renderer.setStyles === 'function') {
    try { renderer.setStyles(css) } catch (e) { /* renderer not ready */ }
  }
}

window.api = {
  goTo: (target) => { try { globalThis.reader?.view?.goTo(target) } catch (e) { emit('on_error', String(e)) } },
  next: () => { try { globalThis.reader?.view?.next() } catch (e) { emit('on_error', String(e)) } },
  prev: () => { try { globalThis.reader?.view?.prev() } catch (e) { emit('on_error', String(e)) } },
  goToFraction: (f) => { try { globalThis.reader?.view?.goToFraction(f) } catch (e) { emit('on_error', String(e)) } },
  setTheme: (mode) => { theme = mode || 'light'; applyStyles() },
  setFont: (family) => { font = family || ''; applyStyles() },
  setSpacing: (value) => { spacing = value || 1.5; if (globalThis.reader?.style) globalThis.reader.style.spacing = spacing; applyStyles() },
  setLineHeight: (value) => { spacing = value || 1.5; applyStyles() },
  setJustify: (on) => { justify = !!on; applyStyles() },
  setHyphenate: (on) => { hyphenate = !!on; applyStyles() },
  setZoom: (pt) => { zoom = pt; applyStyles() },
  setFlow: (mode) => {
    try { globalThis.reader?.view?.renderer?.setAttribute('flow', mode) } catch (e) { /* ignore */ }
  },
  setSpread: (on) => {
    try { globalThis.reader?.view?.renderer?.setAttribute('max-column-count', on ? 2 : 1) } catch (e) { /* ignore */ }
  },
  search: async (query) => {
    const view = globalThis.reader?.view
    if (!view || !query) return ''
    try {
      for await (const result of view.search({ query })) {
        if (result && result.subitems && result.subitems.length) {
          const item = result.subitems[0]
          if (item && item.cfi) { await view.goTo(item.cfi); return item.cfi }
        }
      }
    } catch (e) { emit('on_error', String(e)) }
    return ''
  },
  last: () => JSON.stringify({
    href: (globalThis.__noesis && globalThis.__noesis.href) || '',
    fraction: (globalThis.__noesis && globalThis.__noesis.fraction) || 0,
  }),
}

function attach() {
  const reader = globalThis.reader
  if (!reader || !reader.view || !reader.view.renderer) return false
  reader.view.addEventListener('relocate', (e) => {
    const d = e.detail || {}
    globalThis.__noesis = {
      href: (d.tocItem && d.tocItem.href) || '',
      fraction: d.fraction || 0,
    }
    emit('on_relocated', d.cfi || '', d.fraction || 0,
         (d.tocItem && d.tocItem.href) || '')
  })
  reader.view.addEventListener('load', () => emit('on_loaded', ''))
  applyStyles()
  emit('on_ready', '')
  emit('on_opened', '')
  return true
}

function connectChannel() {
  if (!(window.qt && window.qt.webChannelTransport)) return false
  new QWebChannel(window.qt.webChannelTransport, (channel) => {
    bridge = channel.objects.reader
  })
  return true
}

if (!connectChannel()) {
  const t = setInterval(() => { if (connectChannel()) clearInterval(t) }, 50)
}
const attachTimer = setInterval(() => {
  if (attach()) clearInterval(attachTimer)
}, 50)
