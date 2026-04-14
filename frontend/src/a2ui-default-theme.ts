/**
 * Minimal theme for `@a2ui/lit` v0.8: each `classMap(this.theme.components…)` path
 * must be a plain object (may be empty). Missing keys → `classMap(undefined)` →
 * `TypeError: Cannot convert undefined or null to object` at `Object.keys`.
 *
 * Keep keys aligned with `a2ui-v08-catalog.ts` and with `@a2ui/lit` components
 * under `node_modules/@a2ui/lit/src/0.8/ui/*.js`.
 *
 * 视觉：`classMap` 作用在各组件 **Shadow DOM** 内的节点上，宿主 `demo-app` 的样式无法穿透，
 * 因此与外壳一致的观感主要通过 `additionalStyles`（`styleMap` 内联样式）实现；其中使用
 * `var(--demo-*)` 与宿主 `:host` 上定义的 CSS 变量对齐。
 *
 * `Text` 的 `additionalStyles` 使用「按 usageHint 分支」形态（见 `text.js` 的 `#getAdditionalStyles`）。
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

const textFieldInput: Record<string, string> = {
  width: '100%',
  minHeight: '46px',
  lineHeight: '1.45',
  borderRadius: 'var(--demo-radius-md, 14px)',
  border: '1px solid var(--demo-border, #e4e4e7)',
  padding: '12px 14px',
  fontSize: 'var(--demo-type-body, 0.95rem)',
  background: 'var(--demo-surface, #ffffff)',
  color: 'var(--demo-text, #101828)',
  boxSizing: 'border-box',
  transition: 'border-color 0.16s ease, box-shadow 0.16s ease, background 0.16s ease',
}

/** `styleMap` 用扁平字符串；`Text` 为按 usageHint 分组的嵌套对象。 */
const additionalStyles: Record<string, unknown> = {
  Button: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'center',
    boxSizing: 'border-box',
    width: 'auto',
    minWidth: '176px',
    maxWidth: '100%',
    minHeight: '48px',
    padding: '0 30px',
    marginTop: '12px',
    borderRadius: 'var(--demo-radius-md, 14px)',
    border: '1px solid color-mix(in srgb, var(--demo-accent, #2563eb) 84%, #1e3a8a)',
    background:
      'linear-gradient(180deg, color-mix(in srgb, var(--demo-accent, #2563eb) 88%, #fff) 0%, var(--demo-accent, #2563eb) 100%)',
    color: '#fff',
    fontWeight: '640',
    fontSize: 'var(--demo-type-body, 0.95rem)',
    letterSpacing: '0.02em',
    lineHeight: '1',
    cursor: 'pointer',
    textAlign: 'center',
    boxShadow:
      '0 10px 20px color-mix(in srgb, var(--demo-accent, #2563eb) 34%, transparent), 0 1px 0 rgb(255 255 255 / 0.16) inset',
    transition: 'transform 0.16s ease, filter 0.16s ease',
  },
  TextField: {
    ...textFieldInput,
  },
  Text: {
    h1: {},
    h2: {},
    h3: {
      margin: '0',
      padding: '0',
      fontSize: '0.98rem',
      fontWeight: '650',
      lineHeight: '1.3',
    },
    h4: {},
    h5: {},
    h6: {},
    caption: {},
    body: {
      fontSize: 'var(--demo-type-body, 0.95rem)',
      lineHeight: '1.6',
      color: 'var(--demo-text, #101828)',
      margin: '10px 0',
      padding: '2px 0',
    },
  },
  Card: {
    borderRadius: 'var(--demo-radius-lg, 18px)',
    border: '1px solid var(--demo-border, #e4e4e7)',
    padding: '18px',
    background: 'var(--demo-surface-elevated, #ffffff)',
    boxShadow: '0 10px 26px rgb(15 23 42 / 0.08)',
  },
  CheckBox: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: '12px',
    padding: '8px 0',
    color: 'var(--demo-text, #101828)',
  },
  Slider: {
    accentColor: 'var(--demo-accent, #2563eb)',
    width: '100%',
  },
  DateTimeInput: {
    borderRadius: 'var(--demo-radius-md, 14px)',
    border: '1px solid var(--demo-border, #e4e4e7)',
    padding: '12px 14px',
    fontSize: 'var(--demo-type-body, 0.95rem)',
    background: 'var(--demo-surface, #ffffff)',
    color: 'var(--demo-text, #101828)',
    boxSizing: 'border-box',
  },
}

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
  additionalStyles,
}
