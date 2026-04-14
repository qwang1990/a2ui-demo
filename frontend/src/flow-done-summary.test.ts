import { describe, expect, it } from 'vitest'

import { maskKeepLastDigits, outcomePresentation, rowsFromAttrs } from './flow-done-summary'

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

describe('rowsFromAttrs', () => {
  it('orders known keys and masks sensitive fields', () => {
    const rows = rowsFromAttrs({
      phone: '13800138000',
      fullName: '张三',
      idNumber: '110101199001011234',
      address: '北京市朝阳区',
    })
    expect(rows.map((r) => r.label)).toEqual(['姓名', '身份证号', '手机号', '家庭住址'])
    expect(rows.find((r) => r.label === '手机号')?.value).toBe('*******8000')
    expect(rows.find((r) => r.label === '身份证号')?.value).toBe(`${'*'.repeat(14)}1234`)
  })
})
