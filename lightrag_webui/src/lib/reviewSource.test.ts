import { describe, expect, test } from 'bun:test'
import {
  matchingTextItemIndexes,
  reviewSourceHash,
  sourceDocumentId,
  sourceEvidenceQuote
} from './reviewSource'

const source = {
  chunk_id: 'doc-0123456789abcdef0123456789abcdef-chunk-003',
  document: 'paper.pdf',
  url: null,
  chunk_excerpt: '',
  candidate_span: { text: 'Fallback evidence.' },
  context_excerpt: {
    text: 'Before. Exact evidence sentence. After.',
    match_start: 8,
    match_end: 32,
    status: 'exact_text_match'
  }
}

describe('review source links', () => {
  test('keeps evidence out of the route URL', () => {
    const hash = reviewSourceHash('session 1', 'candidate/2', 1, 0)
    expect(hash).toBe('#/review-source?sessionId=session+1&candidateId=candidate%2F2&hopIndex=1&sourceIndex=0')
    expect(hash).not.toContain('evidence')
  })

  test('resolves document id and exact evidence', () => {
    expect(sourceDocumentId(source)).toBe('doc-0123456789abcdef0123456789abcdef')
    expect(sourceEvidenceQuote(source)).toBe('Exact evidence sentence.')
  })

  test('prefers the chunk-grounded relation quote', () => {
    expect(sourceEvidenceQuote({ ...source, evidence_quote: 'Grounded relation quote.' }))
      .toBe('Grounded relation quote.')
  })

  test('uses one exact source span instead of a concatenated graph quote', () => {
    expect(sourceEvidenceQuote({
      ...source,
      evidence_quote: 'First statement.<SEP>Second statement.',
      candidate_span: { text: 'Second statement.', status: 'exact_text_match' }
    })).toBe('Second statement.')
  })
})

describe('PDF text matching', () => {
  test('matches across PDF text runs despite punctuation and case', () => {
    expect(matchingTextItemIndexes(
      ['Electrode calendering', 'decreased cathode', 'porosity.'],
      'electrode calendering decreased cathode porosity'
    )).toEqual([0, 1, 2])
  })

  test('matches a word split across adjacent PDF text runs', () => {
    expect(matchingTextItemIndexes(
      ['Electro', 'de calendering decreased porosity.'],
      'Electrode calendering decreased porosity.'
    )).toEqual([0, 1])
  })

  test('does not create a highlight for a short or missing quote', () => {
    expect(matchingTextItemIndexes(['A different statement'], 'none')).toEqual([])
    expect(matchingTextItemIndexes(['A different statement'], 'long missing quote')).toEqual([])
  })

  test('does not mark a repeated quote as a unique source', () => {
    expect(matchingTextItemIndexes(
      ['Aging increases resistance.', 'Aging increases resistance.'],
      'Aging increases resistance.'
    )).toEqual([])
  })
})
