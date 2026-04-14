import { V08_STANDARD_CATALOG_COMPONENTS } from './a2ui-v08-catalog'

export const DEFAULT_SURFACE_ID = 'main'

export const ALLOWED_RENDER_COMPONENTS = V08_STANDARD_CATALOG_COMPONENTS

export type A2uiTransportMessage = Record<string, unknown>

export type DecodedA2uiBatch = {
  requestId: string | null
  threadId: string | null
  flowId: string | null
  source: string
  fallbackReason: string | null
  assistantText: string | null
  messages: A2uiTransportMessage[]
  surfaceId: string
  unknownComponents: string[]
}

type DecodeResult =
  | { ok: true; value: DecodedA2uiBatch }
  | { ok: false; error: string }

function _asString(v: unknown): string | null {
  return typeof v === 'string' && v.trim() ? v : null
}

function _collectComponentType(msg: A2uiTransportMessage): string | null {
  const maybeSurface = msg.surfaceUpdate
  if (!maybeSurface || typeof maybeSurface !== 'object') return null
  const components = (maybeSurface as { components?: unknown[] }).components
  if (!Array.isArray(components)) return null
  for (const item of components) {
    if (!item || typeof item !== 'object') continue
    const component = (item as { component?: Record<string, unknown> }).component
    if (!component || typeof component !== 'object') continue
    const keys = Object.keys(component)
    if (keys.length > 0) return keys[0] ?? null
  }
  return null
}

export function normalizeA2uiMessages(raw: unknown): A2uiTransportMessage[] | null {
  if (!Array.isArray(raw)) return null
  const out: A2uiTransportMessage[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') return null
    const msg = item as Record<string, unknown>
    const hasKnownKey =
      'surfaceUpdate' in msg || 'dataModelUpdate' in msg || 'beginRendering' in msg || 'deleteSurface' in msg
    if (!hasKnownKey) return null
    out.push(msg)
  }
  return out
}

export function detectSurfaceId(messages: A2uiTransportMessage[], fallback = DEFAULT_SURFACE_ID): string {
  for (const msg of messages) {
    const update = msg.surfaceUpdate
    if (update && typeof update === 'object') {
      const sid = _asString((update as { surfaceId?: unknown }).surfaceId)
      if (sid) return sid
    }
    const render = msg.beginRendering
    if (render && typeof render === 'object') {
      const sid = _asString((render as { surfaceId?: unknown }).surfaceId)
      if (sid) return sid
    }
    const dataModel = msg.dataModelUpdate
    if (dataModel && typeof dataModel === 'object') {
      const sid = _asString((dataModel as { surfaceId?: unknown }).surfaceId)
      if (sid) return sid
    }
  }
  return fallback
}

export function decodeA2uiBatch(rawMsg: unknown): DecodeResult {
  if (!rawMsg || typeof rawMsg !== 'object') {
    return { ok: false, error: 'a2ui_batch 不是对象' }
  }
  const msg = rawMsg as Record<string, unknown>
  const messages = normalizeA2uiMessages(msg.messages)
  if (!messages) {
    return { ok: false, error: `a2ui_batch 消息结构非法: ${JSON.stringify(msg.messages)}` }
  }
  const unknownComponents: string[] = []
  for (const item of messages) {
    const typ = _collectComponentType(item)
    if (typ && !ALLOWED_RENDER_COMPONENTS.has(typ)) {
      unknownComponents.push(typ)
    }
  }
  return {
    ok: true,
    value: {
      requestId: _asString(msg.request_id),
      threadId: _asString(msg.thread_id),
      flowId: _asString(msg.flow_id),
      source: _asString(msg.messages_source) ?? 'template',
      fallbackReason: _asString(msg.fallback_reason),
      assistantText: _asString(msg.assistant_text),
      messages,
      surfaceId: detectSurfaceId(messages),
      unknownComponents,
    },
  }
}
