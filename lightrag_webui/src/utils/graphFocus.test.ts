import { expect, test } from 'bun:test'
import { isCypherFocusActive, withGraphOpacity } from './graphFocus'

test('converts supported graph colors into transparent renderer colors', () => {
  expect(withGraphOpacity('#E2E2E2', 0.18)).toBe('rgba(226, 226, 226, 0.18)')
  expect(withGraphOpacity('#abc', 0.5)).toBe('rgba(170, 187, 204, 0.5)')
  expect(withGraphOpacity('rgb(10, 20, 30)', 0.08)).toBe('rgba(10, 20, 30, 0.08)')
})

test('keeps unsupported colors valid and detects active graph focus', () => {
  expect(withGraphOpacity('rebeccapurple', 0.2)).toBe('rebeccapurple')
  expect(isCypherFocusActive({ nodeIds: [], edgeIds: [] })).toBeFalse()
  expect(isCypherFocusActive({ nodeIds: ['1'], edgeIds: [] })).toBeTrue()
})
