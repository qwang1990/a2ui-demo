import { describe, expect, it } from 'vitest'
import { a2uiMarkdownToHtml, escapeHtml } from './a2ui-safe-markdown'

describe('escapeHtml', () => {
  it('转义尖括号与 &', () => {
    expect(escapeHtml('<a>&')).toBe('&lt;a&gt;&amp;')
  })
})

describe('a2uiMarkdownToHtml', () => {
  it('渲染二级标题', () => {
    const h = a2uiMarkdownToHtml('## 请填写详细信息')
    expect(h).toContain('<h2')
    expect(h).toContain('请填写详细信息')
    expect(h).toContain('var(--demo-text')
    expect(h).not.toContain('##')
  })

  it('渲染三级标题（用于按钮内文案）', () => {
    const h = a2uiMarkdownToHtml('### 提交')
    expect(h).toContain('<h3')
    expect(h).toContain('提交')
    expect(h).not.toMatch(/###/)
  })

  it('渲染加粗行', () => {
    const h = a2uiMarkdownToHtml('**姓名**　张三')
    expect(h).toContain('<strong')
    expect(h).toContain('var(--demo-text')
    expect(h).toContain('姓名')
    expect(h).not.toContain('**')
  })

  it('归一误重复井号', () => {
    const h = a2uiMarkdownToHtml('## ## 标题')
    expect(h).toContain('标题')
    expect(h).not.toMatch(/##/)
  })

  it('正文样式引用统一 token', () => {
    const h = a2uiMarkdownToHtml('普通正文')
    expect(h).toContain('var(--demo-type-body')
    expect(h).toContain('var(--demo-text')
  })

  it('过滤未填写的摘要行', () => {
    const h = a2uiMarkdownToHtml('**家庭住址**：未填写\n**手机号**：111111')
    expect(h).not.toContain('家庭住址')
    expect(h).toContain('手机号')
  })
})
