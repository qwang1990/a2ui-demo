/**
 * Minimal theme for `@a2ui/lit` v0.8: each `classMap(this.theme.components…)` path
 * must be a plain object (may be empty). Missing keys → `classMap(undefined)` →
 * `TypeError: Cannot convert undefined or null to object` at `Object.keys`.
 *
 * Keep keys aligned with `a2ui-v08-catalog.ts` and with `@a2ui/lit` components
 * under `node_modules/@a2ui/lit/src/0.8/ui/*.js`.
 */
const textLikeClasses = {
  all: {},
  h1: {},
  h2: {},
  h3: {},
  h4: {},
  h5: {},
  body: {},
  caption: {},
} as const

export const DEFAULT_A2UI_THEME: Record<string, unknown> = {
  components: {
    Text: { ...textLikeClasses },
    Image: { ...textLikeClasses },
    Icon: {},
    Video: {},
    AudioPlayer: {},
    Row: {},
    Column: {},
    List: {},
    Card: {},
    Tabs: { element: {}, container: {} },
    Divider: {},
    Modal: { backdrop: {}, element: {} },
    Button: {},
    CheckBox: { container: {}, element: {}, label: {} },
    TextField: { container: {}, element: {}, label: {} },
    DateTimeInput: { container: {}, label: {}, element: {} },
    MultipleChoice: {},
    Slider: { container: {}, label: {}, element: {} },
  },
  markdown: {
    p: [],
    h1: [],
    h2: [],
    h3: [],
    h4: [],
    h5: [],
    ul: [],
    ol: [],
    li: [],
    a: [],
    strong: [],
    em: [],
  },
  additionalStyles: {},
}
