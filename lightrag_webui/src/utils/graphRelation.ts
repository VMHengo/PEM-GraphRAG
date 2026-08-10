import { RawEdgeType } from '@/stores/graph'

const normalizeRelationValue = (value: unknown): string | undefined => {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean).join(', ')
  }

  if (typeof value === 'string') {
    const trimmed = value.trim()
    return trimmed.length > 0 ? trimmed : undefined
  }

  if (value === null || value === undefined) {
    return undefined
  }

  return String(value).trim() || undefined
}

const truncateRelationLabel = (label: string, maxLength: number): string => {
  if (label.length <= maxLength) return label
  return `${label.slice(0, Math.max(0, maxLength - 1)).trimEnd()}...`
}

export const getRelationLabel = (edge: Pick<RawEdgeType, 'type' | 'properties'>, maxLength = 72): string => {
  const candidates = [
    edge.properties?.keywords,
    edge.properties?.relation,
    edge.properties?.relationship,
    edge.properties?.description,
    edge.type && edge.type !== '*' && edge.type.toLowerCase() !== 'directed' ? edge.type : undefined
  ]

  const label = candidates.map(normalizeRelationValue).find(Boolean)
  return truncateRelationLabel(label || 'related to', maxLength)
}
