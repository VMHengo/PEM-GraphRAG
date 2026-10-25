export function evaluationEntityLabel(value: unknown): { name: string; aliases: string[] } {
  if (typeof value === 'string') {
    return { name: value, aliases: [] }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { name: 'Unnamed entity', aliases: [] }
  }

  const entity = value as Record<string, unknown>
  const name = [entity.name, entity.value, entity.entity].find(
    (candidate): candidate is string => typeof candidate === 'string' && candidate.trim().length > 0
  )
  const aliases = Array.isArray(entity.aliases)
    ? entity.aliases.filter((alias): alias is string => typeof alias === 'string' && alias.trim().length > 0)
    : []

  return { name: name?.trim() || 'Unnamed entity', aliases }
}
