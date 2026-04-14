/** 启动页表单校验；通过返回 `null`，否则返回面向用户的错误文案。 */
export function validateSplashInput(fullName: string, idNumber: string): string | null {
  const name = fullName.trim()
  const id = idNumber.trim()
  if (!name) return '请输入姓名。'
  if (!id) return '请输入身份证号。'
  return null
}
