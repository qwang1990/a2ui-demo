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
})
