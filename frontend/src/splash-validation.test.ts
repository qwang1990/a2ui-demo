import { describe, expect, it } from 'vitest'
import { validateSplashInput } from './splash-validation'

describe('validateSplashInput', () => {
  it('通过非空姓名与身份证', () => {
    expect(validateSplashInput('张三', '110101199001011234')).toBeNull()
    expect(validateSplashInput('  李四  ', '  HAS_MS  ')).toBeNull()
  })

  it('拒绝空姓名', () => {
    expect(validateSplashInput('', '110101199001011234')).toBe('请输入姓名。')
    expect(validateSplashInput('   ', 'x')).toBe('请输入姓名。')
  })

  it('拒绝空身份证', () => {
    expect(validateSplashInput('张三', '')).toBe('请输入身份证号。')
    expect(validateSplashInput('张三', '  \t')).toBe('请输入身份证号。')
  })
})
