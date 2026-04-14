import { describe, expect, it } from 'vitest'

import { decodeA2uiBatch, detectSurfaceId, normalizeA2uiMessages } from './a2ui-contract'

describe('a2ui-contract', () => {
  it('normalizes legal messages', () => {
    const out = normalizeA2uiMessages([{ beginRendering: { surfaceId: 'main', root: 'r1' } }])
    expect(out).toHaveLength(1)
  })

  it('decodes batch and extracts metadata', () => {
    const decoded = decodeA2uiBatch({
      type: 'a2ui_batch',
      request_id: 'req-1',
      thread_id: 'th-1',
      flow_id: 'flow-1',
      messages_source: 'template_fallback:json_parse_error',
      fallback_reason: 'json_parse_error',
      assistant_text: '请补全',
      messages: [
        {
          surfaceUpdate: {
            surfaceId: 'form_surface',
            components: [
              {
                id: 'title',
                component: { Text: { text: { literalString: 'T' } } },
              },
            ],
          },
        },
        { beginRendering: { surfaceId: 'form_surface', root: 'root_col' } },
      ],
    })
    expect(decoded.ok).toBe(true)
    if (!decoded.ok) return
    expect(decoded.value.requestId).toBe('req-1')
    expect(decoded.value.surfaceId).toBe('form_surface')
    expect(decoded.value.fallbackReason).toBe('json_parse_error')
    expect(decoded.value.source).toContain('template_fallback')
    expect(decoded.value.unknownComponents).toEqual([])
  })

  it('marks unknown component type', () => {
    const decoded = decodeA2uiBatch({
      type: 'a2ui_batch',
      messages: [
        {
          surfaceUpdate: {
            surfaceId: 'main',
            components: [{ id: 'x', component: { DatePicker: {} } }],
          },
        },
      ],
    })
    expect(decoded.ok).toBe(true)
    if (!decoded.ok) return
    expect(decoded.value.unknownComponents).toEqual(['DatePicker'])
  })

  it('rejects malformed messages', () => {
    const decoded = decodeA2uiBatch({
      type: 'a2ui_batch',
      messages: [{ foo: 1 }],
    })
    expect(decoded.ok).toBe(false)
  })

  it('detects surface id from known keys', () => {
    const sid = detectSurfaceId(
      [
        {
          dataModelUpdate: {
            surfaceId: 'sid-1',
            contents: [],
          },
        },
      ],
      'main',
    )
    expect(sid).toBe('sid-1')
  })
})
