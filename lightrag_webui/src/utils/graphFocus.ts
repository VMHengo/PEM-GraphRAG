export type CypherGraphFocus = {
  nodeIds: string[]
  edgeIds: string[]
}

export const CYPHER_FOCUS_NODE_OPACITY = 0.18
export const CYPHER_FOCUS_EDGE_OPACITY = 0.08
export const CYPHER_FOCUS_LABEL_OPACITY = 0.22

const hexToRgba = (color: string, opacity: number): string | null => {
  const value = color.trim().replace('#', '')
  const normalized = value.length === 3
    ? value.split('').map((character) => `${character}${character}`).join('')
    : value.length === 8 ? value.slice(0, 6) : value

  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) return null
  const red = Number.parseInt(normalized.slice(0, 2), 16)
  const green = Number.parseInt(normalized.slice(2, 4), 16)
  const blue = Number.parseInt(normalized.slice(4, 6), 16)
  return `rgba(${red}, ${green}, ${blue}, ${opacity})`
}

/** Convert the graph's usual hex/rgb colors into transparent Sigma colors. */
export const withGraphOpacity = (color: string | undefined, opacity: number): string | undefined => {
  if (!color) return color
  const boundedOpacity = Math.max(0, Math.min(1, opacity))
  const hex = hexToRgba(color, boundedOpacity)
  if (hex) return hex

  const rgb = color.match(/^rgba?\(([^)]+)\)$/i)
  if (rgb) {
    const channels = rgb[1].split(',').slice(0, 3).map((channel) => channel.trim())
    if (channels.length === 3) return `rgba(${channels.join(', ')}, ${boundedOpacity})`
  }

  // Current LightRAG graph colors are hex values. Preserve unknown CSS colors
  // rather than producing an invalid renderer value.
  return color
}

export const isCypherFocusActive = (focus: CypherGraphFocus): boolean =>
  focus.nodeIds.length > 0 || focus.edgeIds.length > 0
