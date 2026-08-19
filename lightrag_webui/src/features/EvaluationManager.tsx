import { useCallback, useEffect, useMemo, useState } from 'react'
import Button from '@/components/ui/Button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/Select'
import {
  EvaluationBenchmarkListItem,
  EvaluationRunMode,
  EvaluationRunResult,
  getEvaluationBenchmarks,
  runEvaluationBenchmark
} from '@/api/lightrag'
import { errorMessage } from '@/lib/utils'
import { PlayIcon, RefreshCwIcon } from 'lucide-react'
import { toast } from 'sonner'

const modeDescriptions: Record<EvaluationRunMode, string> = {
  graph: 'Graph metadata only, no query calls',
  retrieval: 'Graph plus context and source checks',
  full: 'Graph plus generated answer checks'
}

const scoreTone = (score: number | null | undefined) => {
  if (score == null) return 'text-muted-foreground'
  if (score >= 80) return 'text-emerald-400'
  if (score >= 60) return 'text-amber-400'
  return 'text-red-400'
}

const formatScore = (score: number | null | undefined) =>
  score == null ? '-' : `${score.toFixed(1)}`

function ScoreTile({
  label,
  score,
  detail
}: {
  label: string
  score: number | null | undefined
  detail?: string
}) {
  return (
    <div className="rounded-md border bg-background p-4">
      <div className="text-muted-foreground text-xs font-medium uppercase">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${scoreTone(score)}`}>{formatScore(score)}</div>
      {detail && <div className="text-muted-foreground mt-1 text-xs">{detail}</div>}
    </div>
  )
}

function MetadataCoverage({ result }: { result: EvaluationRunResult }) {
  const coverage = result.summary.graph.metadata_coverage
  const entries = Object.entries(coverage).filter(([key]) => key !== 'total_edges')
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
      {entries.map(([key, value]) => (
        <div key={key} className="rounded-md border bg-background p-3">
          <div className="text-muted-foreground text-xs capitalize">
            {key.replaceAll('_', ' ')}
          </div>
          <div className={`mt-1 text-lg font-semibold ${scoreTone(value)}`}>
            {formatScore(value)}
          </div>
        </div>
      ))}
    </div>
  )
}

function CaseDetails({ result }: { result: EvaluationRunResult }) {
  const graphCases = result.cases.graph
  const queryCases = result.cases.query
  return (
    <div className="space-y-3">
      {graphCases.map((graphCase) => {
        const queryCase = queryCases.find((item) => item.id === graphCase.id)
        return (
          <div key={graphCase.id} className="rounded-md border bg-background p-4">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="font-medium">{graphCase.id}</div>
                <div className="text-muted-foreground text-sm">{graphCase.question}</div>
              </div>
              <div className="flex gap-3 text-sm">
                <span>Entities: {formatScore(graphCase.entity_score)}</span>
                <span>Relations: {formatScore(graphCase.relation_score)}</span>
                {queryCase && <span>Content: {formatScore(queryCase.content_score)}</span>}
              </div>
            </div>
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              <div>
                <div className="text-muted-foreground mb-2 text-xs font-medium uppercase">
                  Expected Relations
                </div>
                <div className="space-y-2">
                  {(graphCase.relation_checks || []).map((check: any, index: number) => (
                    <div
                      key={`${graphCase.id}-relation-${index}`}
                      className="rounded border px-3 py-2 text-sm"
                    >
                      <div className={check.passed ? 'text-emerald-400' : 'text-red-400'}>
                        {check.passed ? 'Found' : 'Missing'}
                      </div>
                      <div className="text-muted-foreground mt-1">
                        {check.expected?.source} - {check.expected?.relation_type} -{' '}
                        {check.expected?.target}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              {queryCase && (
                <div>
                  <div className="text-muted-foreground mb-2 text-xs font-medium uppercase">
                    Query Preview
                  </div>
                  <pre className="max-h-44 overflow-auto rounded border bg-muted/30 p-3 text-xs whitespace-pre-wrap">
                    {queryCase.answer_preview || '-'}
                  </pre>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default function EvaluationManager() {
  const [benchmarks, setBenchmarks] = useState<EvaluationBenchmarkListItem[]>([])
  const [selectedBenchmark, setSelectedBenchmark] = useState('')
  const [mode, setMode] = useState<EvaluationRunMode>('retrieval')
  const [isLoading, setIsLoading] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [result, setResult] = useState<EvaluationRunResult | null>(null)

  const activeBenchmark = useMemo(
    () => benchmarks.find((benchmark) => benchmark.id === selectedBenchmark),
    [benchmarks, selectedBenchmark]
  )

  const loadBenchmarks = useCallback(async () => {
    setIsLoading(true)
    try {
      const response = await getEvaluationBenchmarks()
      setBenchmarks(response.benchmarks)
      setSelectedBenchmark((current) => current || response.benchmarks[0]?.id || '')
    } catch (error) {
      toast.error(`Failed to load benchmarks: ${errorMessage(error)}`)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadBenchmarks()
  }, [loadBenchmarks])

  const handleRun = useCallback(async () => {
    if (!selectedBenchmark || isRunning) return
    setIsRunning(true)
    try {
      const response = await runEvaluationBenchmark(selectedBenchmark, {
        mode,
        save_result: true
      })
      setResult(response)
      toast.success('Benchmark completed')
    } catch (error) {
      toast.error(`Benchmark failed: ${errorMessage(error)}`)
    } finally {
      setIsRunning(false)
    }
  }, [isRunning, mode, selectedBenchmark])

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Evaluation</h2>
          <p className="text-muted-foreground text-sm">
            Run repeatable graph and retrieval quality checks against the current knowledge base.
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="min-w-[280px]">
            <Select value={selectedBenchmark} onValueChange={setSelectedBenchmark}>
              <SelectTrigger>
                <SelectValue placeholder={isLoading ? 'Loading benchmarks...' : 'Select benchmark'} />
              </SelectTrigger>
              <SelectContent>
                {benchmarks.map((benchmark) => (
                  <SelectItem key={benchmark.id} value={benchmark.id}>
                    {benchmark.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="min-w-[220px]">
            <Select value={mode} onValueChange={(value) => setMode(value as EvaluationRunMode)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="graph">Graph</SelectItem>
                <SelectItem value="retrieval">Retrieval</SelectItem>
                <SelectItem value="full">Full QA</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button variant="outline" size="sm" onClick={loadBenchmarks} disabled={isLoading}>
            <RefreshCwIcon /> Refresh
          </Button>
          <Button size="sm" onClick={handleRun} disabled={!selectedBenchmark || isRunning}>
            <PlayIcon /> {isRunning ? 'Running...' : 'Run Benchmark'}
          </Button>
        </div>
      </div>

      <Card className="rounded-md">
        <CardHeader>
          <CardTitle>{activeBenchmark?.name || 'No benchmark selected'}</CardTitle>
          <CardDescription>
            {activeBenchmark?.description || 'Add benchmark JSON files under evaluation/benchmarks.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="text-sm">
            <span className="text-muted-foreground">Cases:</span>{' '}
            {activeBenchmark?.case_count ?? 0}
          </div>
          <div className="text-sm">
            <span className="text-muted-foreground">Selected mode:</span>{' '}
            {modeDescriptions[mode]}
          </div>
        </CardContent>
      </Card>

      {result && (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <ScoreTile label="Overall" score={result.scores.overall} detail={result.run.mode} />
            <ScoreTile label="Graph" score={result.scores.graph} />
            <ScoreTile label="Metadata" score={result.scores.metadata} />
            <ScoreTile label="Retrieval" score={result.scores.retrieval} />
          </div>

          <Card className="rounded-md">
            <CardHeader>
              <CardTitle>Metadata Coverage</CardTitle>
              <CardDescription>
                {result.summary.edges} edges and {result.summary.nodes} nodes inspected.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <MetadataCoverage result={result} />
            </CardContent>
          </Card>

          <Card className="rounded-md">
            <CardHeader>
              <CardTitle>Failed Checks</CardTitle>
              <CardDescription>
                {result.failed_checks.length === 0
                  ? 'All configured checks passed.'
                  : `${result.failed_checks.length} checks need attention.`}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {result.failed_checks.length === 0 ? (
                <div className="text-sm text-emerald-400">No failed checks.</div>
              ) : (
                <ul className="max-h-56 list-disc overflow-auto pl-5 text-sm">
                  {result.failed_checks.map((failure, index) => (
                    <li key={`${failure}-${index}`}>{failure}</li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card className="rounded-md">
            <CardHeader>
              <CardTitle>Case Details</CardTitle>
              <CardDescription>
                Saved result: {result.run.saved_to || 'not persisted'}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CaseDetails result={result} />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
