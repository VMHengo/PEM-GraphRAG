import { expect, test } from 'bun:test'
import { parseStartNodes, selectedStartNode, toggleStartNode } from './startNodes'

test('manual full names check the matching recommendation', () => {
  expect(selectedStartNode('  mixing heat, Electrode Calendering', 'Mixing Heat')).toBe(true)
  expect(selectedStartNode('Mixing H', 'Mixing Heat')).toBe(false)
  expect(parseStartNodes('Heat, heat, Mixing Heat')).toEqual(['Heat', 'Mixing Heat'])
})

test('check adds, replaces a draft, and uncheck removes only that name', () => {
  expect(toggleStartNode('Heat Generation', 'Mixing Heat', true)).toBe('Heat Generation, Mixing Heat')
  expect(toggleStartNode('Heat Generation, Mix', 'Mixing Heat', true)).toBe('Heat Generation, Mixing Heat')
  expect(toggleStartNode('Heat Generation, Mixing Heat', 'Mixing Heat', false)).toBe('Heat Generation')
})
