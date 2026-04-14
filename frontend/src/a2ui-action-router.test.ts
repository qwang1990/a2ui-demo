import { describe, expect, it, vi } from 'vitest'

import { A2uiActionRouter } from './a2ui-action-router'

describe('A2uiActionRouter', () => {
  it('dispatches submit_collect with resolved context', () => {
    const send = vi.fn()
    const router = new A2uiActionRouter({
      getThreadId: () => 'th-1',
      getFlowId: () => 'flow-1',
      getSurfaceId: () => 'main',
      readPathValue: (path: string) => (path === '/user/phone' ? '13800138000' : ''),
      send,
    })
    const ok = router.dispatch({
      action: {
        name: 'submit_collect',
        context: [{ key: 'phone', value: { path: '/user/phone' } }],
      },
    })
    expect(ok).toBe(true)
    expect(send).toHaveBeenCalledWith({
      type: 'a2ui_event',
      thread_id: 'th-1',
      flow_id: 'flow-1',
      name: 'submit_collect',
      context: { phone: '13800138000' },
    })
  })

  it('dispatches confirm suffix with empty context', () => {
    const send = vi.fn()
    const router = new A2uiActionRouter({
      getThreadId: () => 'th-2',
      getFlowId: () => 'flow-2',
      getSurfaceId: () => 'main',
      readPathValue: () => null,
      send,
    })
    const ok = router.dispatch({
      action: { name: 'face_confirm' },
    })
    expect(ok).toBe(true)
    expect(send).toHaveBeenCalledWith({
      type: 'a2ui_event',
      thread_id: 'th-2',
      flow_id: 'flow-2',
      name: 'face_confirm',
      context: {},
    })
  })

  it('does not send when interaction is blocked', () => {
    const send = vi.fn()
    const router = new A2uiActionRouter({
      getThreadId: () => 'th-4',
      getFlowId: () => 'flow-4',
      getSurfaceId: () => 'main',
      readPathValue: () => null,
      send,
      isInteractionBlocked: () => true,
    })
    const ok = router.dispatch({
      action: { name: 'face_confirm' },
    })
    expect(ok).toBe(false)
    expect(send).not.toHaveBeenCalled()
  })

  it('returns false for unknown action', () => {
    const send = vi.fn()
    const router = new A2uiActionRouter({
      getThreadId: () => 'th-3',
      getFlowId: () => 'flow-3',
      getSurfaceId: () => 'main',
      readPathValue: () => null,
      send,
    })
    const ok = router.dispatch({
      action: { name: 'unknown_action' },
    })
    expect(ok).toBe(false)
    expect(send).not.toHaveBeenCalled()
  })
})
