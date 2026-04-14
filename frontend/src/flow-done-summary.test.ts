import { describe, expect, it } from 'vitest'

import { maskKeepLastDigits, outcomePresentation } from './flow-done-summary'

describe('maskKeepLastDigits', () => {
  it('masks id-style strings keeping last 4', () => {
    expect(maskKeepLastDigits('110101199001011234', 4)).toBe(`${'*'.repeat(14)}1234`)
  })

  it('handles short input', () => {
    expect(maskKeepLastDigits('12', 4)).toBe('**')
  })

  it('trims whitespace', () => {
    expect(maskKeepLastDigits('  13800138000  ', 4)).toBe('*******8000')
  })
})

describe('outcomePresentation', () => {
  it('maps approved and denied', () => {
    expect(outcomePresentation('approved').variant).toBe('success')
    expect(outcomePresentation('denied').variant).toBe('failure')
  })
})
