import type { ExplorationSource } from '@/api/lightrag'

const DOCUMENT_CHUNK_ID = /^(doc-[0-9a-f]{32})-chunk-\d+$/i

export const sourceDocumentId = (source: ExplorationSource): string | null =>
  source.document_id || source.chunk_id.match(DOCUMENT_CHUNK_ID)?.[1] || null

export const sourceEvidenceQuote = (source: ExplorationSource): string => {
  if (
    typeof source.candidate_span === 'object'
    && source.candidate_span?.status === 'exact_text_match'
    && source.candidate_span.text?.trim()
  ) return source.candidate_span.text.trim()
  if (source.evidence_quote?.trim()) return source.evidence_quote.trim()
  const excerpt = source.context_excerpt
  if (
    excerpt?.status === 'exact_text_match'
    && excerpt.match_start >= 0
    && excerpt.match_end > excerpt.match_start
    && excerpt.match_end <= excerpt.text.length
  ) {
    return excerpt.text.slice(excerpt.match_start, excerpt.match_end).trim()
  }
  if (typeof source.candidate_span === 'string') return source.candidate_span.trim()
  return source.candidate_span?.text?.trim() || ''
}

export const reviewSourceHash = (
  sessionId: string,
  candidateId: string,
  hopIndex: number,
  sourceIndex: number
): string => {
  const params = new URLSearchParams({
    sessionId,
    candidateId,
    hopIndex: String(hopIndex),
    sourceIndex: String(sourceIndex)
  })
  return `#/review-source?${params.toString()}`
}

type NormalizedText = {
  text: string
  itemIndexes: number[]
}

const normalizeTextItems = (items: string[], spaceBetweenItems = true): NormalizedText => {
  let text = ''
  const itemIndexes: number[] = []
  let pendingSpace = false

  items.forEach((item, itemIndex) => {
    for (const character of item.normalize('NFKC').toLocaleLowerCase()) {
      if (/\p{L}|\p{N}/u.test(character)) {
        if (pendingSpace && text.length > 0) {
          text += ' '
          itemIndexes.push(itemIndex)
        }
        text += character
        itemIndexes.push(itemIndex)
        pendingSpace = false
      } else {
        pendingSpace = text.length > 0
      }
    }
    if (spaceBetweenItems) pendingSpace = text.length > 0
  })

  return { text, itemIndexes }
}

export const matchingTextItemIndexes = (items: string[], quote: string): number[] => {
  const normalizedQuote = normalizeTextItems([quote]).text
  if (!normalizedQuote || normalizedQuote.length < 8) return []

  let normalizedItems = normalizeTextItems(items)
  let start = normalizedItems.text.indexOf(normalizedQuote)
  if (start >= 0 && normalizedItems.text.indexOf(normalizedQuote, start + 1) >= 0) return []
  if (start < 0) {
    normalizedItems = normalizeTextItems(items, false)
    start = normalizedItems.text.indexOf(normalizedQuote)
    if (start < 0 || normalizedItems.text.indexOf(normalizedQuote, start + 1) >= 0) return []
  }

  const indexes = new Set<number>()
  for (let offset = start; offset < start + normalizedQuote.length; offset += 1) {
    const itemIndex = normalizedItems.itemIndexes[offset]
    if (itemIndex != null) indexes.add(itemIndex)
  }
  return [...indexes]
}
