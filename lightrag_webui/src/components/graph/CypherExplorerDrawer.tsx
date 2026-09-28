import { useEffect, useMemo, useState } from 'react'
import { Eraser, Play, X } from 'lucide-react'
import Button from '@/components/ui/Button'
import Textarea from '@/components/ui/Textarea'
import { ScrollArea } from '@/components/ui/ScrollArea'
import {
  GraphCypherEdge,
  GraphCypherReadResponse,
  GraphCypherNode,
  runGraphCypherRead
} from '@/api/lightrag'
import { errorMessage } from '@/lib/utils'
import { useGraphStore } from '@/stores/graph'

type CypherExplorerDrawerProps = {
  open: boolean
  onClose: () => void
}

const DEFAULT_QUERY = `MATCH (source)-[edge:DIRECTED]-(target)
WHERE edge.relation_type IN ['causes', 'influences', 'leads_to', 'results_in', 'affects']
RETURN source, edge, target
LIMIT 50`

const formatValue = (value: unknown): string => {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

const nodeLabel = (node: GraphCypherNode | undefined, fallback: string): string => {
  if (!node) return fallback
  return String(node.properties?.entity_id || node.labels?.[0] || fallback)
}

const relationLabel = (edge: GraphCypherEdge): string =>
  String(
    edge.properties?.relation_type ||
    edge.properties?.keywords ||
    edge.properties?.relation ||
    edge.type ||
    'related to'
  )

const relationImportance = (edge: GraphCypherEdge): string => {
  const importance = edge.properties?.relation_importance ?? edge.properties?.weight
  return typeof importance === 'number' ? importance.toFixed(2) : importance ? String(importance) : '-'
}

const CypherExplorerDrawer = ({ open, onClose }: CypherExplorerDrawerProps) => {
  const [query, setQuery] = useState(DEFAULT_QUERY)
  const [result, setResult] = useState<GraphCypherReadResponse | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cypherFocus = useGraphStore.use.cypherFocus()
  const focusCypherNode = useGraphStore.use.focusCypherNode()
  const focusCypherRelation = useGraphStore.use.focusCypherRelation()
  const clearCypherFocus = useGraphStore.use.clearCypherFocus()

  const nodesById = useMemo(
    () => new Map(result?.nodes.map((node) => [node.id, node]) || []),
    [result]
  )

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      clearCypherFocus()
      onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [clearCypherFocus, onClose, open])

  const runQuery = async () => {
    setIsRunning(true)
    setError(null)
    try {
      setResult(await runGraphCypherRead({ query, max_records: 100 }))
    } catch (runError) {
      setError(errorMessage(runError))
      setResult(null)
    } finally {
      setIsRunning(false)
    }
  }

  const clearFocus = () => clearCypherFocus()

  return (
    <aside
      aria-hidden={!open}
      className={`bg-background/95 absolute top-0 right-0 z-20 h-full w-[min(28rem,calc(100vw-1rem))] border-l shadow-2xl backdrop-blur transition-transform duration-200 ${
        open ? 'translate-x-0' : 'pointer-events-none translate-x-full'
      }`}
    >
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <div className="text-sm font-semibold">Cypher Explorer</div>
          <Button variant="ghost" size="icon" tooltip="Close Cypher Explorer" onClick={onClose}>
            <X />
          </Button>
        </div>

        <div className="space-y-2 border-b p-3">
          <Textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            spellCheck={false}
            className="h-36 min-h-36 font-mono text-xs"
            aria-label="Read-only Cypher query"
          />
          <div className="flex items-center justify-between gap-2">
            <Button variant="outline" size="sm" onClick={() => setQuery(DEFAULT_QUERY)}>
              Directed relations
            </Button>
            <div className="flex items-center gap-2">
              {cypherFocus.nodeIds.length > 0 || cypherFocus.edgeIds.length > 0 ? (
                <Button variant="ghost" size="icon" tooltip="Clear graph focus" onClick={clearFocus}>
                  <Eraser />
                </Button>
              ) : null}
              <Button size="sm" onClick={runQuery} disabled={isRunning}>
                <Play />
                {isRunning ? 'Running' : 'Run'}
              </Button>
            </div>
          </div>
          {error ? <p className="text-destructive text-xs">{error}</p> : null}
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-3 p-3">
            {result ? (
              <div className="text-muted-foreground flex items-center justify-between text-xs">
                <span>{result.rows.length} rows, {result.execution_time_ms} ms</span>
                {result.truncated ? <span>Result limit reached</span> : null}
              </div>
            ) : null}

            {result?.edges.length ? (
              <div className="overflow-hidden rounded-md border">
                <table className="w-full text-left text-xs">
                  <thead className="bg-muted/40 text-muted-foreground">
                    <tr>
                      <th className="px-2 py-2 font-medium">Source</th>
                      <th className="px-2 py-2 font-medium">Relation</th>
                      <th className="px-2 py-2 font-medium">Target</th>
                      <th className="px-2 py-2 text-right font-medium">Importance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.edges.map((edge) => (
                      <tr
                        key={edge.id}
                        className="hover:bg-accent cursor-pointer border-t"
                        onClick={() => focusCypherRelation(edge, result.nodes)}
                      >
                        <td className="max-w-24 truncate px-2 py-2">{nodeLabel(nodesById.get(edge.source), edge.source)}</td>
                        <td className="max-w-28 truncate px-2 py-2">{relationLabel(edge)}</td>
                        <td className="max-w-24 truncate px-2 py-2">{nodeLabel(nodesById.get(edge.target), edge.target)}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{relationImportance(edge)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}

            {result && result.edges.length === 0 && result.nodes.length > 0 ? (
              <div className="overflow-hidden rounded-md border">
                {result.nodes.map((node) => (
                  <button
                    key={node.id}
                    className="hover:bg-accent flex w-full items-center justify-between border-b px-3 py-2 text-left text-sm last:border-b-0"
                    onClick={() => focusCypherNode(node)}
                  >
                    <span className="truncate">{nodeLabel(node, node.id)}</span>
                    <span className="text-muted-foreground ml-3 shrink-0 text-xs">{node.properties?.entity_type || 'entity'}</span>
                  </button>
                ))}
              </div>
            ) : null}

            {result?.rows.length && result.edges.length === 0 && result.nodes.length === 0 ? (
              <div className="overflow-hidden rounded-md border">
                <table className="w-full text-left text-xs">
                  <thead className="bg-muted/40 text-muted-foreground">
                    <tr>{result.columns.map((column) => <th key={column} className="px-2 py-2 font-medium">{column}</th>)}</tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, index) => (
                      <tr key={index} className="border-t">
                        {result.columns.map((column) => (
                          <td key={column} className="max-w-48 truncate px-2 py-2">{formatValue(row.values[column])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}

            {result && result.rows.length === 0 ? (
              <p className="text-muted-foreground py-8 text-center text-sm">No matching graph elements.</p>
            ) : null}
          </div>
        </ScrollArea>
      </div>
    </aside>
  )
}

export default CypherExplorerDrawer
