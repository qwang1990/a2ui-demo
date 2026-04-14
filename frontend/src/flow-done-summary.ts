/** Legacy helpers kept for unit tests; flow_done 摘要改由后端 A2UI 生成。 */

export type FlowResultVariant = 'success' | 'failure' | 'neutral'

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
