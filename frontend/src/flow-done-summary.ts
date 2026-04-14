/** Pure helpers for displaying flow_done in the demo UI (unit-tested). */

export type FlowResultVariant = 'success' | 'failure' | 'neutral'

export type AttrDisplayRow = { label: string; value: string }

const ATTR_LABELS: Record<string, string> = {
  fullName: '姓名',
  idNumber: '身份证号',
  phone: '手机号',
  address: '家庭住址',
}

export function maskKeepLastDigits(raw: string, keepLast: number): string {
  const s = raw.trim()
  if (!s) return ''
  if (s.length <= keepLast) return '*'.repeat(s.length)
  return `${'*'.repeat(s.length - keepLast)}${s.slice(-keepLast)}`
}

export function outcomePresentation(outcome: string): { headline: string; variant: FlowResultVariant } {
  if (outcome === 'approved') {
    return { headline: '办理结果：已通过', variant: 'success' }
  }
  if (outcome === 'denied') {
    return { headline: '办理结果：未通过', variant: 'failure' }
  }
  if (!outcome) {
    return { headline: '流程已结束', variant: 'neutral' }
  }
  return { headline: `流程已结束（${outcome}）`, variant: 'neutral' }
}

export function rowsFromAttrs(attrs: Record<string, unknown> | undefined): AttrDisplayRow[] {
  if (!attrs || typeof attrs !== 'object') return []
  const order = ['fullName', 'idNumber', 'phone', 'address']
  const rows: AttrDisplayRow[] = []
  for (const key of order) {
    if (!(key in attrs)) continue
    const raw = attrs[key]
    const str = raw == null ? '' : String(raw).trim()
    if (!str) continue
    const label = ATTR_LABELS[key] ?? key
    let value = str
    if (key === 'idNumber' || key === 'phone') {
      value = maskKeepLastDigits(str, 4)
    }
    rows.push({ label, value })
  }
  return rows
}
