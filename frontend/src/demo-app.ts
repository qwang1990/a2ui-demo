import { Data } from '@a2ui/lit/0.8'
import '@a2ui/lit/ui'
import { Context as A2UIContext } from '@a2ui/lit/ui'
import type { A2uiMessageProcessor } from '@a2ui/web_core/data/model-processor'
import { A2uiActionRouter, type A2uiActionDetail } from './a2ui-action-router'
import { DEFAULT_A2UI_THEME } from './a2ui-default-theme'
import { DEFAULT_SURFACE_ID, decodeA2uiBatch, type A2uiTransportMessage } from './a2ui-contract'
import { outcomePresentation, rowsFromAttrs } from './flow-done-summary'
import { provide } from '@lit/context'
import { SignalWatcher } from '@lit-labs/signals'
import { css, html, LitElement } from 'lit'
import { customElement, state } from 'lit/decorators.js'
import { keyed } from 'lit/directives/keyed.js'

type RenderState = 'idle' | 'waiting' | 'rendering' | 'empty_tree' | 'error'
type TimelineRole = 'user' | 'assistant' | 'system'
type TimelineItem = {
  ts: number
  role: TimelineRole
  text: string
}

@customElement('demo-app')
export class DemoApp extends SignalWatcher(LitElement) {
  private _processor: A2uiMessageProcessor = Data.createSignalA2uiMessageProcessor()
  private _actionRouter = new A2uiActionRouter({
    getThreadId: () => this._threadId,
    getFlowId: () => this._flowId,
    getSurfaceId: () => this._activeSurfaceId,
    readPathValue: (path: string, surfaceId: string) => {
      const tree = this._processor.getSurfaces().get(surfaceId)?.componentTree
      if (!tree) return null
      return this._processor.getData(tree, path, surfaceId)
    },
    send: (event) => this._send(event),
    isInteractionBlocked: () => this._flowTerminal !== null,
  })
  @provide({ context: A2UIContext.theme })
  private _a2uiTheme: Record<string, unknown> = DEFAULT_A2UI_THEME

  private _ws: WebSocket | null = null
  private _errorHandler?: (ev: ErrorEvent) => void
  private _rejectionHandler?: (ev: PromiseRejectionEvent) => void

  @state() private _status = ''
  @state() private _flowId = 'sam_credit_card'
  @state() private _fullName = ''
  @state() private _idNumber = ''
  @state() private _threadId: string | null = null
  @state() private _tick = 0
  @state() private _renderState: RenderState = 'idle'
  @state() private _diagnostics = ''
  @state() private _timeline: TimelineItem[] = []
  @state() private _messagesSource = ''
  @state() private _fallbackReason = ''
  @state() private _activeSurfaceId = DEFAULT_SURFACE_ID
  @state() private _treeSummary = ''
  @state() private _showDebug = false
  @state() private _debugInfo = ''
  @state() private _runtimeError = ''
  /** Set when backend sends flow_done; clears A2UI surface and shows the end card. */
  @state() private _flowTerminal: { outcome: string; message: string; attrs?: Record<string, unknown> } | null =
    null

  connectedCallback(): void {
    super.connectedCallback()
    void this._a2uiTheme
    window.addEventListener('a2uiaction', this._onA2uiAction as EventListener)
    this._debugInfo = JSON.stringify({
      registry: {
        a2uiSurface: Boolean(customElements.get('a2ui-surface')),
        a2uiRoot: Boolean(customElements.get('a2ui-root')),
        a2uiText: Boolean(customElements.get('a2ui-text')),
        a2uiTextField: Boolean(customElements.get('a2ui-textfield')),
        a2uiButton: Boolean(customElements.get('a2ui-button')),
      },
    })
    this._errorHandler = (ev: ErrorEvent) => {
      const msg = ev.error instanceof Error ? ev.error.stack || ev.error.message : ev.message
      this._runtimeError = String(msg || 'unknown error')
      this._diagnostics = `运行时错误: ${this._runtimeError}`
    }
    this._rejectionHandler = (ev: PromiseRejectionEvent) => {
      const reason = ev.reason instanceof Error ? ev.reason.stack || ev.reason.message : String(ev.reason)
      this._runtimeError = String(reason || 'unknown rejection')
      this._diagnostics = `Promise异常: ${this._runtimeError}`
    }
    window.addEventListener('error', this._errorHandler)
    window.addEventListener('unhandledrejection', this._rejectionHandler)
  }

  disconnectedCallback(): void {
    super.disconnectedCallback()
    window.removeEventListener('a2uiaction', this._onA2uiAction as EventListener)
    if (this._errorHandler) window.removeEventListener('error', this._errorHandler)
    if (this._rejectionHandler) window.removeEventListener('unhandledrejection', this._rejectionHandler)
    this._ws?.close()
  }

  private _onA2uiAction = (ev: Event): void => {
    if (this._flowTerminal) return
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return
    const e = ev as CustomEvent<A2uiActionDetail>
    this._actionRouter.dispatch(e.detail ?? {})
  }

  private _send(obj: unknown) {
    this._ws?.send(JSON.stringify(obj))
  }

  private _pushTimeline(role: TimelineRole, text: string) {
    this._timeline = [...this._timeline, { ts: Date.now(), role, text }]
  }

  private _summarizeTree(surface: unknown): string {
    if (!surface || typeof surface !== 'object') return 'surface=null'
    const s = surface as { rootComponentId?: unknown; componentTree?: unknown }
    if (!s.componentTree || typeof s.componentTree !== 'object') {
      return `root=${String(s.rootComponentId ?? '')}; tree=null`
    }
    const node = s.componentTree as {
      id?: unknown
      type?: unknown
      properties?: { children?: unknown[]; child?: unknown }
    }
    const children = Array.isArray(node.properties?.children)
      ? node.properties?.children.length
      : node.properties?.child
        ? 1
        : 0
    return `root=${String(s.rootComponentId ?? '')}; node=${String(node.type ?? '')}:${String(node.id ?? '')}; children=${children}`
  }

  private _maskIdNumber(idNumber: string): string {
    const s = idNumber.trim()
    if (!s) return ''
    if (s.length <= 4) return '*'.repeat(s.length)
    return `${'*'.repeat(s.length - 4)}${s.slice(-4)}`
  }

  private _applyA2ui(messages: A2uiTransportMessage[], surfaceId: string) {
    try {
      this._processor.processMessages(messages as never[])
      this._tick++
      const surface = this._processor.getSurfaces().get(surfaceId)
      if (!surface) {
        this._renderState = 'error'
        this._diagnostics = `A2UI 处理后未找到 surface=${surfaceId}`
      } else if (!surface.componentTree) {
        this._renderState = 'empty_tree'
        this._diagnostics = '收到 a2ui_batch 但 componentTree 为空'
      } else {
        this._renderState = 'rendering'
        this._diagnostics = ''
      }
      this._treeSummary = this._summarizeTree(surface)
      this._debugInfo = JSON.stringify({
        ...(this._debugInfo ? JSON.parse(this._debugInfo) : {}),
        renderState: this._renderState,
        surfaceSummary: this._treeSummary,
      })
      if (import.meta.env.DEV) {
        const keys = [...this._processor.getSurfaces().keys()]
        console.debug('[demo-app] a2ui_batch', {
          messagesCount: messages.length,
          surfaceKeys: keys,
          activeSurfaceId: surfaceId,
          hasActiveSurface: Boolean(surface),
          hasTree: Boolean(surface?.componentTree),
          renderState: this._renderState,
        })
      }
    } catch (err) {
      this._renderState = 'error'
      const message = err instanceof Error ? err.message : String(err)
      this._diagnostics = `A2UI 渲染失败: ${message}`
      this._treeSummary = ''
      console.error('[demo-app] processMessages failed', err)
    }
  }

  private _connectWs() {
    this._ws?.close()
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${proto}//${location.host}/ws`
    const ws = new WebSocket(url)
    this._ws = ws
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data as string) as Record<string, unknown>
      if (msg.type === 'a2ui_batch') {
        const decoded = decodeA2uiBatch(msg)
        if (!decoded.ok) {
          const decodeError = 'error' in decoded ? decoded.error : '未知协议错误'
          this._renderState = 'error'
          this._diagnostics = decodeError
          this._treeSummary = ''
          this._status = 'A2UI 消息格式错误'
          this._pushTimeline('system', '收到非法 A2UI 消息结构')
          return
        }
        const { value } = decoded
        this._threadId = value.threadId
        this._flowId = value.flowId ?? this._flowId
        this._activeSurfaceId = value.surfaceId || DEFAULT_SURFACE_ID
        this._applyA2ui(value.messages, this._activeSurfaceId)
        this._messagesSource = value.source
        this._fallbackReason = value.fallbackReason ?? ''
        this._status = '等待用户操作…'
        this._pushTimeline('assistant', value.assistantText || '请补全信息后继续下一步。')
        const reasonPart = value.fallbackReason ? `, fallback=${value.fallbackReason}` : ''
        const unknownPart = value.unknownComponents.length
          ? `, unknown_components=${value.unknownComponents.join('|')}`
          : ''
        this._pushTimeline(
          'system',
          `动态交互卡片已更新（source=${value.source}${reasonPart}, surface=${this._activeSurfaceId}, messages=${value.messages.length}${unknownPart}）`,
        )
      } else if (msg.type === 'flow_done') {
        const outcome = String(msg.outcome ?? '')
        const message = String(msg.message ?? '')
        const attrsRaw = msg.attrs
        const attrs =
          attrsRaw && typeof attrsRaw === 'object' && !Array.isArray(attrsRaw)
            ? (attrsRaw as Record<string, unknown>)
            : undefined
        this._flowTerminal = { outcome, message, attrs }
        this._processor.clearSurfaces()
        this._tick++
        this._status = message ? `${message}（${outcome}）` : `流程结束（${outcome}）`
        this._renderState = 'idle'
        this._diagnostics = ''
        this._treeSummary = ''
        this._pushTimeline('assistant', `流程结束：${outcome} ${message}`.trim())
      } else if (msg.type === 'flow_progress') {
        const cur = String(msg.current_node_id ?? '')
        this._status = `节点：${cur}`
        this._pushTimeline('system', `流程推进到节点：${cur}`)
      } else if (msg.type === 'error') {
        this._status = `错误：${String(msg.message)}`
        this._renderState = 'error'
        this._diagnostics = String(msg.message ?? '')
        this._treeSummary = ''
        this._pushTimeline('system', `后端错误：${String(msg.message)}`)
      }
    }
    ws.onopen = () => {
      this._status = '已连接'
      this._renderState = 'waiting'
    }
    ws.onerror = () => {
      this._status = 'WebSocket 错误（请确认后端已启动）'
      this._renderState = 'error'
      this._diagnostics = 'WebSocket 连接错误'
      this._treeSummary = ''
    }
  }

  private _startFlow() {
    this._flowTerminal = null
    this._processor.clearSurfaces()
    this._tick++
    this._renderState = 'waiting'
    this._diagnostics = ''
    this._treeSummary = ''
    this._runtimeError = ''
    this._timeline = []
    const maskedId = this._maskIdNumber(this._idNumber)
    this._pushTimeline('user', `我想办理信用卡。姓名：${this._fullName.trim()}，身份证：${maskedId}`)
    this._pushTimeline('system', '已提交信息，流程引擎处理中...')
    this._connectWs()
    const ws = this._ws
    if (!ws) return
    const sendStart = () =>
      this._send({
        type: 'start_flow',
        flow_id: this._flowId,
        attrs: {
          fullName: this._fullName.trim(),
          idNumber: this._idNumber.trim(),
        },
      })
    if (ws.readyState === WebSocket.OPEN) sendStart()
    else ws.addEventListener('open', sendStart, { once: true })
  }

  render() {
    const surface = this._processor.getSurfaces().get(this._activeSurfaceId)
    const terminal = this._flowTerminal
    const pres = terminal ? outcomePresentation(terminal.outcome) : null
    const summaryRows = terminal ? rowsFromAttrs(terminal.attrs) : []
    return html`
      <div class="page">
        <header>
          <h1>山姆信用卡开卡 Demo</h1>
          <p class="sub">先填写基础信息，后续通过对话式动态卡片完成流程交互</p>
        </header>
        <section class="card">
          <label>流程</label>
          <select
            @change=${(e: Event) => {
              this._flowId = (e.target as HTMLSelectElement).value
            }}
          >
            <option value="sam_credit_card">sam_credit_card</option>
            <option value="simple_kyc">simple_kyc</option>
          </select>
          <label>姓名</label>
          <input
            .value=${this._fullName}
            @input=${(e: Event) => (this._fullName = (e.target as HTMLInputElement).value)}
          />
          <label>身份证号</label>
          <input
            .value=${this._idNumber}
            @input=${(e: Event) => (this._idNumber = (e.target as HTMLInputElement).value)}
          />
          <p class="hint">
            演示：身份证号包含 <code>SAMS_MEMBER</code> 模拟山姆会员（不予开卡）；包含
            <code>HAS_MS</code> 模拟持有民生信用卡（不予开卡）。
          </p>
          <button class="primary" @click=${() => this._startFlow()}>办理 Sam 信用卡</button>
        </section>
        <section class="card">
          <div class="chat-header">
            <div class="status">${this._status}</div>
            ${import.meta.env.DEV
              ? html`<button
                  class="toggle-debug"
                  @click=${() => {
                    this._showDebug = !this._showDebug
                  }}
                >
                  ${this._showDebug ? '隐藏调试' : '显示调试'}
                </button>`
              : null}
          </div>
          <div class="timeline">
            ${this._timeline.length
              ? this._timeline.map(
                  (item) => html`<div class="bubble ${item.role}">
                    <div class="bubble-role">${item.role}</div>
                    <div>${item.text}</div>
                  </div>`,
                )
              : html`<p class="muted">会话开始后，这里会显示完整交互过程。</p>`}
          </div>
          <p class="stage-title">${terminal ? '办理结果' : '当前交互卡片'}</p>
          <div class="surface-host" key=${this._tick}>
            ${terminal && pres
              ? html`<div class="flow-result ${pres.variant}">
                  <h2 class="flow-result-title">${pres.headline}</h2>
                  ${terminal.message
                    ? html`<p class="flow-result-detail"><strong>说明：</strong>${terminal.message}</p>`
                    : null}
                  <p class="flow-result-meta">结果代码：<code>${terminal.outcome || '—'}</code></p>
                  ${summaryRows.length
                    ? html`<dl class="flow-result-dl">
                        ${summaryRows.map(
                          (r) => html`<dt>${r.label}</dt>
                            <dd>${r.value}</dd>`,
                        )}
                      </dl>`
                    : null}
                  <p class="flow-result-foot muted">流程已结束，动态卡片已关闭；如需重新办理请点击上方按钮。</p>
                </div>`
              : surface
                ? keyed(
                    this._tick,
                    surface.componentTree
                      ? html`<a2ui-surface
                          .surfaceId=${this._activeSurfaceId}
                          .surface=${surface}
                          .processor=${this._processor}
                        ></a2ui-surface>`
                      : html`<p class="muted">已收到 A2UI 消息，但组件树为空（等待下一批或检查协议）</p>`,
                  )
                : html`<p class="muted">A2UI 区域（流程暂停补全数据时出现）</p>`}
          </div>
          ${this._diagnostics
            ? html`<p class="hint">诊断：<code>${this._diagnostics}</code></p>`
            : null}
          ${import.meta.env.DEV && this._showDebug
            ? html`<div class="debug-panel">
                <p class="hint">渲染状态：<code>${this._renderState}</code></p>
                <p class="hint">消息来源：<code>${this._messagesSource || 'n/a'}</code></p>
                <p class="hint">回退原因：<code>${this._fallbackReason || 'none'}</code></p>
                <p class="hint">渲染Surface：<code>${this._activeSurfaceId}</code></p>
                <p class="hint">组件树：<code>${this._treeSummary || 'n/a'}</code></p>
                <p class="hint">运行时错误：<code>${this._runtimeError || 'none'}</code></p>
                <p class="hint">调试信息：<code>${this._debugInfo || 'n/a'}</code></p>
              </div>`
            : null}
        </section>
      </div>
    `
  }

  static styles = css`
    :host {
      display: block;
      font-family: system-ui, sans-serif;
      color: #111;
      background: #f4f4f5;
      min-height: 100vh;
    }
    .page {
      max-width: 720px;
      margin: 0 auto;
      padding: 24px 16px 48px;
    }
    header h1 {
      margin: 0 0 8px;
      font-size: 1.35rem;
    }
    .sub {
      margin: 0;
      color: #555;
      font-size: 0.9rem;
    }
    .card {
      background: #fff;
      border-radius: 12px;
      padding: 16px;
      margin-top: 16px;
      box-shadow: 0 1px 3px rgb(0 0 0 / 0.08);
    }
    label {
      display: block;
      margin-top: 10px;
      font-size: 0.85rem;
      color: #444;
    }
    input,
    select {
      width: 100%;
      margin-top: 4px;
      padding: 8px 10px;
      border: 1px solid #ccc;
      border-radius: 8px;
      font: inherit;
      box-sizing: border-box;
    }
    .hint {
      font-size: 0.8rem;
      color: #666;
      margin: 10px 0 0;
    }
    code {
      background: #f0f0f0;
      padding: 1px 4px;
      border-radius: 4px;
    }
    .primary {
      margin-top: 14px;
      padding: 10px 16px;
      border: none;
      border-radius: 8px;
      background: #2563eb;
      color: #fff;
      font-weight: 600;
      cursor: pointer;
    }
    .primary:hover {
      background: #1d4ed8;
    }
    .status {
      font-size: 0.9rem;
      color: #333;
    }
    .chat-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 10px;
      gap: 10px;
    }
    .toggle-debug {
      border: 1px solid #d1d5db;
      border-radius: 6px;
      background: #fff;
      color: #374151;
      font-size: 0.8rem;
      padding: 6px 10px;
      cursor: pointer;
      white-space: nowrap;
    }
    .muted {
      color: #888;
      margin: 0;
    }
    .timeline {
      display: flex;
      flex-direction: column;
      gap: 8px;
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      padding: 10px;
      min-height: 120px;
      background: #fcfcfc;
      margin-bottom: 10px;
    }
    .bubble {
      max-width: 90%;
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 0.88rem;
      line-height: 1.35;
    }
    .bubble.user {
      align-self: flex-end;
      background: #dbeafe;
      color: #1e3a8a;
    }
    .bubble.assistant {
      align-self: flex-start;
      background: #eef2ff;
      color: #3730a3;
    }
    .bubble.system {
      align-self: center;
      max-width: 100%;
      width: 100%;
      background: #f3f4f6;
      color: #374151;
    }
    .bubble-role {
      font-weight: 700;
      margin-bottom: 2px;
      text-transform: uppercase;
      font-size: 0.7rem;
      opacity: 0.75;
    }
    .stage-title {
      margin: 6px 0;
      font-size: 0.82rem;
      color: #4b5563;
      font-weight: 600;
    }
    .surface-host {
      border: 1px dashed #cbd5e1;
      border-radius: 8px;
      padding: 12px;
      min-height: 120px;
      background: #fff;
    }
    .flow-result {
      border-radius: 10px;
      padding: 14px 14px 10px;
      border: 1px solid #e5e7eb;
      background: #fafafa;
    }
    .flow-result.success {
      border-color: #86efac;
      background: #f0fdf4;
    }
    .flow-result.failure {
      border-color: #fca5a5;
      background: #fef2f2;
    }
    .flow-result.neutral {
      border-color: #d1d5db;
      background: #f9fafb;
    }
    .flow-result-title {
      margin: 0 0 8px;
      font-size: 1.1rem;
    }
    .flow-result-detail {
      margin: 0 0 8px;
      font-size: 0.92rem;
      line-height: 1.45;
    }
    .flow-result-meta {
      margin: 0 0 10px;
      font-size: 0.85rem;
      color: #4b5563;
    }
    .flow-result-dl {
      margin: 0 0 10px;
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 4px 12px;
      font-size: 0.88rem;
    }
    .flow-result-dl dt {
      margin: 0;
      color: #6b7280;
      font-weight: 600;
    }
    .flow-result-dl dd {
      margin: 0;
      color: #111827;
    }
    .flow-result-foot {
      margin: 0;
      font-size: 0.82rem;
    }
    .debug-panel {
      margin-top: 10px;
      border-top: 1px dashed #d1d5db;
      padding-top: 10px;
    }
  `
}

declare global {
  interface HTMLElementTagNameMap {
    'demo-app': DemoApp
  }
}
