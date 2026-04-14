import { describe, expect, it } from 'vitest'
import { DEFAULT_A2UI_THEME } from './a2ui-default-theme'
import { V08_STANDARD_CATALOG_COMPONENTS } from './a2ui-v08-catalog'

describe('DEFAULT_A2UI_THEME', () => {
  it('defines a plain object for every v0.8 catalog component', () => {
    const components = DEFAULT_A2UI_THEME.components as Record<string, unknown>
    for (const name of V08_STANDARD_CATALOG_COMPONENTS) {
      expect(components, `missing theme.components.${name}`).toHaveProperty(name)
      const entry = components[name]
      expect(entry, name).toBeTruthy()
      expect(entry, name).not.toBeNull()
      expect(typeof entry, name).toBe('object')
    }
  })

  it('covers classMap paths used by Row / TextField / Modal', () => {
    const c = DEFAULT_A2UI_THEME.components as Record<string, Record<string, unknown>>
    expect(typeof c.Row).toBe('object')
    expect(typeof c.TextField.container).toBe('object')
    expect(typeof c.Modal.backdrop).toBe('object')
    expect(typeof c.Modal.element).toBe('object')
  })

  it('provides additionalStyles for shadow-DOM widgets (Button, TextField, Card, Text.body)', () => {
    const add = DEFAULT_A2UI_THEME.additionalStyles as Record<string, unknown>
    const btn = add.Button as Record<string, string>
    expect(btn.background).toContain('var(--demo-accent')
    expect(btn.borderRadius).toContain('var(--demo-radius-md')
    expect(btn.width).toBe('auto')
    expect(btn.display).toBe('inline-flex')
    expect(btn.transition).toContain('transform')
    const tf = add.TextField as Record<string, string>
    expect(tf.minHeight).toBe('46px')
    expect(tf.fontSize).toContain('var(--demo-type-body')
    const card = add.Card as Record<string, string>
    expect(card.borderRadius).toContain('var(--demo-radius-lg')
    expect(card.boxShadow).toContain('rgb(15 23 42')
    const dt = add.DateTimeInput as Record<string, string>
    expect(dt.fontSize).toContain('var(--demo-type-body')
    const slider = add.Slider as Record<string, string>
    expect(slider.accentColor).toContain('var(--demo-accent')
    const textStyles = add.Text as Record<string, Record<string, string>>
    expect(textStyles.body.fontSize).toContain('var(--demo-type-body')
    expect(textStyles.h1).toEqual({})
    expect(textStyles.h3.margin).toBe('0')
    expect(textStyles.h3.fontWeight).toBe('650')
  })
})
