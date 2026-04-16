import { css, html, svg, LitElement, nothing } from "lit"
import { customElement, state } from "lit/decorators.js"

type NodeKind = "start" | "collect" | "end" | "logic" | "action"
type EdgeCondition = "next" | "true" | "false"
type ValidationErrorItem = { path: string; message: string }

type BaseOntology = {
  ontologyVersion?: number | string
  objectTypes?: Array<{ apiName: string; displayName?: string; properties?: Array<{ apiName: string; displayName?: string; fieldSource?: string; required?: boolean; type?: string }> }>
  logicDefinitions?: Array<{
    apiName: string
    displayName?: string
    description?: string
    implementation?: { type?: string; flagKey?: string; requestPathTemplate?: string }
  }>
  actionDefinitions?: Array<{ apiName: string; displayName?: string; description?: string }>
  [key: string]: unknown
}

type LogicParameterBinding = { fromAttr: string; templateKey: string }

type GraphNode = {
  id: string
  kind: NodeKind
  title: string
  objectTypeApiName: string
  inputPropertyApiNames: string[]
  propertyApiNames: string[]
  logicRef: string
  actionRef: string
  expression: string
  responseToAttrs: string[]
  /** logic：attrs 键 → HTTP 路径模板占位符名 */
  logicParameterBindings?: LogicParameterBinding[]
  outcome: "approved" | "denied"
  message: string
  position: { x: number; y: number }
}

type GraphEdge = { source: string; target: string; condition: EdgeCondition }
type Graph = { version: 1; nodes: GraphNode[]; edges: GraphEdge[] }
type PaletteItem = { key: string; label: string; kind: NodeKind; desc: string; setup?: Partial<GraphNode> }

const NODE_W = 240
const IN_Y = 70
/** 右侧出线点：端口圆心在距节点左缘 NODE_W - OUT_PORT_CENTER_X_OFFSET */
const OUT_PORT_CENTER_X_OFFSET = 17

function sourceWireX(nodeLeft: number): number {
  return nodeLeft + NODE_W - OUT_PORT_CENTER_X_OFFSET
}
/** 与 demo-app 开卡首页、sam_credit_card 编排默认值一致 */
const SAM_CREDIT_FLOW = "sam_credit_card"
const SAM_START_NODE_ID = "start_apply"
/** 山姆办卡：入口入参固定，与首页开卡一致 */
const SAM_FIXED_INPUTS = ["fullName", "idNumber"] as const

function sanitizeId(raw: string): string {
  return raw.trim().replace(/[^a-zA-Z0-9_]/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "")
}

/** 出线圆心相对节点顶部的 Y（与 CSS 中端口位置一致） */
function outPortY(condition: EdgeCondition): number {
  if (condition === "true") return 82
  if (condition === "false") return 104
  return 79
}

@customElement("ontology-app")
export class OntologyApp extends LitElement {
  @state() private _flowId = "sam_credit_card"
  @state() private _showTboxPanel = false
  @state() private _showAboxPanel = false
  @state() private _tboxFileText = ""
  @state() private _aboxFileText = ""
  @state() private _base = "{}\n"
  @state() private _graph: Graph = { version: 1, nodes: [], edges: [] }
  @state() private _entryNodeId = ""
  @state() private _selectedNodeId = ""
  @state() private _dragNodeId = ""
  @state() private _dragOffset = { x: 0, y: 0 }
  @state() private _wire: { srcId: string; condition: EdgeCondition; mx: number; my: number } | null = null
  @state() private _wireHoverTarget = ""
  @state() private _status = ""
  @state() private _errors: ValidationErrorItem[] = []
  @state() private _busy = false
  /** 保留服务端 aip_logic 中除 id/entry/inputs 外的字段（如 allowIncompleteGraph） */
  @state() private _aipLogicExtra: Record<string, unknown> = {}

  connectedCallback(): void {
    super.connectedCallback()
    const flow = new URLSearchParams(location.search).get("flow")
    if (flow === SAM_CREDIT_FLOW) this._flowId = flow
    window.addEventListener("pointermove", this._onGlobalPointerMove)
    window.addEventListener("pointerup", this._onGlobalPointerUp)
    void this._load()
  }
  disconnectedCallback(): void {
    window.removeEventListener("pointermove", this._onGlobalPointerMove)
    window.removeEventListener("pointerup", this._onGlobalPointerUp)
    super.disconnectedCallback()
  }

  private get _baseData(): BaseOntology { try { return JSON.parse(this._base) as BaseOntology } catch { return {} } }

  private _selectNode(id: string): void {
    this._selectedNodeId = id
  }

  /** 属性 apiName → 展示名（用于入参/采集下拉文案） */
  private _propertyLabelMap(): Map<string, string> {
    const m = new Map<string, string>()
    for (const ot of this._baseData.objectTypes || []) {
      for (const p of ot.properties || []) m.set(p.apiName, p.displayName || p.apiName)
    }
    return m
  }

  /** 流程入口入参键（写入 attrs，后续节点可读） */
  private _flowInputKeys(): string[] {
    if (this._flowId === SAM_CREDIT_FLOW) return [...SAM_FIXED_INPUTS]
    const start = this._graph.nodes.find((x) => x.kind === "start")
    return start?.inputPropertyApiNames?.length ? [...start.inputPropertyApiNames] : []
  }

  /** 是否存在从 fromId 到 toId 的有向路径（沿画布连线正向）。 */
  private _reachable(fromId: string, toId: string): boolean {
    if (fromId === toId) return true
    const adj = new Map<string, string[]>()
    for (const e of this._graph.edges) {
      if (!adj.has(e.source)) adj.set(e.source, [])
      adj.get(e.source)!.push(e.target)
    }
    const q: string[] = [fromId]
    const seen = new Set<string>([fromId])
    while (q.length) {
      const u = q.shift()!
      if (u === toId) return true
      for (const v of adj.get(u) || []) {
        if (seen.has(v)) continue
        seen.add(v)
        q.push(v)
      }
    }
    return false
  }

  /**
   * logic 路径参数下拉：仅「已有 attrs 来源」——入参 + 拓扑上游采集节点产出字段。
   * 不列出 TBox 属性名：schema 无运行时值，选错会导致路径模板拼不出或运行中断。
   */
  private _bindingSourceOptionsFor(currentNodeId: string): Array<{ value: string; label: string }> {
    const lm = this._propertyLabelMap()
    const out: Array<{ value: string; label: string }> = []
    const seen = new Set<string>()
    for (const k of this._flowInputKeys()) {
      if (seen.has(k)) continue
      seen.add(k)
      out.push({ value: k, label: `入参·${k}（${lm.get(k) || k}）` })
    }
    for (const c of this._graph.nodes) {
      if (c.kind !== "collect") continue
      if (!this._reachable(c.id, currentNodeId)) continue
      const tag = c.title === "数据补充" ? "数据补充" : "采集"
      for (const k of c.propertyApiNames || []) {
        if (seen.has(k)) continue
        seen.add(k)
        out.push({ value: k, label: `${tag}·${k}（${c.id}）` })
      }
    }
    return out.sort((a, b) => a.value.localeCompare(b.value))
  }

  private _logicTemplatePlaceholders(logicRef: string): string[] {
    const ld = (this._baseData.logicDefinitions || []).find((d) => d.apiName === logicRef)
    const tpl = ld?.implementation?.requestPathTemplate || ""
    const keys: string[] = []
    const re = /\{([a-zA-Z0-9_]+)\}/g
    let m: RegExpExecArray | null
    while ((m = re.exec(tpl)) !== null) {
      if (!keys.includes(m[1])) keys.push(m[1])
    }
    return keys
  }

  /** 选择 logic 后，按 requestPathTemplate 占位符生成/覆盖 logicParameterBindings */
  private _applyLogicRefAndSyncBindings(nodeId: string, logicRef: string): void {
    const n = this._graph.nodes.find((x) => x.id === nodeId)
    if (!n || n.kind !== "logic") return
    if (!logicRef.trim()) {
      this._updateNode(nodeId, { logicRef: "", logicParameterBindings: undefined })
      return
    }
    const placeholders = this._logicTemplatePlaceholders(logicRef)
    const opts = this._bindingSourceOptionsFor(nodeId)
    const optVals = new Set(opts.map((o) => o.value))
    const bindings: LogicParameterBinding[] = placeholders.map((tk) => ({
      templateKey: tk,
      fromAttr: optVals.has(tk) ? tk : opts[0]?.value || tk,
    }))
    this._updateNode(nodeId, {
      logicRef,
      logicParameterBindings: bindings.length ? bindings : undefined,
    })
  }

  private _setLogicBindingFromAttr(nodeId: string, templateKey: string, fromAttr: string): void {
    const n = this._graph.nodes.find((x) => x.id === nodeId)
    if (!n || n.kind !== "logic") return
    const cur = [...(n.logicParameterBindings || [])]
    const ix = cur.findIndex((b) => b.templateKey === templateKey)
    if (ix >= 0) cur[ix] = { ...cur[ix], fromAttr }
    else cur.push({ templateKey, fromAttr })
    this._updateNode(nodeId, { logicParameterBindings: cur })
  }

  private get _palette(): PaletteItem[] {
    const base = this._baseData
    const ot0 = base.objectTypes?.[0]?.apiName || ""
    const items: PaletteItem[] = [
      { key: "start", label: "开始节点", kind: "start", desc: "接收初始输入，选择入参属性。", setup: { title: "开始", objectTypeApiName: base.objectTypes?.[0]?.apiName || "", inputPropertyApiNames: [] } },
      {
        key: "supplement",
        label: "数据补充",
        kind: "collect",
        desc: "补充字段写入流程 attrs，后续 logic/采集 均可引用。",
        setup: { title: "数据补充", objectTypeApiName: ot0 || "ApplicantUser", propertyApiNames: [] },
      },
      { key: "logic", label: "逻辑判断", kind: "logic", desc: "先选 logic，再为路径占位符选择入参或上游字段。", setup: { title: "逻辑判断", expression: "" } },
    ]
    for (const a of base.actionDefinitions || []) items.push({ key: `action:${a.apiName}`, label: `动作: ${a.displayName || a.apiName}`, kind: "action", desc: a.description || "触发前端动作。", setup: { title: a.displayName || a.apiName, actionRef: a.apiName } })
    items.push({ key: "end:approved", label: "结束(通过)", kind: "end", desc: "流程通过。", setup: { title: "通过", outcome: "approved", message: "流程完成" } })
    items.push({ key: "end:denied", label: "结束(拒绝)", kind: "end", desc: "流程拒绝。", setup: { title: "拒绝", outcome: "denied", message: "不予通过" } })
    if (this._flowId === SAM_CREDIT_FLOW) return items.filter((it) => it.kind !== "start")
    return items
  }

  /** 山姆办卡 flow：画布仅保留固定「开始办理」节点（与首页开卡同一批入参）。 */
  private _applyFixedSamCreditStart(): void {
    if (this._flowId !== SAM_CREDIT_FLOW) return
    const want = [...SAM_FIXED_INPUTS]
    let nodes = [...this._graph.nodes]
    nodes = nodes.filter((n) => !(n.kind === "start" && n.id !== SAM_START_NODE_ID))
    const ix = nodes.findIndex((n) => n.id === SAM_START_NODE_ID)
    const blank: GraphNode = {
      id: SAM_START_NODE_ID,
      kind: "start",
      title: "开始办理",
      objectTypeApiName: "ApplicantUser",
      inputPropertyApiNames: want,
      propertyApiNames: [],
      logicRef: "",
      actionRef: "",
      expression: "",
      responseToAttrs: [],
      outcome: "approved",
      message: "",
      position: { x: 280, y: 220 },
    }
    if (ix >= 0 && nodes[ix].kind === "start") {
      const n = nodes[ix]
      nodes[ix] = { ...n, title: "开始办理", objectTypeApiName: "ApplicantUser", inputPropertyApiNames: want }
    } else if (ix >= 0) {
      nodes[ix] = { ...blank, position: nodes[ix].position }
    } else {
      nodes.unshift(blank)
    }
    this._graph = { ...this._graph, nodes, edges: this._graph.edges }
    this._entryNodeId = SAM_START_NODE_ID
  }

  private _extractBase(full: Record<string, unknown>): BaseOntology { const out = { ...full }; delete out.aip_logic; delete out.aip_logic_graph; delete out.nodes; return out }

  private _normalizeGraph(raw: unknown): Graph {
    if (!raw || typeof raw !== "object") return { version: 1, nodes: [], edges: [] }
    const obj = raw as Record<string, unknown>
    const nodes: GraphNode[] = []
    for (const [idx, item] of (Array.isArray(obj.nodes) ? obj.nodes : []).entries()) {
      if (!item || typeof item !== "object") continue
      const n = item as Record<string, unknown>
      const kind = String(n.kind || "") as NodeKind
      if (!["start", "collect", "end", "logic", "action"].includes(kind)) continue
      const pos = (n.position && typeof n.position === "object" ? n.position : {}) as { x?: number; y?: number }
      const propertyApiNames = Array.isArray(n.propertyApiNames) ? n.propertyApiNames.map(String) : []
      const logicParameterBindings: LogicParameterBinding[] = Array.isArray(n.logicParameterBindings)
        ? (n.logicParameterBindings as unknown[]).filter((x) => x && typeof x === "object").map((x) => {
            const o = x as Record<string, unknown>
            return { fromAttr: String(o.fromAttr || ""), templateKey: String(o.templateKey || "") }
          }).filter((b) => b.fromAttr && b.templateKey)
        : []
      nodes.push({
        id: String(n.id || `${kind}_${idx + 1}`), kind,
        title: String(n.title || `${kind}_${idx + 1}`),
        objectTypeApiName: typeof n.objectTypeApiName === "string" ? n.objectTypeApiName : "",
        inputPropertyApiNames: Array.isArray(n.inputPropertyApiNames) ? n.inputPropertyApiNames.map(String) : [],
        propertyApiNames,
        logicRef: typeof n.logicRef === "string" ? n.logicRef : "",
        actionRef: typeof n.actionRef === "string" ? n.actionRef : "",
        expression: typeof n.expression === "string" ? n.expression : "",
        responseToAttrs: Array.isArray(n.responseToAttrs) ? n.responseToAttrs.map(String) : [],
        logicParameterBindings: kind === "logic" ? (logicParameterBindings.length ? logicParameterBindings : undefined) : undefined,
        outcome: n.outcome === "denied" ? "denied" : "approved",
        message: typeof n.message === "string" ? n.message : "",
        position: { x: Number(pos.x ?? 80 + idx * 18), y: Number(pos.y ?? 80 + idx * 16) },
      })
    }
    const ids = new Set(nodes.map((n) => n.id))
    const edges: GraphEdge[] = []
    for (const item of Array.isArray(obj.edges) ? obj.edges : []) {
      if (!item || typeof item !== "object") continue
      const e = item as Record<string, unknown>
      const condition = String(e.condition || "next") as EdgeCondition
      const source = String(e.source || ""); const target = String(e.target || "")
      if (!["next", "true", "false"].includes(condition) || !source || !target || !ids.has(source) || !ids.has(target)) continue
      edges.push({ source, target, condition })
    }
    return { version: 1, nodes, edges }
  }

  private _deriveInputs() {
    const start = this._graph.nodes.find((n) => n.kind === "start")
    if (!start) return []
    const lm = this._propertyLabelMap()
    if (this._flowId === SAM_CREDIT_FLOW) {
      const desc: Record<string, string> = { fullName: "申请人姓名", idNumber: "身份证号（演示用 Mock 规则见 logicDefinitions）" }
      return [...SAM_FIXED_INPUTS].map((k) => ({
        attributeApiName: k,
        required: true,
        description: desc[k] || lm.get(k) || k,
      }))
    }
    return start.inputPropertyApiNames.map((k) => ({ attributeApiName: k, required: true, description: lm.get(k) || k }))
  }

  /** 与当前 TBox 中 logic 模板对齐 bindings（加载/保存前修复） */
  private _repairLogicBindingsIfNeeded(): void {
    let changed = false
    const nodes = this._graph.nodes.map((n) => {
      if (n.kind !== "logic" || !n.logicRef) return n
      const ph = this._logicTemplatePlaceholders(n.logicRef)
      const cur = n.logicParameterBindings || []
      const ok = ph.length === cur.length && ph.every((tk) => cur.some((b) => b.templateKey === tk))
      if (ok) return n
      changed = true
      const opts = this._bindingSourceOptionsFor(n.id)
      const optVals = new Set(opts.map((o) => o.value))
      const bindings: LogicParameterBinding[] = ph.map((tk) => ({
        templateKey: tk,
        fromAttr: optVals.has(tk) ? tk : opts[0]?.value || tk,
      }))
      return { ...n, logicParameterBindings: bindings.length ? bindings : undefined }
    })
    if (changed) this._graph = { ...this._graph, nodes }
  }

  private _graphToNodes(): Array<Record<string, unknown>> {
    const map = new Map<string, Record<string, unknown>>()
    for (const n of this._graph.nodes) {
      if (n.kind === "start") map.set(n.id, { id: n.id, kind: "collect", edges: null, next: null, objectTypeApiName: n.objectTypeApiName || null, propertyApiNames: n.inputPropertyApiNames, title: n.title, outcome: null, message: null, logicRef: null, actionRef: null })
      else if (n.kind === "collect") map.set(n.id, { id: n.id, kind: "collect", edges: null, next: null, objectTypeApiName: n.objectTypeApiName || null, propertyApiNames: n.propertyApiNames, title: n.title, outcome: null, message: null, logicRef: null, actionRef: null })
      else if (n.kind === "end") map.set(n.id, { id: n.id, kind: "terminal", edges: null, next: null, objectTypeApiName: null, propertyApiNames: null, title: n.title, outcome: n.outcome, message: n.message, logicRef: null, actionRef: null })
      else if (n.kind === "logic") {
        const row: Record<string, unknown> = {
          id: n.id,
          kind: "logic",
          edges: null,
          next: null,
          objectTypeApiName: null,
          propertyApiNames: null,
          title: n.title,
          outcome: null,
          message: null,
          logicRef: n.logicRef || null,
          actionRef: null,
          expression: n.expression || null,
        }
        if (n.responseToAttrs?.length) row.responseToAttrs = n.responseToAttrs
        if (n.logicParameterBindings?.length) row.logicParameterBindings = n.logicParameterBindings
        map.set(n.id, row)
      }
      else map.set(n.id, { id: n.id, kind: n.kind, edges: null, next: null, objectTypeApiName: null, propertyApiNames: null, title: n.title, outcome: null, message: null, logicRef: null, actionRef: n.kind === "action" ? n.actionRef : null })
    }
    for (const e of this._graph.edges) { const src = map.get(e.source); if (!src) continue; if (e.condition === "next") src.next = e.target; else { const edges = (src.edges as Record<string, string> | null) || {}; edges[e.condition] = e.target; src.edges = edges } }
    return [...map.values()]
  }

  private _composeRaw(): string {
    if (this._flowId === SAM_CREDIT_FLOW) {
      this._applyFixedSamCreditStart()
    }
    this._repairLogicBindingsIfNeeded()
    const base = this._baseData
    const entry = this._entryNodeId || (this._flowId === SAM_CREDIT_FLOW ? SAM_START_NODE_ID : this._graph.nodes[0]?.id || "")
    const aipLogic = { ...this._aipLogicExtra, id: this._flowId, entry, inputs: this._deriveInputs() }
    return `${JSON.stringify({ ...base, aip_logic: aipLogic, aip_logic_graph: this._graph, nodes: this._graphToNodes() }, null, 2)}\n`
  }

  private async _fetchTboxFile(): Promise<void> {
    try {
      const r = await fetch("/api/ontology/tbox/sam_credit")
      if (!r.ok) {
        this._tboxFileText = `加载失败 HTTP ${r.status}`
        return
      }
      const data = (await r.json()) as unknown
      this._tboxFileText = JSON.stringify(data, null, 2)
    } catch (e) {
      this._tboxFileText = e instanceof Error ? e.message : "加载异常"
    }
  }

  private async _fetchAboxFile(): Promise<void> {
    try {
      const r = await fetch("/api/ontology/abox/sam_credit")
      if (!r.ok) {
        this._aboxFileText = `加载失败 HTTP ${r.status}`
        return
      }
      const data = (await r.json()) as unknown
      this._aboxFileText = JSON.stringify(data, null, 2)
    } catch (e) {
      this._aboxFileText = e instanceof Error ? e.message : "加载异常"
    }
  }

  private async _toggleTboxPanel(): Promise<void> {
    const next = !this._showTboxPanel
    this._showTboxPanel = next
    if (next) await this._fetchTboxFile()
  }

  private async _toggleAboxPanel(): Promise<void> {
    const next = !this._showAboxPanel
    this._showAboxPanel = next
    if (next) await this._fetchAboxFile()
  }

  private async _load(): Promise<void> {
    this._busy = true; this._status = ""; this._errors = []
    try {
      const r = await fetch(`/api/ontology/${encodeURIComponent(this._flowId)}`)
      if (!r.ok) { this._status = `加载失败：HTTP ${r.status}`; return }
      const body = (await r.json()) as { raw?: string }
      const full = JSON.parse(body.raw || "{}") as Record<string, unknown>
      this._base = `${JSON.stringify(this._extractBase(full), null, 2)}\n`
      this._aipLogicExtra = {}
      const al = full.aip_logic && typeof full.aip_logic === "object" ? (full.aip_logic as Record<string, unknown>) : {}
      for (const [k, v] of Object.entries(al)) {
        if (!["id", "entry", "inputs"].includes(k)) this._aipLogicExtra[k] = v
      }
      this._graph = this._normalizeGraph(full.aip_logic_graph)
      const entryFromServer = typeof (full.aip_logic as { entry?: string } | undefined)?.entry === "string" ? String((full.aip_logic as { entry: string }).entry).trim() : ""
      if (this._flowId === SAM_CREDIT_FLOW) {
        this._applyFixedSamCreditStart()
        this._repairLogicBindingsIfNeeded()
        this._entryNodeId = SAM_START_NODE_ID
        this._selectedNodeId = this._graph.nodes.some((x) => x.id === SAM_START_NODE_ID) ? SAM_START_NODE_ID : (this._graph.nodes[0]?.id || "")
      } else {
        this._entryNodeId = entryFromServer || this._graph.nodes[0]?.id || ""
        this._selectedNodeId = this._graph.nodes.find((x) => x.id === entryFromServer)?.id || this._graph.nodes[0]?.id || ""
      }
      this._status = "已加载"
    } catch (e) { this._status = e instanceof Error ? e.message : "加载异常" }
    finally { this._busy = false }
  }
  private async _validate(): Promise<void> {
    this._busy = true; this._status = ""; this._errors = []
    try {
      const r = await fetch("/api/ontology/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ raw: this._composeRaw() }) })
      const body = (await r.json()) as { ok?: boolean; errors?: ValidationErrorItem[] }
      if (body.ok) this._status = "校验通过"; else { this._status = "校验失败"; this._errors = body.errors || [] }
    } catch (e) { this._status = e instanceof Error ? e.message : "校验失败" }
    finally { this._busy = false }
  }
  private async _save(): Promise<void> {
    this._busy = true; this._status = ""; this._errors = []
    try {
      const r = await fetch(`/api/ontology/${encodeURIComponent(this._flowId)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ raw: this._composeRaw() }) })
      const body = (await r.json().catch(() => ({}))) as { detail?: string | { errors?: ValidationErrorItem[] } }
      if (!r.ok) { this._status = "保存失败"; if (typeof body.detail === "string") this._status = body.detail; if (body.detail && typeof body.detail === "object" && Array.isArray(body.detail.errors)) this._errors = body.detail.errors; return }
      this._status = "已保存并应用"
    } catch (e) { this._status = e instanceof Error ? e.message : "保存失败" }
    finally { this._busy = false }
  }

  private _addNode(item: PaletteItem, x: number, y: number): void {
    const seed = sanitizeId(item.key.split(":").pop() || item.kind) || item.kind
    const used = new Set(this._graph.nodes.map((n) => n.id))
    let idx = 1; let id = `${seed}_${idx}`
    while (used.has(id)) { idx += 1; id = `${seed}_${idx}` }
    const s = item.setup || {}
    const node: GraphNode = {
      id,
      kind: item.kind,
      title: String(s.title || item.label),
      objectTypeApiName: String(s.objectTypeApiName || ""),
      inputPropertyApiNames: Array.isArray(s.inputPropertyApiNames) ? s.inputPropertyApiNames.map(String) : [],
      propertyApiNames: Array.isArray(s.propertyApiNames) ? s.propertyApiNames.map(String) : [],
      logicRef: String(s.logicRef || ""),
      actionRef: String(s.actionRef || ""),
      expression: String(s.expression || ""),
      responseToAttrs: Array.isArray(s.responseToAttrs) ? s.responseToAttrs.map(String) : [],
      logicParameterBindings: item.kind === "logic" ? [] : undefined,
      outcome: s.outcome === "denied" ? "denied" : "approved",
      message: String(s.message || ""),
      position: { x, y },
    }
    this._graph = { ...this._graph, nodes: [...this._graph.nodes, node] }
    this._selectNode(id)
    if (!this._entryNodeId) this._entryNodeId = id
  }

  private _onPaletteDragStart(ev: DragEvent, item: PaletteItem): void { ev.dataTransfer?.setData("application/aip-node", item.key) }
  private _onCanvasDrop(ev: DragEvent): void {
    ev.preventDefault()
    const item = this._palette.find((p) => p.key === (ev.dataTransfer?.getData("application/aip-node") || ""))
    if (!item) return
    const host = this.renderRoot.querySelector(".board") as HTMLElement | null
    if (!host) return
    const rect = host.getBoundingClientRect()
    this._addNode(item, Math.max(8, ev.clientX - rect.left + host.scrollLeft - NODE_W / 2), Math.max(8, ev.clientY - rect.top + host.scrollTop - 40))
  }

  /* ───── node drag ───── */
  private _startNodeDrag(ev: PointerEvent, nodeId: string): void {
    if (this._wire) return
    const node = this._graph.nodes.find((n) => n.id === nodeId)
    if (!node) return
    this._selectNode(nodeId); this._dragNodeId = nodeId
    const host = this.renderRoot.querySelector(".board") as HTMLElement | null
    if (!host) return
    const rect = host.getBoundingClientRect()
    this._dragOffset = { x: ev.clientX - rect.left + host.scrollLeft - node.position.x, y: ev.clientY - rect.top + host.scrollTop - node.position.y }
  }

  /* ───── wire drag (connection) ───── */
  private _startWire(ev: PointerEvent, srcId: string, condition: EdgeCondition): void {
    ev.stopPropagation(); ev.preventDefault()
    const host = this.renderRoot.querySelector(".board") as HTMLElement | null
    if (!host) return
    const rect = host.getBoundingClientRect()
    this._wire = { srcId, condition, mx: ev.clientX - rect.left + host.scrollLeft, my: ev.clientY - rect.top + host.scrollTop }
  }

  private _nearestPortIn(mx: number, my: number, excludeId: string): string {
    const HIT_RADIUS = 30
    let best = ""; let bestDist = HIT_RADIUS
    for (const n of this._graph.nodes) {
      if (n.id === excludeId) continue
      const cx = n.position.x; const cy = n.position.y + IN_Y
      const d = Math.hypot(mx - cx, my - cy)
      if (d < bestDist) { bestDist = d; best = n.id }
    }
    return best
  }

  private _onGlobalPointerMove = (ev: PointerEvent): void => {
    const host = this.renderRoot.querySelector(".board") as HTMLElement | null
    if (!host) return
    const rect = host.getBoundingClientRect()
    const bx = ev.clientX - rect.left + host.scrollLeft
    const by = ev.clientY - rect.top + host.scrollTop
    if (this._dragNodeId) {
      const x = Math.max(0, bx - this._dragOffset.x)
      const y = Math.max(0, by - this._dragOffset.y)
      this._graph = { ...this._graph, nodes: this._graph.nodes.map((n) => n.id === this._dragNodeId ? { ...n, position: { x, y } } : n) }
    }
    if (this._wire) {
      this._wire = { ...this._wire, mx: bx, my: by }
      this._wireHoverTarget = this._nearestPortIn(bx, by, this._wire.srcId)
    }
  }

  private _onGlobalPointerUp = (): void => {
    if (this._dragNodeId) { this._dragNodeId = "" }
    if (this._wire) {
      if (this._wireHoverTarget) this._finishWire(this._wireHoverTarget)
      this._wire = null; this._wireHoverTarget = ""
    }
  }

  private _finishWire(targetId: string): void {
    const w = this._wire
    if (!w || w.srcId === targetId) return
    const source = this._graph.nodes.find((n) => n.id === w.srcId)
    if (!source) return
    const isBranch = source.kind === "logic"
    if (isBranch && w.condition === "next") return
    if (!isBranch && w.condition !== "next") return
    let edges = this._graph.edges.filter((e) => !(e.source === w.srcId && e.condition === w.condition))
    edges.push({ source: w.srcId, target: targetId, condition: w.condition })
    this._graph = { ...this._graph, edges }
  }

  private _wirePath(): string {
    if (!this._wire) return ""
    const src = this._graph.nodes.find((n) => n.id === this._wire!.srcId)
    if (!src) return ""
    const sx = sourceWireX(src.position.x); const sy = src.position.y + outPortY(this._wire.condition)
    let tx = this._wire.mx; let ty = this._wire.my
    if (this._wireHoverTarget) {
      const tn = this._graph.nodes.find((n) => n.id === this._wireHoverTarget)
      if (tn) { tx = tn.position.x; ty = tn.position.y + IN_Y }
    }
    const dx = Math.max(40, Math.abs(tx - sx) * 0.35)
    return `M ${sx} ${sy} C ${sx + dx} ${sy}, ${tx - dx} ${ty}, ${tx} ${ty}`
  }

  private _removeNode(id: string): void {
    if (this._flowId === SAM_CREDIT_FLOW && id === SAM_START_NODE_ID) return
    this._graph = { ...this._graph, nodes: this._graph.nodes.filter((n) => n.id !== id), edges: this._graph.edges.filter((e) => e.source !== id && e.target !== id) }
    if (this._entryNodeId === id) this._entryNodeId = this._flowId === SAM_CREDIT_FLOW ? SAM_START_NODE_ID : (this._graph.nodes[0]?.id || "")
    if (this._selectedNodeId === id) this._selectedNodeId = ""
  }
  private _updateNode(id: string, patch: Partial<GraphNode>): void { this._graph = { ...this._graph, nodes: this._graph.nodes.map((n) => n.id === id ? { ...n, ...patch } : n) } }

  private _edgePath(e: GraphEdge): string {
    const s = this._graph.nodes.find((n) => n.id === e.source); const t = this._graph.nodes.find((n) => n.id === e.target)
    if (!s || !t) return ""
    const sx = sourceWireX(s.position.x); const sy = s.position.y + outPortY(e.condition)
    const tx = t.position.x; const ty = t.position.y + IN_Y
    const dx = Math.max(60, Math.abs(tx - sx) * 0.4)
    return `M ${sx} ${sy} C ${sx + dx} ${sy}, ${tx - dx} ${ty}, ${tx} ${ty}`
  }

  /* ───── inspector panel ───── */
  private _renderInspector() {
    const n = this._graph.nodes.find((x) => x.id === this._selectedNodeId)
    if (!n) return html`<p class="muted">选择一个节点后可编辑配置。</p>`
    const objects = this._baseData.objectTypes || []; const cur = objects.find((o) => o.apiName === n.objectTypeApiName); const props = cur?.properties || []
    return html`
      <h2 class="inspector-title">节点配置</h2>
      <p class="muted"><code>${n.id}</code> · ${n.kind}</p>
      <label>标题</label><input .value=${n.title} @input=${(e: Event) => this._updateNode(n.id, { title: (e.target as HTMLInputElement).value })} />

      ${n.kind === "start" && this._flowId === SAM_CREDIT_FLOW
        ? html`
        <p class="muted small">入口入参<strong>固定</strong>为 <code>fullName</code>、<code>idNumber</code>（与首页开卡一致）；入参即写入流程 <code>attrs</code>，后续节点均可引用。</p>
        <div class="readonly-box">
          <div><strong>对象类型</strong> ApplicantUser（固定）</div>
          <div><strong>出参 / attrs 键</strong> ${SAM_FIXED_INPUTS.map((k) => html`<code>${k}</code>`)}</div>
        </div>
      `
        : n.kind === "start"
          ? html`
        <label>对象类型</label><select .value=${n.objectTypeApiName} @change=${(e: Event) => this._updateNode(n.id, { objectTypeApiName: (e.target as HTMLSelectElement).value, inputPropertyApiNames: [] })}><option value="">请选择</option>${objects.map((o) => html`<option value=${o.apiName}>${o.displayName || o.apiName}</option>`)}</select>
        <label>入参属性(从TBox选)</label>
        <div class="checks">${props.map((p) => { const on = n.inputPropertyApiNames.includes(p.apiName); return html`<label class="check"><input type="checkbox" .checked=${on} @change=${(e: Event) => { const s = new Set(n.inputPropertyApiNames); (e.target as HTMLInputElement).checked ? s.add(p.apiName) : s.delete(p.apiName); this._updateNode(n.id, { inputPropertyApiNames: [...s] }) }} /><span>${p.displayName || p.apiName} <code>${p.type || "string"}</code></span></label>` })}</div>
      `
          : nothing}

      ${n.kind === "collect" ? html`
        ${n.title === "数据补充" ? html`<p class="muted small">勾选字段将合并进 <code>attrs</code>；仅下游节点在配置 logic 路径参数时可选用。</p>` : nothing}
        <label>对象类型</label><select .value=${n.objectTypeApiName} @change=${(e: Event) => this._updateNode(n.id, { objectTypeApiName: (e.target as HTMLSelectElement).value, propertyApiNames: [] })}><option value="">请选择</option>${objects.map((o) => html`<option value=${o.apiName}>${o.displayName || o.apiName}</option>`)}</select>
        <label>${n.title === "数据补充" ? "补充字段" : "采集属性"}(从TBox选)</label>
        <div class="checks">${props.map((p) => { const on = n.propertyApiNames.includes(p.apiName); return html`<label class="check"><input type="checkbox" .checked=${on} @change=${(e: Event) => { const s = new Set(n.propertyApiNames); (e.target as HTMLInputElement).checked ? s.add(p.apiName) : s.delete(p.apiName); this._updateNode(n.id, { propertyApiNames: [...s] }) }} /><span>${p.displayName || p.apiName} <code>${p.type || "string"}</code></span></label>` })}</div>
      ` : nothing}

      ${n.kind === "logic" ? (() => {
        const placeholders = this._logicTemplatePlaceholders(n.logicRef)
        const bindOpts = this._bindingSourceOptionsFor(n.id)
        return html`
        <div class="logic-builder">
          <label>logic（选择逻辑定义）</label>
          <select .value=${n.logicRef} @change=${(e: Event) => this._applyLogicRefAndSyncBindings(n.id, (e.target as HTMLSelectElement).value)}>
            <option value="">请选择</option>
            ${(this._baseData.logicDefinitions || []).map((d) => html`<option value=${d.apiName}>${d.displayName || d.apiName}</option>`)}
          </select>

          <p class="logic-builder-title">路径参数（按模板占位符）</p>
          <p class="muted small">每个 <code>{占位符}</code> 映射到<strong>此时已有值</strong>的 <code>attrs</code> 键：仅<strong>入参</strong>与<strong>上游采集/数据补充</strong>已勾选的字段（不列 TBox 全量属性，避免无值跑不通）。</p>
          ${!n.logicRef
            ? html`<p class="muted small">请先选择 logic。</p>`
            : placeholders.length === 0
              ? html`<p class="muted small">当前逻辑无路径占位符（检查 TBox 中该 logic 的 <code>requestPathTemplate</code>）。</p>`
              : placeholders.map((tk) => {
                  const b = (n.logicParameterBindings || []).find((x) => x.templateKey === tk)
                  const fromAttr = b?.fromAttr || ""
                  return html`<label><code>{${tk}}</code> ← 来源</label>
              <select .value=${fromAttr} @change=${(e: Event) => this._setLogicBindingFromAttr(n.id, tk, (e.target as HTMLSelectElement).value)}>
                <option value="">请选择</option>
                ${bindOpts.map((o) => html`<option value=${o.value}>${o.label}</option>`)}
              </select>`
                })}
        </div>
      ` })() : nothing}

      ${n.kind === "action" ? html`
        <label>actionRef</label><select .value=${n.actionRef} @change=${(e: Event) => this._updateNode(n.id, { actionRef: (e.target as HTMLSelectElement).value })}><option value="">请选择</option>${(this._baseData.actionDefinitions || []).map((d) => html`<option value=${d.apiName}>${d.displayName || d.apiName}</option>`)}</select>
      ` : nothing}

      ${n.kind === "end" ? html`
        <label>结果状态</label><select .value=${n.outcome} @change=${(e: Event) => this._updateNode(n.id, { outcome: (e.target as HTMLSelectElement).value as "approved" | "denied" })}><option value="approved">✅ approved (通过)</option><option value="denied">❌ denied (拒绝)</option></select>
        <label>结束文案</label><input .value=${n.message} @input=${(e: Event) => this._updateNode(n.id, { message: (e.target as HTMLInputElement).value })} />
      ` : nothing}
    `
  }

  /* ───── node card summary ───── */
  private _nodeSummary(n: GraphNode) {
    if (n.kind === "start") return html`<p>入参：${n.inputPropertyApiNames.join(", ") || "未选"}</p>`
    if (n.kind === "collect")
      return html`<p>${n.title === "数据补充" ? "补充" : "采集"}：${n.propertyApiNames.join(", ") || "未选"}</p>`
    if (n.kind === "logic") return html`<p><code>${n.logicRef || "logicRef?"}</code></p>`
    if (n.kind === "action") return html`<p>action: ${n.actionRef || "未选"}</p>`
    if (n.kind === "end") return html`<p>${n.outcome === "approved" ? "✅" : "❌"} ${n.outcome} / ${n.message || "-"}</p>`
    return nothing
  }

  render() {
    const wirePreview = this._wire ? this._wirePath() : ""
    return html`
      <div class="page">
        <header class="top"><div><p class="eyebrow">AIP Logic Studio</p><h1>本体驱动流程编排</h1>        <p class="sub">从组件库拖入画布 → 连线 → 右侧配置节点。<strong>保存并应用</strong>会持久化 <code>ontology/flows/sam_credit_card.json</code>（及共享 TBox）。logic 路径参数下拉仅含<strong>入参</strong>与<strong>拓扑上游</strong>采集节点字段。TBox / ABox 为 Mock。<span class="hint-line">山姆「开始办理」入参固定：姓名、身份证。</span></p></div><a class="btn" href="/">返回首页</a></header>
        <section class="card tools"><span class="flow-label">Flow：<code>sam_credit_card</code>（山姆信用卡开卡）</span><button class="btn" ?disabled=${this._busy} @click=${() => void this._load()}>重新加载</button><button class="btn" ?disabled=${this._busy} @click=${() => void this._validate()}>校验</button><button class="btn primary" ?disabled=${this._busy} @click=${() => void this._save()}>保存并应用</button><button type="button" class="btn" @click=${() => void this._toggleTboxPanel()}>${this._showTboxPanel ? "隐藏 TBox 文件" : "查看 TBox（文件）"}</button><button type="button" class="btn" @click=${() => void this._toggleAboxPanel()}>${this._showAboxPanel ? "隐藏 ABox 文件" : "查看 ABox（文件）"}</button>${this._status ? html`<span class="status">${this._status}</span>` : nothing}</section>
        ${this._showTboxPanel ? html`<section class="card file-view"><h2>TBox（只读 · ontology/tbox/sam_credit.json）</h2><textarea class="file-json" readonly spellcheck="false" .value=${this._tboxFileText}></textarea></section>` : nothing}
        ${this._showAboxPanel ? html`<section class="card file-view"><h2>ABox（只读 · ontology/abox/sam_credit.json）</h2><textarea class="file-json" readonly spellcheck="false" .value=${this._aboxFileText}></textarea></section>` : nothing}
        ${this._errors.length ? html`<section class="card"><ul class="errors">${this._errors.map((e) => html`<li><code>${e.path || "(root)"}</code> - ${e.message}</li>`)}</ul></section>` : nothing}
        <section class="layout">
          <div class="layout-main">
            <aside class="card palette-aside"><h2>组件库</h2><p class="sub">拖入画布生成节点。</p>${this._palette.map((item) => html`<div class="palette" draggable="true" @dragstart=${(e: DragEvent) => this._onPaletteDragStart(e, item)}><strong>${item.label}</strong><p>${item.desc}</p></div>`)}</aside>
            <div class="card canvas-card">
              <div class="canvas-head"><h2>画布</h2><span class="muted">入口：<code>${this._entryNodeId || "未设置"}</code></span>${this._wire ? html`<span class="tag">拖线中 …</span>` : nothing}</div>
              <div class="board" @dragover=${(e: DragEvent) => e.preventDefault()} @drop=${(e: DragEvent) => this._onCanvasDrop(e)}>
                <svg class="edges" width="3000" height="2000">
                  ${this._graph.edges.map((e) => { const d = this._edgePath(e); return d ? svg`<path d=${d} class=${e.condition}/>` : nothing })}
                  ${wirePreview ? svg`<path d=${wirePreview} class="wire-preview"/>` : nothing}
                </svg>
                ${this._graph.nodes.map((n) => { const isHoverTarget = this._wire && this._wireHoverTarget === n.id; return html`
                  <div class=${`node kind-${n.kind} ${this._selectedNodeId === n.id ? "active" : ""} ${isHoverTarget ? "wire-target" : ""}`} style=${`left:${n.position.x}px;top:${n.position.y}px;`} @click=${() => this._selectNode(n.id)}>
                    <div class="head" @pointerdown=${(e: PointerEvent) => this._startNodeDrag(e, n.id)}><strong>${n.title}</strong><button class="icon danger" @click=${(e: Event) => { e.stopPropagation(); this._removeNode(n.id) }}>×</button></div>
                    ${this._nodeSummary(n)}
                    <div class=${`port port-in ${isHoverTarget ? "port-in-hover" : ""}`}></div>
                    ${n.kind === "logic"
                      ? html`<div class="logic-out-row logic-out-true">
                            <span class="logic-out-label">是</span><span class="logic-out-sub">yes</span>
                            <div class="port port-out port-true" @pointerdown=${(e: PointerEvent) => this._startWire(e, n.id, "true")} title="是（true）分支"></div>
                          </div>
                          <div class="logic-out-row logic-out-false">
                            <span class="logic-out-label">否</span><span class="logic-out-sub">no</span>
                            <div class="port port-out port-false" @pointerdown=${(e: PointerEvent) => this._startWire(e, n.id, "false")} title="否（false）分支"></div>
                          </div>`
                      : n.kind !== "end"
                        ? html`<div class="port port-out port-next" @pointerdown=${(e: PointerEvent) => this._startWire(e, n.id, "next")} title="next(下一步)"></div>`
                        : nothing}
                  </div>
                ` })}
              </div>
            </div>
            <aside class="card inspector-aside">${this._renderInspector()}</aside>
          </div>
        </section>
      </div>
    `
  }

  static styles = css`
    :host {
      display:flex;
      flex-direction:column;
      flex:1 1 auto;
      min-height:0;
      height:100%;
      background:#f4f7fc;
      color:#101828;
      font-family:Inter,'SF Pro Text','Segoe UI',system-ui,sans-serif;
      box-sizing:border-box;
    }
    .page {
      width:100%;
      max-width:none;
      margin:0;
      padding:10px 12px 12px;
      box-sizing:border-box;
      display:flex;
      flex-direction:column;
      flex:1;
      min-height:0;
    }
    .top { display:flex; justify-content:space-between; align-items:flex-start; gap:14px; margin-bottom:12px; }
    .eyebrow { margin:0; font-size:12px; color:#667085; text-transform:uppercase; letter-spacing:.12em; font-weight:700; }
    h1 { margin:6px 0; font-size:28px; } h2 { margin:0 0 8px; font-size:16px; } h3 { margin:0 0 8px; font-size:13px; }
    .sub,.muted { margin:0; color:#667085; font-size:12px; }
    .hint-line { color:#475467; font-weight:500; }
    .card { border:1px solid #dbe3f0; background:#fff; border-radius:14px; box-shadow:0 8px 24px rgb(15 23 42 / .08); padding:14px; box-sizing:border-box; }
    .tools { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-bottom:12px; }
    .flow-label { font-size:13px; color:#344054; margin-right:8px; }
    .file-view h2 { margin:0 0 10px; font-size:15px; }
    .file-json { width:100%; min-height:220px; max-height:min(40vh,420px); font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,monospace; font-size:11px; line-height:1.45; border-radius:10px; border:1px solid #cfd9ea; padding:10px; box-sizing:border-box; resize:vertical; background:#fafbfc; color:#1f2937; }
    .btn { border:1px solid #b8c5dc; background:#fff; color:#1f2937; border-radius:10px; font-size:13px; padding:8px 12px; cursor:pointer; text-decoration:none; }
    .btn.primary { background:#2563eb; border-color:#1e55cc; color:#fff; }
    .status { font-size:13px; color:#344054; }
    textarea { width:100%; min-height:200px; border-radius:10px; border:1px solid #cfd9ea; font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,monospace; font-size:12px; padding:10px; box-sizing:border-box; resize:vertical; }
    .errors { margin:0; padding-left:18px; color:#b42318; font-size:12px; }
    .layout { display:flex; flex-direction:column; gap:10px; align-items:stretch; flex:1; min-height:0; }
    .layout-main {
      display:grid;
      grid-template-columns:min(200px,22vw) 1fr clamp(240px,30vw,420px);
      gap:10px;
      align-items:stretch;
      flex:1;
      min-height:0;
    }
    .palette-aside { align-self:stretch; max-height:100%; overflow:auto; }
    .canvas-card { min-width:0; display:flex; flex-direction:column; flex:1; min-height:0; }
    .inspector-aside {
      min-width:0;
      display:flex;
      flex-direction:column;
      min-height:0;
      max-height:100%;
      overflow:auto;
    }
    .palette { border:1px dashed #c6d3ec; border-radius:10px; padding:10px; margin-bottom:8px; cursor:grab; background:#f8faff; }
    .palette strong { font-size:13px; } .palette p { margin:6px 0 0; font-size:12px; color:#667085; line-height:1.35; }
    .canvas-head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:10px; }
    .tag { font-size:12px; color:#2563eb; background:#eaf2ff; border-radius:8px; padding:4px 8px; }
    .board {
      position:relative;
      flex:1;
      min-height:0;
      height:100%;
      border-radius:12px;
      border:1px dashed #bfcce4;
      background:linear-gradient(90deg, rgb(226 234 248 / .45) 1px, transparent 1px) 0 0 / 24px 24px,
        linear-gradient(rgb(226 234 248 / .45) 1px, transparent 1px) 0 0 / 24px 24px, #f8faff;
      overflow:auto;
    }
    .edges { position:absolute; top:0; left:0; width:3000px; height:2000px; pointer-events:none; overflow:visible; }
    .edges path { stroke:#5b84d6; stroke-width:2.5; fill:none; stroke-linecap:round; }
    .edges path.next { stroke:#5b84d6; }
    .edges path.true { stroke:#22c55e; } .edges path.false { stroke:#f59e0b; }
    .edges path.wire-preview { stroke:#2563eb; stroke-width:3; stroke-dasharray:8 5; opacity:.8; }
    .node { position:absolute; width:${NODE_W}px; border:1px solid #b7c5df; background:#fff; border-radius:12px; box-shadow:0 6px 18px rgb(15 23 42 / .1); padding:8px 10px 10px; box-sizing:border-box; }
    .node:not(.kind-end) { padding-bottom: 26px; }
    .kind-logic { min-height: 118px; padding-bottom: 12px; }
    .kind-start,.kind-collect,.kind-action { min-height: 96px; }
    .node.active { border-color:#2563eb; box-shadow:0 0 0 2px rgb(37 99 235 / .2); }
    .kind-start { border-left:4px solid #22c55e; }
    .kind-collect { border-left:4px solid #6366f1; }
    .kind-end { border-left:4px solid #ef4444; }
    .kind-logic { border-left:4px solid #8b5cf6; }
    .kind-action { border-left:4px solid #f59e0b; }
    .head { display:flex; justify-content:space-between; align-items:center; gap:8px; cursor:move; user-select:none; }
    .head strong { font-size:13px; }
    .node p { margin:4px 0; font-size:11px; color:#52607a; line-height:1.35; word-break:break-word; }
    .icon { width:22px; height:22px; border-radius:8px; border:1px solid #d8e1f1; background:#fff; cursor:pointer; display:flex; align-items:center; justify-content:center; font-size:14px; line-height:1; }
    .danger { color:#b42318; border-color:#efc0bc; background:#fff6f5; }
    .node.wire-target { outline:2px dashed #2563eb; outline-offset:3px; }
    .port { position:absolute; width:14px; height:14px; border-radius:50%; border:2.5px solid #fff; cursor:crosshair; z-index:2; box-shadow:0 0 0 1px rgba(0,0,0,.12); transition:transform .1s,box-shadow .1s; }
    .port-in { left:-8px; top:${IN_Y - 7}px; background:#6b7280; }
    .port-in-hover { transform:scale(2); background:#2563eb; box-shadow:0 0 0 4px rgba(37,99,235,.35); }
    .port-out { right:10px; }
    .port-out:hover { transform:scale(1.35); }
    .port-next { top:72px; background:#2563eb; }
    .kind-logic .logic-out-row {
      position:absolute;
      right:10px;
      display:flex;
      align-items:center;
      gap:5px;
      height:14px;
      line-height:1;
    }
    .kind-logic .logic-out-row.logic-out-true { top:75px; }
    .kind-logic .logic-out-row.logic-out-false { top:97px; }
    .kind-logic .logic-out-label { font-size:11px; font-weight:700; color:#15803d; letter-spacing:0.02em; }
    .kind-logic .logic-out-row.logic-out-false .logic-out-label { color:#c2410c; }
    .kind-logic .logic-out-sub { font-size:9px; font-weight:600; color:#94a3b8; text-transform:uppercase; }
    .kind-logic .logic-out-row .port { position:static; margin:0; flex-shrink:0; }
    .kind-logic .logic-out-row .port.port-true { background:#22c55e; }
    .kind-logic .logic-out-row .port.port-false { background:#f59e0b; }
    .inspector-title { margin:0 0 10px; font-size:16px; color:#101828; }
    label { display:block; margin-top:10px; margin-bottom:4px; font-size:12px; color:#667085; font-weight:600; }
    input,select { width:100%; box-sizing:border-box; border-radius:8px; border:1px solid #cfd9ea; background:#fff; font-size:12px; padding:7px 8px; }
    .checks { display:flex; flex-direction:column; gap:5px; border:1px solid #e1e8f4; border-radius:8px; padding:8px; max-height:220px; overflow:auto; }
    .check { margin:0; display:grid; grid-template-columns:16px 1fr; align-items:center; gap:6px; font-size:12px; color:#475467; font-weight:500; }
    .check input { width:14px; height:14px; margin:0; padding:0; }
    .check code { color:#667085; font-size:10px; }
    .small { font-size:11px; line-height:1.45; }
    .readonly-box {
      border:1px solid #e1e8f4;
      border-radius:10px;
      padding:10px 12px;
      background:#f8fafc;
      font-size:12px;
      color:#475467;
      line-height:1.5;
    }
    .readonly-box code { margin-right:6px; font-size:11px; }
    .logic-builder { border:1px solid #e4ebf7; border-radius:10px; padding:10px; background:#fafcff; }
    .logic-builder-title { margin:0 0 6px; font-size:13px; font-weight:700; color:#344054; }
    .bind-row { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:8px; font-size:12px; }
    .bind-key { min-width:100px; color:#0ea5e9; }
    .bind-arrow { color:#667085; }
    .bind-input { width:120px; border-radius:8px; border:1px solid #cfd9ea; padding:6px 8px; font-size:12px; }
    .btn.tiny { padding:5px 9px; font-size:11px; margin-top:6px; }
    @media (max-width:900px) {
      .layout-main { grid-template-columns:1fr; }
      .canvas-card { order:1; }
      .inspector-aside { order:2; max-height:min(360px,42vh); }
      .palette-aside { order:3; }
    }
  `
}

declare global {
  interface HTMLElementTagNameMap { "ontology-app": OntologyApp }
}
