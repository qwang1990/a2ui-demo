import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, test } from 'vitest'

const root = resolve(new URL('..', import.meta.url).pathname)

describe('ontology page split', () => {
  test('index page no longer embeds ontology editor', () => {
    const indexHtml = readFileSync(resolve(root, 'index.html'), 'utf-8')
    expect(indexHtml).toContain('<demo-app></demo-app>')
    expect(indexHtml).not.toContain('<ontology-app></ontology-app>')
  })

  test('ontology page exists as standalone entry', () => {
    const html = readFileSync(resolve(root, 'ontology.html'), 'utf-8')
    expect(html).toContain('<ontology-app></ontology-app>')
    expect(html).toContain('/src/ontology-studio.ts')
    expect(html).toContain('min-height: 100dvh')
  })
})
