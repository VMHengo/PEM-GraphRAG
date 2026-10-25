import { describe, expect, test } from 'bun:test'
import { evaluationEntityLabel } from './evaluationEntityLabel'

describe('evaluationEntityLabel', () => {
  test('keeps legacy string expectations', () => {
    expect(evaluationEntityLabel('Internal Polarization')).toEqual({
      name: 'Internal Polarization',
      aliases: []
    })
  })

  test('renders a structured benchmark entity and its aliases', () => {
    expect(evaluationEntityLabel({ name: 'NCM622', aliases: ['NCM622 Cathode'] })).toEqual({
      name: 'NCM622',
      aliases: ['NCM622 Cathode']
    })
  })

  test('does not pass malformed objects through to React', () => {
    expect(evaluationEntityLabel({ aliases: [null, 'Cell Aging', 2] })).toEqual({
      name: 'Unnamed entity',
      aliases: ['Cell Aging']
    })
  })
})
