import { useCallback, useEffect, useMemo, useState } from 'react'
import Button from '@/components/ui/Button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/Dialog'
import Input from '@/components/ui/Input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/Select'
import Textarea from '@/components/ui/Textarea'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger
} from '@/components/ui/Tooltip'
import {
  EvaluationBenchmarkListItem,
  EvaluationRunDetailResponse,
  EvaluationRunMode,
  EvaluationRunResult,
  EvaluationRunSummary,
  ExtractionRevision,
  getEvaluationBenchmarks,
  getEvaluationRun,
  getEvaluationRuns,
  startEvaluationBenchmarkRun,
  updateEvaluationRun
} from '@/api/lightrag'
import { errorMessage } from '@/lib/utils'
import { CircleHelpIcon, PencilIcon, PlayIcon, RefreshCwIcon } from 'lucide-react'
import { toast } from 'sonner'
import PromptExperimentManager from '@/features/PromptExperimentManager'

const modeDescriptions: Record<EvaluationRunMode, string> = {
  graph: 'Graph metadata only, no query calls',
  retrieval: 'Graph plus context and source checks',
  full: 'Graph plus generated answer checks'
}

const metricDescriptions: Record<string, string> = {
  Overall:
    'Weighted aggregate of the available Graph, Metadata, Retrieval, and Directed checks. Weights are rebalanced when a score is not evaluated.',
  Graph:
    'Expected entity and relation matches in the graph. Relation matches receive twice the weight of entity matches.',
  Metadata:
    'Completeness of directionality, relation type, relation importance, chain role, and specific relation types. It measures coverage, not domain correctness.',
  Retrieval:
    'Average of expected-content coverage and expected-source coverage in the retrieved context or generated answer.',
  Directed:
    'Quality of expected multi-hop paths for directed, combined, and auto retrieval strategies. Normal retrieval is shown as a regression comparison.',
  Entities: 'Share of expected entities that could be found in the current graph.',
  Relations:
    'Share of expected source, relation type, target, and direction combinations that match an extracted graph edge.',
  Content:
    'Share of required terms found in the retrieved context or generated answer for this benchmark case.',
  directionality: 'Share of graph edges with a direction other than unknown.',
  'relation type': 'Share of graph edges with a populated relation type.',
  'relation importance': 'Share of graph edges with a relation importance value.',
  'chain role': 'Share of graph edges with a chain role other than other.',
  'specific relation type': 'Share of graph edges with a non-generic relation type.',
  Strategy:
    'Share of expected directed-path checks passed by this retrieval strategy. It evaluates path direction, hops, relation types, and citations where configured.'
}

const scoreTone = (score: number | null | undefined) => {
  if (score == null) return 'text-muted-foreground'
  if (score >= 80) return 'text-emerald-400'
  if (score >= 60) return 'text-amber-400'
  return 'text-red-400'
}

const statusTone: Record<EvaluationRunSummary['status'], string> = {
  queued: 'text-sky-400',
  running: 'text-amber-400',
  completed: 'text-emerald-400',
  failed: 'text-red-400',
  interrupted: 'text-red-400'
}

const formatScore = (score: number | null | undefined) =>
  score == null ? '-' : `${score.toFixed(1)}`

const formatDate = (value: string | null | undefined) => {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short'
    }).format(date)
}

const formatRevision = (revision: ExtractionRevision | null | undefined) => {
  if (!revision) return 'Legacy / unknown'
  const fingerprint = revision.fingerprint ? revision.fingerprint.slice(0, 12) : 'unknown'
  return `${revision.version} / ${revision.prompt_profile} / ${fingerprint}`
}

const scoreDelta = (candidate: number | null | undefined, baseline: number | null | undefined) => {
  if (candidate == null || baseline == null) return '-'
  const delta = candidate - baseline
  return `${delta >= 0 ? '+' : ''}${delta.toFixed(1)}`
}

function MetricLabel({
  label,
  description,
  className = ''
}: {
  label: string
  description?: string
  className?: string
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={`inline-flex items-center gap-1 text-left ${className}`}
          aria-label={`Explain ${label} metric`}
        >
          <span>{label}</span>
          <CircleHelpIcon className="size-3.5 shrink-0" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-xs text-xs">
        {description || 'This metric has no additional description.'}
      </TooltipContent>
    </Tooltip>
  )
}

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
      <MetricLabel
        label={label}
        description={metricDescriptions[label]}
        className="text-muted-foreground text-xs font-medium uppercase"
      />
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
      {entries.map(([key, value]) => {
        const label = key.replaceAll('_', ' ')
        return (
          <div key={key} className="rounded-md border bg-background p-3">
            <MetricLabel
              label={label}
              description={metricDescriptions[label]}
              className="text-muted-foreground text-xs capitalize"
            />
            <div className={`mt-1 text-lg font-semibold ${scoreTone(value)}`}>
              {formatScore(value)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CaseMetric({ label, score }: { label: 'Entities' | 'Relations' | 'Content'; score: number | null | undefined }) {
  return (
    <span className="inline-flex items-center gap-1">
      <MetricLabel label={label} description={metricDescriptions[label]} className="text-sm" />
      <span>{formatScore(score)}</span>
    </span>
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
                <div className="font-medium">{graphCase.question || graphCase.id}</div>
                <div className="text-muted-foreground text-sm">{graphCase.id}</div>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
                <CaseMetric label="Entities" score={graphCase.entity_score} />
                <CaseMetric label="Relations" score={graphCase.relation_score} />
                {queryCase && <CaseMetric label="Content" score={queryCase.content_score} />}
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

function DirectedRetrievalQuality({ result }: { result: EvaluationRunResult }) {
  const summary = result.summary.directed
  const cases = result.cases.directed || []
  if (!summary || cases.length === 0) return null

  return (
    <Card className="rounded-md">
      <CardHeader>
        <CardTitle>Directed Retrieval Quality</CardTitle>
        <CardDescription>{summary.cases} chain cases across normal, directed, combined, and auto.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {Object.entries(summary.strategies).map(([strategy, strategySummary]) => (
            <div key={strategy} className="rounded-md border bg-background p-3">
              <MetricLabel
                label={strategy}
                description={metricDescriptions.Strategy}
                className="text-muted-foreground text-xs font-medium uppercase"
              />
              <div className={`mt-1 text-xl font-semibold ${scoreTone(strategySummary.path_score)}`}>
                {formatScore(strategySummary.path_score)}
              </div>
              <div className="text-muted-foreground mt-1 text-xs">
                {strategySummary.successful_runs}/{strategySummary.runs} successful
              </div>
            </div>
          ))}
        </div>
        <div className="space-y-2">
          {cases.map((benchmarkCase) => (
            <div key={benchmarkCase.id} className="rounded-md border bg-background p-3">
              <div className="font-medium">{benchmarkCase.question || benchmarkCase.id}</div>
              <div className="text-muted-foreground mt-1 text-sm">{benchmarkCase.id}</div>
              <div className="mt-3 grid gap-2 lg:grid-cols-3">
                {(benchmarkCase.strategies || []).map((strategy: any) => (
                  <div key={strategy.strategy} className="rounded border px-3 py-2 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium capitalize">{strategy.strategy}</span>
                      <span className={scoreTone(strategy.score)}>{formatScore(strategy.score)}</span>
                    </div>
                    <div className="text-muted-foreground mt-1 text-xs">
                      {strategy.path_status || '-'}; {strategy.path_count || 0} paths
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function QualityGates({ result }: { result: EvaluationRunResult }) {
  const gates = result.quality_gates
  if (!gates?.configured) return null

  return (
    <Card className="rounded-md">
      <CardHeader>
        <CardTitle>Quality Gates</CardTitle>
        <CardDescription>
          {gates.passed
            ? 'All configured promotion thresholds passed.'
            : 'At least one configured promotion threshold failed.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {gates.checks.map((check) => (
          <div key={check.kind} className="flex flex-wrap items-center justify-between gap-2 rounded border px-3 py-2 text-sm">
            <span className="font-medium">{check.kind.replaceAll('_', ' ')}</span>
            <span className={check.passed ? 'text-emerald-400' : 'text-red-400'}>
              {check.passed ? 'Passed' : 'Failed'}
            </span>
            <span className="text-muted-foreground text-xs">
              expected {String(check.expected)}; actual {String(check.actual)}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function RunHistory({
  runs,
  selectedRunId,
  isLoading,
  onOpen,
  onEdit,
  onRefresh
}: {
  runs: EvaluationRunSummary[]
  selectedRunId: string
  isLoading: boolean
  onOpen: (runId: string) => void
  onEdit: (run: EvaluationRunSummary) => void
  onRefresh: () => void
}) {
  return (
    <Card className="rounded-md">
      <CardHeader className="flex-row items-center justify-between gap-4 space-y-0">
        <div>
          <CardTitle>Run History</CardTitle>
          <CardDescription>Saved benchmark results for the selected benchmark.</CardDescription>
        </div>
        <Button variant="outline" size="icon" onClick={onRefresh} disabled={isLoading} tooltip="Refresh run history">
          <RefreshCwIcon className={isLoading ? 'animate-spin' : ''} />
          <span className="sr-only">Refresh run history</span>
        </Button>
      </CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <div className="text-muted-foreground text-sm">No saved runs for this benchmark yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead className="text-muted-foreground border-b text-xs uppercase">
                <tr>
                  <th className="px-2 py-2 font-medium">Title and note</th>
                  <th className="px-2 py-2 font-medium">Extraction revision</th>
                  <th className="px-2 py-2 font-medium">Mode</th>
                  <th className="px-2 py-2 font-medium">Status</th>
                  <th className="px-2 py-2 font-medium">Overall</th>
                  <th className="px-2 py-2 font-medium">Created</th>
                  <th className="px-2 py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    className={selectedRunId === run.id ? 'bg-muted/40' : 'border-b last:border-0'}
                  >
                    <td className="max-w-sm px-2 py-3 align-top">
                      <div className="font-medium">{run.title}</div>
                      {run.note && <div className="text-muted-foreground mt-1 truncate text-xs">{run.note}</div>}
                      {run.error && <div className="mt-1 truncate text-xs text-red-400">{run.error}</div>}
                    </td>
                    <td className="max-w-[220px] px-2 py-3 align-top text-xs text-muted-foreground">
                      {formatRevision(run.extraction_revision)}
                    </td>
                    <td className="px-2 py-3 align-top capitalize">{run.mode}</td>
                    <td className={`px-2 py-3 align-top capitalize ${statusTone[run.status]}`}>{run.status}</td>
                    <td className={`px-2 py-3 align-top ${scoreTone(run.scores.overall)}`}>
                      {formatScore(run.scores.overall)}
                    </td>
                    <td className="px-2 py-3 align-top text-xs">{formatDate(run.created_at)}</td>
                    <td className="px-2 py-3 align-top">
                      <div className="flex gap-1">
                        <Button variant="outline" size="sm" onClick={() => onOpen(run.id)}>
                          Open
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => onEdit(run)} tooltip="Edit title and note">
                          <PencilIcon />
                          <span className="sr-only">Edit title and note</span>
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function PromptComparison({
  runs,
  selectedRun,
  baselineRunId,
  onBaselineChange
}: {
  runs: EvaluationRunSummary[]
  selectedRun: EvaluationRunSummary | null
  baselineRunId: string
  onBaselineChange: (runId: string) => void
}) {
  const baseline = runs.find((run) => run.id === baselineRunId) || null
  const comparableRuns = runs.filter(
    (run) => run.status === 'completed' && run.id !== selectedRun?.id
  )

  if (!selectedRun || selectedRun.status !== 'completed' || comparableRuns.length === 0) {
    return null
  }

  const metrics: Array<keyof EvaluationRunSummary['scores']> = [
    'overall',
    'graph',
    'metadata',
    'retrieval',
    'directed'
  ]

  return (
    <Card className="rounded-md">
      <CardHeader>
        <CardTitle>Prompt Comparison</CardTitle>
        <CardDescription>
          Compare the selected completed run with an earlier run. Each run stores the active extraction revision at its start.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-md border p-3 text-sm">
            <div className="text-muted-foreground text-xs uppercase">Candidate</div>
            <div className="mt-1 font-medium">{selectedRun.title}</div>
            <div className="mt-1 text-xs text-muted-foreground">
              {formatRevision(selectedRun.extraction_revision)}
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-sm font-medium" htmlFor="evaluation-comparison-baseline">
              Baseline run
            </label>
            <Select value={baselineRunId} onValueChange={onBaselineChange}>
              <SelectTrigger id="evaluation-comparison-baseline">
                <SelectValue placeholder="Select baseline" />
              </SelectTrigger>
              <SelectContent>
                {comparableRuns.map((run) => (
                  <SelectItem key={run.id} value={run.id}>
                    {run.title} ({formatRevision(run.extraction_revision)})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {baseline && (
              <div className="text-xs text-muted-foreground">
                {formatRevision(baseline.extraction_revision)}
              </div>
            )}
          </div>
        </div>
        {baseline && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead className="text-muted-foreground border-b text-xs uppercase">
                <tr>
                  <th className="px-2 py-2">Metric</th>
                  <th className="px-2 py-2">Baseline</th>
                  <th className="px-2 py-2">Candidate</th>
                  <th className="px-2 py-2">Delta</th>
                </tr>
              </thead>
              <tbody>
                {metrics.map((metric) => {
                  const candidateScore = selectedRun.scores[metric]
                  const baselineScore = baseline.scores[metric]
                  const delta = candidateScore != null && baselineScore != null
                    ? candidateScore - baselineScore
                    : null
                  return (
                    <tr key={metric} className="border-b last:border-0">
                      <td className="px-2 py-2 capitalize">{metric}</td>
                      <td className={`px-2 py-2 ${scoreTone(baselineScore)}`}>
                        {formatScore(baselineScore)}
                      </td>
                      <td className={`px-2 py-2 ${scoreTone(candidateScore)}`}>
                        {formatScore(candidateScore)}
                      </td>
                      <td className={`px-2 py-2 ${delta == null ? 'text-muted-foreground' : delta >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {scoreDelta(candidateScore, baselineScore)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function EvaluationManager() {
  const [benchmarks, setBenchmarks] = useState<EvaluationBenchmarkListItem[]>([])
  const [selectedBenchmark, setSelectedBenchmark] = useState('')
  const [mode, setMode] = useState<EvaluationRunMode>('retrieval')
  const [isLoading, setIsLoading] = useState(false)
  const [runs, setRuns] = useState<EvaluationRunSummary[]>([])
  const [selectedRunId, setSelectedRunId] = useState('')
  const [comparisonBaselineId, setComparisonBaselineId] = useState('')
  const [runDetail, setRunDetail] = useState<EvaluationRunDetailResponse | null>(null)
  const [isLoadingRuns, setIsLoadingRuns] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [runDialogOpen, setRunDialogOpen] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [runTitle, setRunTitle] = useState('')
  const [runNote, setRunNote] = useState('')

  const activeBenchmark = useMemo(
    () => benchmarks.find((benchmark) => benchmark.id === selectedBenchmark),
    [benchmarks, selectedBenchmark]
  )
  const selectedRun = useMemo(
    () => runs.find((run) => run.id === selectedRunId) || runDetail?.run || null,
    [runDetail?.run, runs, selectedRunId]
  )
  const hasActiveRun = runs.some((run) => run.status === 'queued' || run.status === 'running')
  const result = runDetail?.result || null

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

  const loadRuns = useCallback(async () => {
    if (!selectedBenchmark) {
      setRuns([])
      return
    }
    setIsLoadingRuns(true)
    try {
      const response = await getEvaluationRuns({ benchmarkId: selectedBenchmark, limit: 25 })
      setRuns(response.runs)
      setSelectedRunId((current) =>
        response.runs.some((run) => run.id === current) ? current : response.runs[0]?.id || ''
      )
    } catch (error) {
      toast.error(`Failed to load run history: ${errorMessage(error)}`)
    } finally {
      setIsLoadingRuns(false)
    }
  }, [selectedBenchmark])

  const loadRun = useCallback(async (runId: string, quiet = false) => {
    if (!runId) return
    try {
      const response = await getEvaluationRun(runId)
      setRunDetail(response)
    } catch (error) {
      if (!quiet) toast.error(`Failed to load benchmark run: ${errorMessage(error)}`)
    }
  }, [])

  useEffect(() => {
    void loadBenchmarks()
  }, [loadBenchmarks])

  useEffect(() => {
    setSelectedRunId('')
    setRunDetail(null)
    void loadRuns()
  }, [loadRuns])

  const effectiveComparisonBaselineId = useMemo(() => {
    const stillValid = runs.some(
      (run) => run.id === comparisonBaselineId && run.id !== selectedRunId && run.status === 'completed'
    )
    if (stillValid) return comparisonBaselineId
    return runs.find(
      (run) => run.id !== selectedRunId && run.status === 'completed'
    )?.id || ''
  }, [comparisonBaselineId, runs, selectedRunId])

  useEffect(() => {
    if (selectedRunId) void loadRun(selectedRunId)
  }, [loadRun, selectedRunId])

  useEffect(() => {
    if (!hasActiveRun && !['queued', 'running'].includes(selectedRun?.status || '')) return
    const intervalId = window.setInterval(() => {
      void loadRuns()
      if (selectedRunId) void loadRun(selectedRunId, true)
    }, 10000)
    return () => window.clearInterval(intervalId)
  }, [hasActiveRun, loadRun, loadRuns, selectedRun?.status, selectedRunId])

  const openRunDialog = () => {
    if (!activeBenchmark) return
    setRunTitle(`${activeBenchmark.name} (${mode})`)
    setRunNote('')
    setRunDialogOpen(true)
  }

  const handleStartRun = useCallback(async () => {
    if (!selectedBenchmark || !runTitle.trim() || isSubmitting) return
    setIsSubmitting(true)
    try {
      const response = await startEvaluationBenchmarkRun(selectedBenchmark, {
        mode,
        title: runTitle.trim(),
        note: runNote.trim()
      })
      setRunDialogOpen(false)
      setSelectedRunId(response.run.id)
      await loadRuns()
      await loadRun(response.run.id, true)
      toast.success('Benchmark queued and will continue in the background')
    } catch (error) {
      toast.error(`Could not start benchmark: ${errorMessage(error)}`)
    } finally {
      setIsSubmitting(false)
    }
  }, [isSubmitting, loadRun, loadRuns, mode, runNote, runTitle, selectedBenchmark])

  const openEditDialog = (run: EvaluationRunSummary) => {
    setSelectedRunId(run.id)
    setRunTitle(run.title)
    setRunNote(run.note)
    setEditDialogOpen(true)
  }

  const handleUpdateRun = useCallback(async () => {
    if (!selectedRunId || !runTitle.trim() || isSubmitting) return
    setIsSubmitting(true)
    try {
      const response = await updateEvaluationRun(selectedRunId, {
        title: runTitle.trim(),
        note: runNote.trim()
      })
      setRuns((current) => current.map((run) => (run.id === response.run.id ? response.run : run)))
      setRunDetail((current) =>
        current && current.run.id === response.run.id ? { ...current, run: response.run } : current
      )
      setEditDialogOpen(false)
      toast.success('Run title and note updated')
    } catch (error) {
      toast.error(`Could not update benchmark run: ${errorMessage(error)}`)
    } finally {
      setIsSubmitting(false)
    }
  }, [isSubmitting, runNote, runTitle, selectedRunId])

  return (
    <TooltipProvider delayDuration={250}>
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
              <RefreshCwIcon className={isLoading ? 'animate-spin' : ''} /> Refresh
            </Button>
            <Button size="sm" onClick={openRunDialog} disabled={!selectedBenchmark || isSubmitting}>
              <PlayIcon /> Run Benchmark
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

        <PromptExperimentManager benchmarks={benchmarks} />

        <RunHistory
          runs={runs}
          selectedRunId={selectedRunId}
          isLoading={isLoadingRuns}
          onOpen={setSelectedRunId}
          onEdit={openEditDialog}
          onRefresh={() => void loadRuns()}
        />

        <PromptComparison
          runs={runs}
          selectedRun={selectedRun}
          baselineRunId={effectiveComparisonBaselineId}
          onBaselineChange={setComparisonBaselineId}
        />

        {selectedRun && (
          <div className="border-y py-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-semibold">{selectedRun.title}</h3>
                  <span className={`text-xs font-medium capitalize ${statusTone[selectedRun.status]}`}>
                    {selectedRun.status}
                  </span>
                </div>
                {selectedRun.note && <p className="text-muted-foreground mt-1 text-sm">{selectedRun.note}</p>}
                <p className="text-muted-foreground mt-1 text-xs">
                  Extraction: {formatRevision(selectedRun.extraction_revision)}
                </p>
                <p className="text-muted-foreground mt-1 text-xs">
                  {selectedRun.benchmark_name} · {selectedRun.mode} · {formatDate(selectedRun.created_at)}
                </p>
              </div>
              <Button variant="outline" size="icon" onClick={() => openEditDialog(selectedRun)} tooltip="Edit title and note">
                <PencilIcon />
                <span className="sr-only">Edit title and note</span>
              </Button>
            </div>
            {['queued', 'running'].includes(selectedRun.status) && (
              <p className="mt-2 text-sm text-amber-400">This run continues in the background. Its status refreshes every 10 seconds.</p>
            )}
            {selectedRun.error && <p className="mt-2 text-sm text-red-400">{selectedRun.error}</p>}
          </div>
        )}

        {result && (
          <>
            <div className="grid gap-3 md:grid-cols-5">
              <ScoreTile label="Overall" score={result.scores.overall} detail={result.run.mode} />
              <ScoreTile label="Graph" score={result.scores.graph} />
              <ScoreTile label="Metadata" score={result.scores.metadata} />
              <ScoreTile label="Retrieval" score={result.scores.retrieval} />
              <ScoreTile label="Directed" score={result.scores.directed} />
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

            <DirectedRetrievalQuality result={result} />

            <QualityGates result={result} />

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
                <CardDescription>Run ID: {selectedRun?.id || result.run.id || 'unknown'}</CardDescription>
              </CardHeader>
              <CardContent>
                <CaseDetails result={result} />
              </CardContent>
            </Card>
          </>
        )}
      </div>

      <Dialog open={runDialogOpen} onOpenChange={setRunDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Run benchmark</DialogTitle>
            <DialogDescription>
              Add a title and optional note so this result can be identified later. The benchmark will run in the background.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <label className="block space-y-1 text-sm font-medium" htmlFor="evaluation-run-title">
              <span>Title</span>
              <Input
                id="evaluation-run-title"
                value={runTitle}
                maxLength={160}
                onChange={(event) => setRunTitle(event.target.value)}
                placeholder="Benchmark run title"
              />
            </label>
            <label className="block space-y-1 text-sm font-medium" htmlFor="evaluation-run-note">
              <span>Note</span>
              <Textarea
                id="evaluation-run-note"
                value={runNote}
                maxLength={4000}
                onChange={(event) => setRunNote(event.target.value)}
                placeholder="Optional context, prompt version, or graph change"
              />
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRunDialogOpen(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button onClick={() => void handleStartRun()} disabled={!runTitle.trim() || isSubmitting}>
              <PlayIcon /> {isSubmitting ? 'Starting...' : 'Start benchmark'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit benchmark run</DialogTitle>
            <DialogDescription>Update the title or note without rerunning the benchmark.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <label className="block space-y-1 text-sm font-medium" htmlFor="evaluation-edit-title">
              <span>Title</span>
              <Input
                id="evaluation-edit-title"
                value={runTitle}
                maxLength={160}
                onChange={(event) => setRunTitle(event.target.value)}
              />
            </label>
            <label className="block space-y-1 text-sm font-medium" htmlFor="evaluation-edit-note">
              <span>Note</span>
              <Textarea
                id="evaluation-edit-note"
                value={runNote}
                maxLength={4000}
                onChange={(event) => setRunNote(event.target.value)}
              />
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditDialogOpen(false)} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button onClick={() => void handleUpdateRun()} disabled={!runTitle.trim() || isSubmitting}>
              {isSubmitting ? 'Saving...' : 'Save changes'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TooltipProvider>
  )
}
