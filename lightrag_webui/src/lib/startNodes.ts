const normalize = (name: string) => name.trim().toLowerCase()

export const parseStartNodes = (text: string): string[] => {
  const seen = new Set<string>()
  return text.split(/[,\n]/).map((part) => part.trim()).filter((part) => {
    const key = normalize(part)
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export const toggleStartNode = (text: string, name: string, checked: boolean): string => {
  const names = parseStartNodes(text)
  const key = normalize(name)
  if (!checked) return names.filter((part) => normalize(part) !== key).join(', ')
  if (names.some((part) => normalize(part) === key)) return names.join(', ')

  const last = names.at(-1)
  const hasDraft = !/[,\n]\s*$/.test(text)
  if (hasDraft && last && key.startsWith(normalize(last))) names[names.length - 1] = name
  else names.push(name)
  return names.join(', ')
}

export const selectedStartNode = (text: string, name: string): boolean =>
  parseStartNodes(text).some((part) => normalize(part) === normalize(name))
