export type A2uiActionContextEntry = { key: string; value: { path?: string } }

export type A2uiActionDetail = {
  action?: { name?: string; context?: A2uiActionContextEntry[] }
}

export type OutboundA2uiEvent = {
  type: 'a2ui_event'
  thread_id: string
  flow_id: string
  name: string
  context: Record<string, string>
}

type DispatchDeps = {
  getThreadId: () => string | null
  getFlowId: () => string
  getSurfaceId: () => string
  readPathValue: (path: string, surfaceId: string) => unknown
  send: (event: OutboundA2uiEvent) => void
  /** When true (e.g. flow already finished), actions are ignored. */
  isInteractionBlocked?: () => boolean
}

type ActionHandler = (name: string, detail: A2uiActionDetail) => Record<string, string> | null
type SuffixHandler = (name: string, detail: A2uiActionDetail) => Record<string, string> | null

export class A2uiActionRouter {
  private _handlers = new Map<string, ActionHandler>()
  private _suffixHandlers: Array<{ suffix: string; handler: SuffixHandler }> = []
  private readonly _deps: DispatchDeps

  constructor(deps: DispatchDeps) {
    this._deps = deps
    this.register('submit_collect', (_name, detail) => {
      const ctx: Record<string, string> = {}
      for (const entry of detail.action?.context ?? []) {
        const p = entry.value?.path
        if (!p) continue
        const v = this._deps.readPathValue(p, this._deps.getSurfaceId())
        ctx[entry.key] = v == null ? '' : String(v)
      }
      return ctx
    })
    this.registerSuffix('_confirm', () => ({}))
  }

  register(name: string, handler: ActionHandler): void {
    this._handlers.set(name, handler)
  }

  registerSuffix(suffix: string, handler: SuffixHandler): void {
    this._suffixHandlers.push({ suffix, handler })
  }

  dispatch(detail: A2uiActionDetail): boolean {
    if (this._deps.isInteractionBlocked?.()) return false
    const name = detail.action?.name
    const threadId = this._deps.getThreadId()
    if (!name || !threadId) return false

    let context: Record<string, string> | null = null
    const direct = this._handlers.get(name)
    if (direct) {
      context = direct(name, detail)
    } else {
      for (const item of this._suffixHandlers) {
        if (name.endsWith(item.suffix)) {
          context = item.handler(name, detail)
          break
        }
      }
    }
    if (context === null) return false
    this._deps.send({
      type: 'a2ui_event',
      thread_id: threadId,
      flow_id: this._deps.getFlowId(),
      name,
      context,
    })
    return true
  }
}
