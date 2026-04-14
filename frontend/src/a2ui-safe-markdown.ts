/**
 * 供 `@a2ui/lit` Text 使用的极简 Markdown → HTML（供 unsafeHTML）。
 * 覆盖标题、加粗、换行与段落；其余内容做 HTML 转义，避免 XSS。
 */
export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

const H3_STYLE =
  'font-size:var(--demo-type-body,0.95rem);font-weight:650;margin:0;padding:0;letter-spacing:0.02em;color:var(--demo-text,#101828);line-height:1.32'
const H2_STYLE =
  'font-size:clamp(1.15rem,2.2vw,1.32rem);font-weight:700;letter-spacing:-0.02em;margin:0 0 12px;color:var(--demo-text,#101828);line-height:1.35'
const P_STYLE =
  'margin:10px 0;line-height:1.62;color:var(--demo-text,#101828);font-size:var(--demo-type-body,0.95rem)'
const P_MUTED =
  'margin:8px 0;line-height:1.58;color:var(--demo-text-muted,#52607a);font-size:0.9rem'

function formatInline(raw: string): string {
  const parts = raw.split(/(\*\*[^*]+\*\*)/g)
  return parts
    .map((p) => {
      const m = /^\*\*([^*]+)\*\*$/.exec(p)
      if (m) return `<strong style="font-weight:640;color:var(--demo-text,#101828)">${escapeHtml(m[1])}</strong>`
      return escapeHtml(p)
    })
    .join('')
}

function isUnfilledSummaryLine(rawLine: string): boolean {
  const line = rawLine.trim()
  if (!line) return false
  if (!line.startsWith('**')) return false
  const plain = line.replace(/\*\*/g, '').replace(/[：:]/g, '').replace(/\s+/g, '')
  return plain.endsWith('未填写') || plain.endsWith('—') || plain.endsWith('-')
}

function renderParagraphLines(lines: string[], style: string): string | null {
  const filtered = lines.map((ln) => ln.trimEnd()).filter((ln) => ln && !isUnfilledSummaryLine(ln))
  if (!filtered.length) return null
  return `<p style="${style}">${filtered.map((ln) => formatInline(ln.trim())).join('<br/>')}</p>`
}

/** 折叠误重复的「## ## 」等 */
function normalizeHeadingMarkdown(md: string): string {
  return md.replace(/^(\s*#{1,6}\s+)(#{1,6}\s+)/gm, '$1')
}

/**
 * @a2ui Text 传入的字符串可能已含 `## `（usageHint=h2 时组件会再包一层），此处做轻度归一。
 */
export function a2uiMarkdownToHtml(markdown: string): string {
  const src = normalizeHeadingMarkdown(markdown).trimEnd()
  if (!src) return ''

  const blocks = src.split(/\n{2,}/)
  const html: string[] = []

  for (const block of blocks) {
    const b = block.trim()
    if (!b) continue
    const lines = b.split(/\n/)
    const first = lines[0].trim()
    if (first.startsWith('### ')) {
      html.push(`<h3 style="${H3_STYLE}">${escapeHtml(first.slice(4).trim())}</h3>`)
      const rest = lines.slice(1).join('\n').trim()
      if (rest) {
        const p = renderParagraphLines(rest.split(/\n/), P_MUTED)
        if (p) html.push(p)
      }
      continue
    }
    if (first.startsWith('## ')) {
      html.push(`<h2 style="${H2_STYLE}">${escapeHtml(first.slice(3).trim())}</h2>`)
      const rest = lines.slice(1).join('\n').trim()
      if (rest) {
        const p = renderParagraphLines(rest.split(/\n/), P_MUTED)
        if (p) html.push(p)
      }
      continue
    }
    if (first.startsWith('# ')) {
      html.push(
        `<h1 style="font-size:clamp(1.4rem,2.6vw,1.72rem);font-weight:760;margin:0 0 12px;letter-spacing:-0.03em;color:var(--demo-text,#101828)">${escapeHtml(first.slice(2).trim())}</h1>`,
      )
      const rest = lines.slice(1).join('\n').trim()
      if (rest) {
        const p = renderParagraphLines(rest.split(/\n/), P_STYLE)
        if (p) html.push(p)
      }
      continue
    }
    const p = renderParagraphLines(lines, P_STYLE)
    if (p) html.push(p)
  }

  return html.join('')
}
