import { Data } from '@a2ui/lit/0.8'
import '@a2ui/lit/ui'
import { Context as A2UIContext } from '@a2ui/lit/ui'
import type { A2uiMessageProcessor } from '@a2ui/web_core/data/model-processor'
import type { MarkdownRenderer } from '@a2ui/web_core'
import { A2uiActionRouter, type A2uiActionDetail } from './a2ui-action-router'
import { DEFAULT_A2UI_THEME } from './a2ui-default-theme'
import {
  DEFAULT_SURFACE_ID,
  decodeA2uiBatch,
  normalizeA2uiMessages,
  type A2uiTransportMessage,
} from './a2ui-contract'
import { validateSplashInput } from './splash-validation'
import { a2uiMarkdownToHtml } from './a2ui-safe-markdown'
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

type UiPhase = 'splash' | 'flow'
type ProgressBusinessInfo = {
  node_id?: string
  node_kind?: string
  node_title?: string
  collect_fields?: string[]
  object_type?: string
  logic_name?: string
  logic_description?: string
  logic_result?: string
  logic_branch?: string
  next_node_id?: string
  action_name?: string
  action_description?: string
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

  /** 未配置时 Text 会把 `## 标题` 原样输出；注入后正常渲染标题与加粗。 */
  @provide({ context: A2UIContext.markdown })
  private _a2uiMarkdown: MarkdownRenderer = (markdown) =>
    a2uiMarkdownToHtml(typeof markdown === 'string' ? markdown : '')

  private _ws: WebSocket | null = null
  private _errorHandler?: (ev: ErrorEvent) => void
  private _rejectionHandler?: (ev: PromiseRejectionEvent) => void

  @state() private _uiPhase: UiPhase = 'splash'
  @state() private _splashError = ''
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
  /** Set when backend sends flow_done；结束内容由 A2UI 渲染，此处仅用于禁用交互与状态文案。 */
  @state() private _flowTerminal: { outcome: string; message: string } | null = null

  connectedCallback(): void {
    super.connectedCallback()
    void this._a2uiTheme
    void this._a2uiMarkdown
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

  private _flowLabel(): string {
    return this._flowId === 'sam_credit_card' ? '山姆信用卡开卡' : this._flowId
  }

  private _buildProgressNarrative(msg: Record<string, unknown>): string[] {
    const infoRaw = msg.business_info
    if (!infoRaw || typeof infoRaw !== 'object') return []
    const info = infoRaw as ProgressBusinessInfo
    const nodeId = typeof info.node_id === 'string' ? info.node_id : ''
    const nodeKind = typeof info.node_kind === 'string' ? info.node_kind : ''
    const title = typeof info.node_title === 'string' ? info.node_title.trim() : ''
    const lines: string[] = []

    if (nodeKind === 'collect') {
      lines.push(`进入采集节点：${nodeId || 'unknown'}${title ? `（${title}）` : ''}`)
      if (Array.isArray(info.collect_fields) && info.collect_fields.length) {
        lines.push(`本节点采集字段：${info.collect_fields.join('、')}`)
      }
      return lines
    }
    if (nodeKind === 'logic') {
      const logicName =
        typeof info.logic_name === 'string' && info.logic_name.trim() ? info.logic_name.trim() : nodeId
      lines.push(`执行规则判断：${logicName || '未知规则'}`)
      if (typeof info.logic_description === 'string' && info.logic_description.trim()) {
        lines.push(`规则说明：${info.logic_description.trim()}`)
      }
      if (typeof info.logic_result === 'string' && info.logic_result.trim()) {
        const next =
          typeof info.next_node_id === 'string' && info.next_node_id.trim()
            ? `，下一节点：${info.next_node_id.trim()}`
            : ''
        lines.push(`规则结果：${info.logic_result.trim()}${next}`)
      }
      return lines
    }
    if (nodeKind === 'action') {
      const actionName =
        typeof info.action_name === 'string' && info.action_name.trim() ? info.action_name.trim() : nodeId
      lines.push(`进入操作节点：${actionName || '待确认操作'}`)
      if (typeof info.action_description === 'string' && info.action_description.trim()) {
        lines.push(`操作说明：${info.action_description.trim()}`)
      }
      return lines
    }
    if (nodeKind === 'terminal') {
      lines.push(`流程进入结束节点：${nodeId || 'terminal'}`)
      return lines
    }
    if (nodeId) lines.push(`流程推进到节点：${nodeId}`)
    return lines
  }

  private _resetToSplash(): void {
    this._ws?.close()
    this._ws = null
    this._flowTerminal = null
    this._processor.clearSurfaces()
    this._tick++
    this._threadId = null
    this._timeline = []
    this._status = ''
    this._renderState = 'idle'
    this._diagnostics = ''
    this._treeSummary = ''
    this._messagesSource = ''
    this._fallbackReason = ''
    this._runtimeError = ''
    this._activeSurfaceId = DEFAULT_SURFACE_ID
    this._splashError = ''
    this._uiPhase = 'splash'
  }

  private _onBeginCard(): void {
    const err = validateSplashInput(this._fullName, this._idNumber)
    if (err) {
      this._splashError = err
      return
    }
    this._splashError = ''
    this._uiPhase = 'flow'
    this._startFlow()
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
        const fromLlm = value.source.startsWith('llm')
        const fallback = value.fallbackReason ? `（已回退：${value.fallbackReason}）` : ''
        this._pushTimeline(
          'system',
          fromLlm
            ? `已生成新的业务交互卡片，请按卡片提示继续办理${fallback}`
            : `已更新业务交互卡片，请继续完成当前节点${fallback}`,
        )
      } else if (msg.type === 'flow_done') {
        const outcome = String(msg.outcome ?? '')
        const message = String(msg.message ?? '')
        const rawMsgs = (msg as { a2ui_messages?: unknown }).a2ui_messages
        const sidRaw = (msg as { surface_id?: unknown }).surface_id
        const sid =
          typeof sidRaw === 'string' && sidRaw.trim() ? sidRaw.trim() : DEFAULT_SURFACE_ID
        this._processor.clearSurfaces()
        this._tick++
        const norm = Array.isArray(rawMsgs) ? normalizeA2uiMessages(rawMsgs) : null
        if (norm && norm.length) {
          this._activeSurfaceId = sid
          this._applyA2ui(norm, sid)
        } else {
          this._renderState = 'idle'
          this._treeSummary = ''
          this._diagnostics = '未收到结束页 A2UI 消息（请确认后端已注册当前 flow）'
        }
        this._flowTerminal = { outcome, message }
        this._status = message ? `${message}（${outcome}）` : `流程结束（${outcome}）`
        this._pushTimeline('assistant', `流程结束：${outcome} ${message}`.trim())
      } else if (msg.type === 'flow_progress') {
        const cur = String(msg.current_node_id ?? '')
        const narratives = this._buildProgressNarrative(msg)
        this._status = narratives[0] || `节点：${cur}`
        if (narratives.length) {
          for (const line of narratives) this._pushTimeline('system', line)
        } else {
          this._pushTimeline('system', `流程推进到节点：${cur}`)
        }
        const stepHint = typeof msg.step_hint === 'string' ? msg.step_hint.trim() : ''
        if (stepHint) this._pushTimeline('system', `节点说明：${stepHint}`)
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

  private _renderSplash() {
    return html`
      <div class="page splash">
        <header class="hero">
          <p class="eyebrow">演示环境</p>
          <h1>山姆信用卡开卡</h1>
          <p class="sub">填写基础信息后进入对话式流程；动态界面由 A2UI 协议驱动。</p>
        </header>
        <section class="card splash-card">
          <h2 class="card-title">开始办理</h2>
          <p class="muted flow-hint">当前流程：<strong>${this._flowLabel()}</strong>（<code>sam_credit_card</code>）</p>
          <label>姓名</label>
          <input
            name="fullName"
            autocomplete="name"
            .value=${this._fullName}
            @input=${(e: Event) => {
              this._fullName = (e.target as HTMLInputElement).value
              if (this._splashError) this._splashError = ''
            }}
          />
          <label>身份证号</label>
          <input
            name="idNumber"
            autocomplete="off"
            .value=${this._idNumber}
            @input=${(e: Event) => {
              this._idNumber = (e.target as HTMLInputElement).value
              if (this._splashError) this._splashError = ''
            }}
          />
          <p class="hint">
            演示 Mock：身份证号会先转大写再匹配子串。<code>SAMS_MEMBER</code> → 山姆会员（第一步拒贷）；
            <code>HAS_MS</code> → 已持民生卡（第二步拒贷）。完整对照表（姓名+身份证样例与预期 flags）见接口
            <code>GET /api/mock-ontology/demo-seeds</code>。
          </p>
          ${this._splashError ? html`<p class="form-error" role="alert">${this._splashError}</p>` : null}
          <button type="button" class="primary" @click=${() => this._onBeginCard()}>办卡</button>
          <a class="btn-secondary nav-ontology" href=${`/ontology.html?flow=${encodeURIComponent(this._flowId)}`}>
            打开本体与 AIP Logic 管理页
          </a>
        </section>
      </div>
    `
  }

  private _renderFlow() {
    const surface = this._processor.getSurfaces().get(this._activeSurfaceId)
    const terminal = this._flowTerminal
    const masked = this._maskIdNumber(this._idNumber)
    return html`
      <div class="page flow">
        <header class="flow-head">
          <div class="flow-head-main">
            <div>
              <p class="eyebrow">办理中</p>
              <h1>山姆信用卡开卡</h1>
              <p class="sub">请在下方卡片中完成操作；会话记录会同步展示。</p>
            </div>
            <button type="button" class="btn-ghost" @click=${() => this._resetToSplash()}>重新开始</button>
          </div>
          <div class="chips">
            <span class="chip">${this._flowLabel()}</span>
            <span class="chip chip-dim">${this._fullName.trim() || '—'}</span>
            <span class="chip chip-dim">${masked || '—'}</span>
          </div>
        </header>
        <section class="card flow-card">
          <div class="chat-header">
            <div class="status-wrap">
              <span class="status-dot" data-state=${this._renderState}></span>
              <div class="status">${this._status || '准备中…'}</div>
            </div>
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
          <div class="flow-grid">
            <div class="timeline-panel">
              <p class="stage-title">会话轨迹</p>
              <div class="timeline">
                ${this._timeline.length
                  ? this._timeline.map(
                      (item) => html`<div class="bubble ${item.role}">
                        <div class="bubble-role">${item.role}</div>
                        <div>${item.text}</div>
                      </div>`,
                    )
                  : html`<p class="muted">正在连接并拉取流程…</p>`}
              </div>
            </div>
            <div class="surface-panel">
              <p class="stage-title">${terminal ? '办理结果（A2UI）' : '当前交互卡片'}</p>
              <div class="surface-host" key=${this._tick}>
                ${surface
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
                  : html`<p class="muted">等待服务端下发 A2UI 卡片…</p>`}
              </div>
              ${this._diagnostics ? html`<p class="hint">诊断：<code>${this._diagnostics}</code></p>` : null}
            </div>
          </div>
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

  render() {
    return this._uiPhase === 'splash' ? this._renderSplash() : this._renderFlow()
  }

  static styles = css`
    :host {
      display: block;
      font-family: var(--demo-font);
      color: var(--demo-text);
      background: var(--demo-bg-page);
      min-height: 100vh;
      min-height: 100dvh;
      --demo-font:
        'Inter',
        'SF Pro Text',
        'Segoe UI',
        'PingFang SC',
        'Hiragino Sans GB',
        'Microsoft Yahei',
        system-ui,
        sans-serif;
      --demo-bg-page: #f6f8fc;
      --demo-bg-spot:
        radial-gradient(circle at 0% 0%, rgb(59 130 246 / 0.14), transparent 36%),
        radial-gradient(circle at 100% 10%, rgb(14 165 233 / 0.08), transparent 34%);
      --demo-bg-elevated: #ffffff;
      --demo-surface: #ffffff;
      --demo-surface-soft: #f8faff;
      --demo-surface-elevated: #ffffff;
      --demo-border: #dfe5f3;
      --demo-border-strong: #bcc7df;
      --demo-text: #101828;
      --demo-text-muted: #52607a;
      --demo-accent: #2563eb;
      --demo-accent-hover: #1d4ed8;
      --demo-success: #22c55e;
      --demo-warning: #f59e0b;
      --demo-danger: #ef4444;
      --demo-focus-ring: rgb(37 99 235 / 0.35);
      --demo-space-2: 0.5rem;
      --demo-space-3: 0.75rem;
      --demo-space-4: 1rem;
      --demo-space-5: 1.25rem;
      --demo-space-6: 1.5rem;
      --demo-space-8: 2rem;
      --demo-space-10: 2.5rem;
      --demo-space-12: 3rem;
      --demo-radius-sm: 10px;
      --demo-radius-md: 14px;
      --demo-radius-lg: 18px;
      --demo-radius-xl: 24px;
      --demo-radius-pill: 999px;
      --demo-shadow-sm: 0 1px 2px rgb(15 23 42 / 0.05);
      --demo-shadow: 0 10px 30px rgb(15 23 42 / 0.08);
      --demo-shadow-lg: 0 24px 56px rgb(15 23 42 / 0.12);
      --demo-type-label: 0.78rem;
      --demo-type-body: 0.95rem;
      --demo-type-title: clamp(1.6rem, 3vw, 2rem);
      --demo-type-hero: clamp(2.05rem, 4.4vw, 2.6rem);
    }

    @media (prefers-color-scheme: dark) {
      :host {
        --demo-bg-page: #090d1a;
        --demo-bg-spot:
          radial-gradient(circle at 0% 0%, rgb(37 99 235 / 0.25), transparent 40%),
          radial-gradient(circle at 100% 12%, rgb(56 189 248 / 0.1), transparent 38%);
        --demo-bg-elevated: #11182a;
        --demo-surface: #0f172a;
        --demo-surface-soft: #16213d;
        --demo-surface-elevated: #17213a;
        --demo-border: #293751;
        --demo-border-strong: #41567c;
        --demo-text: #f8fafc;
        --demo-text-muted: #9aa9c4;
        --demo-accent: #3b82f6;
        --demo-accent-hover: #60a5fa;
        --demo-success: #4ade80;
        --demo-warning: #fbbf24;
        --demo-danger: #f87171;
        --demo-focus-ring: rgb(96 165 250 / 0.42);
        --demo-shadow-sm: 0 1px 2px rgb(0 0 0 / 0.35);
        --demo-shadow: 0 12px 32px rgb(0 0 0 / 0.4);
        --demo-shadow-lg: 0 26px 64px rgb(0 0 0 / 0.52);
      }
    }

    .page {
      max-width: 1120px;
      margin: 0 auto;
      padding: var(--demo-space-10) var(--demo-space-6) var(--demo-space-12);
      box-sizing: border-box;
    }

    .page.splash {
      max-width: 860px;
      min-height: min(100vh, 980px);
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: var(--demo-space-6);
      padding-top: var(--demo-space-12);
      padding-bottom: var(--demo-space-12);
      background: var(--demo-bg-spot);
    }

    .hero {
      text-align: center;
      margin-bottom: var(--demo-space-4);
      padding: var(--demo-space-8);
      border: 1px solid color-mix(in srgb, var(--demo-border) 74%, transparent);
      border-radius: var(--demo-radius-xl);
      background: linear-gradient(
        160deg,
        color-mix(in srgb, var(--demo-surface-elevated) 94%, var(--demo-accent) 6%),
        var(--demo-bg-elevated)
      );
      box-shadow: var(--demo-shadow);
    }

    .eyebrow {
      margin: 0 0 var(--demo-space-3);
      font-size: var(--demo-type-label);
      font-weight: 600;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--demo-text-muted);
    }

    header h1 {
      margin: 0 0 var(--demo-space-3);
      font-size: var(--demo-type-hero);
      font-weight: 760;
      letter-spacing: -0.03em;
    }

    .sub {
      margin: 0 auto;
      max-width: 40rem;
      color: var(--demo-text-muted);
      font-size: var(--demo-type-body);
      line-height: 1.55;
    }

    .card {
      background: var(--demo-bg-elevated);
      border-radius: var(--demo-radius-lg);
      padding: var(--demo-space-8) var(--demo-space-8) var(--demo-space-6);
      border: 1px solid var(--demo-border);
      box-shadow: var(--demo-shadow);
      transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
    }

    .card:hover {
      border-color: color-mix(in srgb, var(--demo-border-strong) 65%, var(--demo-accent));
      box-shadow: var(--demo-shadow-lg);
    }

    .splash-card {
      box-shadow: var(--demo-shadow-lg);
    }

    .ontology-card {
      margin-top: var(--demo-space-6);
    }

    .ontology-toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: var(--demo-space-3);
      margin-top: var(--demo-space-4);
    }

    .btn-secondary {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      text-decoration: none;
      padding: 10px 16px;
      border-radius: var(--demo-radius-md);
      border: 1px solid var(--demo-border);
      background: color-mix(in srgb, var(--demo-surface) 88%, var(--demo-accent) 12%);
      color: var(--demo-text);
      font-size: 0.86rem;
      font-weight: 600;
      cursor: pointer;
      transition: transform 0.16s ease, background 0.16s ease, border-color 0.16s ease;
    }

    .btn-secondary:hover:not(:disabled) {
      transform: translateY(-1px);
      border-color: var(--demo-border-strong);
      background: color-mix(in srgb, var(--demo-surface) 76%, var(--demo-accent) 24%);
    }

    .btn-secondary:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }

    .nav-ontology {
      margin-top: var(--demo-space-3);
      width: 100%;
    }

    .ontology-textarea {
      width: 100%;
      min-height: 230px;
      margin-top: var(--demo-space-4);
      padding: var(--demo-space-4);
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;
      font-size: 0.82rem;
      line-height: 1.45;
      border: 1px solid var(--demo-border);
      border-radius: var(--demo-radius-md);
      background: var(--demo-surface);
      color: var(--demo-text);
      box-sizing: border-box;
      resize: vertical;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }

    .ontology-status {
      margin: var(--demo-space-3) 0 0;
      font-size: 0.86rem;
      color: var(--demo-text-muted);
    }

    .ontology-errors {
      margin: var(--demo-space-3) 0 0;
      padding-left: 1.2rem;
      font-size: 0.83rem;
      color: var(--demo-danger);
    }

    .card-title {
      margin: 0 0 var(--demo-space-5);
      font-size: 1.04rem;
      font-weight: 650;
      letter-spacing: -0.01em;
    }

    label {
      display: block;
      margin-top: var(--demo-space-4);
      font-size: var(--demo-type-label);
      font-weight: 600;
      color: var(--demo-text-muted);
    }

    label:first-of-type {
      margin-top: 0;
    }

    input,
    select {
      width: 100%;
      margin-top: var(--demo-space-2);
      padding: 12px 14px;
      border: 1px solid var(--demo-border);
      border-radius: var(--demo-radius-md);
      font: inherit;
      font-size: var(--demo-type-body);
      box-sizing: border-box;
      background: var(--demo-surface);
      color: var(--demo-text);
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }

    input:focus-visible,
    textarea:focus-visible,
    select:focus-visible,
    button:focus-visible {
      outline: none;
      border-color: var(--demo-accent);
      box-shadow: 0 0 0 3px var(--demo-focus-ring);
    }

    .hint {
      font-size: 0.82rem;
      color: var(--demo-text-muted);
      margin: var(--demo-space-4) 0 0;
      line-height: 1.5;
    }

    code {
      background: color-mix(in srgb, var(--demo-border) 55%, transparent);
      padding: 3px 6px;
      border-radius: 8px;
      font-size: 0.8em;
    }

    .form-error {
      margin: var(--demo-space-4) 0 0;
      font-size: 0.86rem;
      color: var(--demo-danger);
    }

    .primary {
      margin-top: var(--demo-space-5);
      width: 100%;
      min-height: 48px;
      padding: 12px 20px;
      border: none;
      border-radius: var(--demo-radius-md);
      background: linear-gradient(
        180deg,
        color-mix(in srgb, var(--demo-accent) 88%, #ffffff 12%),
        var(--demo-accent)
      );
      color: #fff;
      font-weight: 640;
      font-size: 0.95rem;
      cursor: pointer;
      transition: transform 0.16s ease, background 0.16s ease, box-shadow 0.16s ease;
      box-shadow: 0 8px 20px color-mix(in srgb, var(--demo-accent) 32%, transparent);
    }

    .primary:hover {
      transform: translateY(-1px);
      background: var(--demo-accent-hover);
    }

    /* —— 流程页 —— */
    .flow-head {
      margin-bottom: var(--demo-space-6);
      padding: var(--demo-space-6);
      border-radius: var(--demo-radius-lg);
      border: 1px solid color-mix(in srgb, var(--demo-border) 80%, transparent);
      background: linear-gradient(
        156deg,
        color-mix(in srgb, var(--demo-surface-elevated) 90%, var(--demo-accent) 10%),
        var(--demo-bg-elevated)
      );
      box-shadow: var(--demo-shadow);
    }

    .flow-head-main {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--demo-space-5);
    }

    .flow-head-main h1 {
      text-align: left;
      font-size: var(--demo-type-title);
    }

    .flow-head .sub {
      margin: 0;
      text-align: left;
    }

    .btn-ghost {
      flex-shrink: 0;
      padding: 10px 16px;
      border-radius: var(--demo-radius-md);
      border: 1px solid var(--demo-border);
      background: color-mix(in srgb, var(--demo-surface) 80%, var(--demo-accent) 20%);
      color: var(--demo-text);
      font-size: 0.86rem;
      font-weight: 600;
      cursor: pointer;
      transition: transform 0.16s ease, background 0.16s ease, border-color 0.16s ease;
    }

    .btn-ghost:hover {
      transform: translateY(-1px);
      border-color: var(--demo-border-strong);
      background: color-mix(in srgb, var(--demo-surface) 72%, var(--demo-accent) 28%);
    }

    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: var(--demo-space-2);
      margin-top: var(--demo-space-4);
    }

    .chip {
      font-size: var(--demo-type-label);
      font-weight: 600;
      padding: 6px 12px;
      border-radius: var(--demo-radius-pill);
      border: 1px solid var(--demo-border);
      background: color-mix(in srgb, var(--demo-surface) 78%, var(--demo-accent) 22%);
      color: var(--demo-text);
    }

    .chip-dim {
      font-weight: 500;
      color: var(--demo-text-muted);
    }

    .status-wrap {
      display: flex;
      align-items: center;
      gap: var(--demo-space-2);
      min-width: 0;
    }

    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
      background: var(--demo-text-muted);
    }

    .status-dot[data-state='rendering'],
    .status-dot[data-state='waiting'] {
      background: var(--demo-success);
    }

    .status-dot[data-state='error'] {
      background: var(--demo-danger);
    }

    .status {
      font-size: 0.9rem;
      color: var(--demo-text);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .chat-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: var(--demo-space-5);
      gap: var(--demo-space-3);
    }

    .flow-card {
      padding: var(--demo-space-6);
    }

    .flow-grid {
      display: grid;
      grid-template-columns: minmax(280px, 340px) minmax(0, 1fr);
      gap: var(--demo-space-5);
      align-items: start;
    }

    .timeline-panel,
    .surface-panel {
      min-width: 0;
    }

    .toggle-debug {
      border: 1px solid var(--demo-border);
      border-radius: var(--demo-radius-sm);
      background: var(--demo-surface);
      color: var(--demo-text-muted);
      font-size: 0.8rem;
      padding: 7px 11px;
      cursor: pointer;
      white-space: nowrap;
    }

    .muted {
      color: var(--demo-text-muted);
      margin: 0;
    }

    .timeline {
      display: flex;
      flex-direction: column;
      gap: var(--demo-space-2);
      border: 1px solid var(--demo-border);
      border-radius: var(--demo-radius-lg);
      padding: var(--demo-space-4);
      min-height: 140px;
      max-height: 420px;
      overflow-y: auto;
      background: color-mix(in srgb, var(--demo-surface-soft) 80%, var(--demo-bg-elevated));
    }

    .bubble {
      max-width: 92%;
      border-radius: var(--demo-radius-md);
      padding: 10px 12px;
      font-size: 0.87rem;
      line-height: 1.45;
      border: 1px solid transparent;
    }

    .bubble.user {
      align-self: flex-end;
      background: color-mix(in srgb, var(--demo-accent) 16%, var(--demo-bg-elevated));
      color: var(--demo-text);
    }

    .bubble.assistant {
      align-self: flex-start;
      background: color-mix(in srgb, var(--demo-accent) 7%, var(--demo-bg-elevated));
      border-color: color-mix(in srgb, var(--demo-accent) 24%, var(--demo-border));
      color: var(--demo-text);
    }

    .bubble.system {
      align-self: center;
      max-width: 100%;
      width: 100%;
      background: color-mix(in srgb, var(--demo-border) 40%, var(--demo-bg-elevated));
      color: var(--demo-text-muted);
    }

    .bubble-role {
      font-weight: 700;
      margin-bottom: 4px;
      text-transform: uppercase;
      font-size: 0.64rem;
      opacity: 0.75;
    }

    .stage-title {
      margin: 0 0 var(--demo-space-3);
      font-size: var(--demo-type-label);
      color: var(--demo-text-muted);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    .surface-host {
      border: 1px solid var(--demo-border);
      border-radius: var(--demo-radius-lg);
      padding: var(--demo-space-6);
      min-height: 220px;
      background: var(--demo-surface);
      box-shadow:
        inset 0 1px 0 rgb(255 255 255 / 0.1),
        0 8px 22px rgb(15 23 42 / 0.06);
    }

    .surface-host a2ui-surface {
      display: block;
    }

    .debug-panel {
      margin-top: var(--demo-space-4);
      border-top: 1px dashed var(--demo-border);
      padding-top: var(--demo-space-4);
    }

    @media (max-width: 960px) {
      .flow-grid {
        grid-template-columns: 1fr;
      }

      .timeline {
        max-height: 260px;
      }
    }

    @media (max-width: 640px) {
      .page {
        padding: var(--demo-space-8) var(--demo-space-4) var(--demo-space-10);
      }

      .hero,
      .flow-head,
      .card,
      .flow-card {
        padding: var(--demo-space-5);
      }

      .flow-head-main {
        flex-direction: column;
        align-items: stretch;
      }

      .btn-ghost {
        width: 100%;
      }

      .surface-host {
        min-height: 180px;
        padding: var(--demo-space-4);
      }
    }

    @media (prefers-reduced-motion: reduce) {
      .card,
      .btn-secondary,
      .btn-ghost,
      .primary {
        transition: none;
      }
    }
  `
}

declare global {
  interface HTMLElementTagNameMap {
    'demo-app': DemoApp
  }
}
