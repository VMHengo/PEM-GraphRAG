import { useCallback, useEffect, useMemo, useState } from 'react'
import Button from '@/components/ui/Button'
import Checkbox from '@/components/ui/Checkbox'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card'
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
  EvaluationBenchmarkListItem,
  EvaluationRunMode,
  PromptExperiment,
  PromptExperimentConfig,
  PromptExperimentEstimate,
  PromptExperimentMode,
  cancelPromptExperiment,
  estimatePromptExperiment,
  getDocumentsPaginated,
  getPromptExperiment,
  getPromptExperimentConfig,
  getPromptExperiments,
  promotePromptExperiment,
  startPromptExperiment
} from '@/api/lightrag'
import { errorMessage } from '@/lib/utils'
import { BeakerIcon, PlayIcon, RefreshCwIcon, SquareIcon } from 'lucide-react'
import { toast } from 'sonner'

type Props = {
  benchmarks: EvaluationBenchmarkListItem[]
}

const modeLabels: Record<PromptExperimentMode, string> = {
  screening: 'Screening: sample, no gleaning',
  validation: 'Validation: all chunks, no gleaning',
  final: 'Final: all chunks, active gleaning'
}

const modeDescriptions: Record<PromptExperimentMode, string> = {
  screening: 'Fast comparison on a bounded chunk sample. Results cannot be promoted.',
  validation: 'Full selected documents without continuation extraction. Useful before the final run.',
  final: 'Full selected documents with the currently configured continuation extraction. A completed candidate can be promoted.'
}

const statusTone: Record<string, string> = {
  queued: 'text-sky-400',
  running: 'text-amber-400',
  completed: 'text-emerald-400',
  failed: 'text-red-400',
  cancelled: 'text-red-400',
  interrupted: 'text-red-400'
}

const formatScore = (value: number | null | undefined) => value == null ? '-' : value.toFixed(1)
const formatUsd = (value: number | null | undefined) => value == null ? '-' : `$${value.toFixed(2)}`

export default function PromptExperimentManager({ benchmarks }: Props) {
  const [config, setConfig] = useState<PromptExperimentConfig | null>(null)
  const [documents, setDocuments] = useState<Array<{ id: string; file_path: string; chunks_count?: number }>>([])
  const [experiments, setExperiments] = useState<PromptExperiment[]>([])
  const [selectedExperimentId, setSelectedExperimentId] = useState('')
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([])
  const [selectedProfileFiles, setSelectedProfileFiles] = useState<string[]>([])
  const [benchmarkId, setBenchmarkId] = useState('')
  const [optimizationMode, setOptimizationMode] = useState<PromptExperimentMode>('screening')
  const [benchmarkMode, setBenchmarkMode] = useState<EvaluationRunMode>('retrieval')
  const [title, setTitle] = useState('')
  const [note, setNote] = useState('')
  const [estimate, setEstimate] = useState<PromptExperimentEstimate | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const selectedExperiment = useMemo(
    () => experiments.find((experiment) => experiment.id === selectedExperimentId) || null,
    [experiments, selectedExperimentId]
  )
  const activeExperiment = experiments.some((experiment) => ['queued', 'running'].includes(experiment.status))
  const maxDocuments = config?.limits?.max_documents || 20
  const maxProfiles = config?.limits?.max_profiles || 5

  const load = useCallback(async () => {
    setIsLoading(true)
    try {
      const [nextConfig, docResponse, experimentResponse] = await Promise.all([
        getPromptExperimentConfig(),
        getDocumentsPaginated({
          page: 1,
          page_size: 100,
          status_filter: 'processed',
          status_filters: ['processed'],
          sort_field: 'updated_at',
          sort_direction: 'desc'
        }),
        getPromptExperiments()
      ])
      setConfig(nextConfig)
      setDocuments(docResponse.documents
        .filter((document) => !document.metadata?.skip_kg && (document.chunks_count || 0) > 0)
        .map((document) => ({ id: document.id, file_path: document.file_path, chunks_count: document.chunks_count })))
      setExperiments(experimentResponse.experiments)
      setSelectedExperimentId((current) => current || experimentResponse.experiments[0]?.id || '')
      setBenchmarkId((current) => current || benchmarks[0]?.id || '')
      setSelectedProfileFiles((current) => {
        if (current.length > 0) return current
        const active = nextConfig.profiles.find((profile) => profile.active)
        return active ? [active.file] : nextConfig.profiles.slice(0, 1).map((profile) => profile.file)
      })
    } catch (error) {
      toast.error(`Failed to load prompt experiments: ${errorMessage(error)}`)
    } finally {
      setIsLoading(false)
    }
  }, [benchmarks])

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void load()
    }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [load])

  useEffect(() => {
    if (!activeExperiment && !['queued', 'running'].includes(selectedExperiment?.status || '')) return
    const intervalId = window.setInterval(async () => {
      try {
        const response = await getPromptExperiments()
        setExperiments(response.experiments)
        if (selectedExperimentId) {
          const detail = await getPromptExperiment(selectedExperimentId)
          setExperiments((current) => current.map((item) => item.id === detail.id ? detail : item))
        }
      } catch {
        // A transient refresh failure should not erase an already rendered result.
      }
    }, 10000)
    return () => window.clearInterval(intervalId)
  }, [activeExperiment, selectedExperiment?.status, selectedExperimentId])

  const toggleDocument = (documentId: string) => {
    setEstimate(null)
    setSelectedDocumentIds((current) => {
      if (current.includes(documentId)) return current.filter((id) => id !== documentId)
      if (current.length >= maxDocuments) {
        toast.error(`At most ${maxDocuments} documents can be compared at once`)
        return current
      }
      return [...current, documentId]
    })
  }

  const toggleProfile = (profileFile: string) => {
    setEstimate(null)
    setSelectedProfileFiles((current) => {
      if (current.includes(profileFile)) return current.filter((file) => file !== profileFile)
      if (current.length >= maxProfiles) {
        toast.error(`At most ${maxProfiles} prompt profiles can be compared at once`)
        return current
      }
      return [...current, profileFile]
    })
  }

  const calculateEstimate = async () => {
    if (!config?.enabled || selectedDocumentIds.length === 0 || selectedProfileFiles.length === 0) return
    setIsSubmitting(true)
    try {
      const response = await estimatePromptExperiment({
        document_ids: selectedDocumentIds,
        profile_files: selectedProfileFiles,
        optimization_mode: optimizationMode
      })
      setEstimate(response)
      toast.success('Extraction estimate calculated')
    } catch (error) {
      toast.error(`Could not calculate estimate: ${errorMessage(error)}`)
    } finally {
      setIsSubmitting(false)
    }
  }

  const startExperiment = async () => {
    if (!estimate || !benchmarkId || !title.trim() || isSubmitting) return
    setIsSubmitting(true)
    try {
      const experiment = await startPromptExperiment({
        title: title.trim(),
        note: note.trim(),
        document_ids: selectedDocumentIds,
        profile_files: selectedProfileFiles,
        benchmark_id: benchmarkId,
        optimization_mode: optimizationMode,
        benchmark_mode: optimizationMode === 'final' ? benchmarkMode : undefined
      })
      setExperiments((current) => [experiment, ...current])
      setSelectedExperimentId(experiment.id)
      setEstimate(null)
      toast.success('Prompt experiment queued')
    } catch (error) {
      toast.error(`Could not start prompt experiment: ${errorMessage(error)}`)
    } finally {
      setIsSubmitting(false)
    }
  }

  const cancelExperiment = async () => {
    if (!selectedExperiment || isSubmitting) return
    setIsSubmitting(true)
    try {
      await cancelPromptExperiment(selectedExperiment.id)
      toast.success('Cancellation requested')
    } catch (error) {
      toast.error(`Could not cancel prompt experiment: ${errorMessage(error)}`)
    } finally {
      setIsSubmitting(false)
    }
  }

  const promoteCandidate = async (profileFile: string) => {
    if (!selectedExperiment || isSubmitting) return
    const confirmed = window.confirm(
      `Promote ${profileFile}? The selected documents' graph contributions will be replaced; document files, chunks, and source URLs stay unchanged.`
    )
    if (!confirmed) return
    setIsSubmitting(true)
    try {
      const promotion = await promotePromptExperiment(selectedExperiment.id, profileFile)
      const detail = await getPromptExperiment(selectedExperiment.id)
      setExperiments((current) => current.map((item) => item.id === detail.id ? detail : item))
      toast.success(`Promoted ${promotion?.profile_file || profileFile}`)
    } catch (error) {
      toast.error(`Could not promote candidate: ${errorMessage(error)}`)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Card className="rounded-md">
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2"><BeakerIcon className="size-5" /> Prompt Experiments</CardTitle>
          <CardDescription>Run isolated extraction candidates against retained chunks, then compare the same benchmark scores.</CardDescription>
        </div>
        <Button variant="outline" size="icon" onClick={() => void load()} disabled={isLoading} tooltip="Refresh prompt experiments">
          <RefreshCwIcon className={isLoading ? 'animate-spin' : ''} />
          <span className="sr-only">Refresh prompt experiments</span>
        </Button>
      </CardHeader>
      <CardContent className="space-y-5">
        {!config?.enabled ? (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm text-amber-300">
            Prompt experiments are disabled. An operator must set <code>PROMPT_EXPERIMENTS_ENABLED=true</code> and restart LightRAG.
          </div>
        ) : (
          <>
            <div className="grid gap-4 xl:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="prompt-experiment-title">Experiment title</label>
                <Input id="prompt-experiment-title" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={160} placeholder="Example: compact causal prompt screening" />
                <Textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={4000} placeholder="Optional hypothesis or change description" />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <label className="text-sm font-medium" htmlFor="prompt-experiment-benchmark">Benchmark</label>
                  <Select value={benchmarkId} onValueChange={setBenchmarkId}>
                    <SelectTrigger id="prompt-experiment-benchmark"><SelectValue placeholder="Select benchmark" /></SelectTrigger>
                    <SelectContent>{benchmarks.map((benchmark) => <SelectItem key={benchmark.id} value={benchmark.id}>{benchmark.name}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium" htmlFor="prompt-experiment-mode">Cost mode</label>
                  <Select value={optimizationMode} onValueChange={(value) => { setOptimizationMode(value as PromptExperimentMode); setEstimate(null) }}>
                    <SelectTrigger id="prompt-experiment-mode"><SelectValue /></SelectTrigger>
                    <SelectContent>{Object.entries(modeLabels).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                {optimizationMode === 'final' && <div className="space-y-1 sm:col-span-2">
                  <label className="text-sm font-medium" htmlFor="prompt-experiment-benchmark-mode">Final benchmark mode</label>
                  <Select value={benchmarkMode} onValueChange={(value) => setBenchmarkMode(value as EvaluationRunMode)}>
                    <SelectTrigger id="prompt-experiment-benchmark-mode"><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="graph">Graph</SelectItem><SelectItem value="retrieval">Retrieval</SelectItem><SelectItem value="full">Full QA</SelectItem></SelectContent>
                  </Select>
                </div>}
                <p className="text-muted-foreground text-xs sm:col-span-2">{modeDescriptions[optimizationMode]}</p>
              </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
              <div className="space-y-2">
                <div className="flex items-center justify-between"><h3 className="text-sm font-medium">Completed documents</h3><span className="text-muted-foreground text-xs">{selectedDocumentIds.length}/{maxDocuments} selected</span></div>
                <div className="max-h-56 space-y-1 overflow-auto rounded-md border p-2">
                  {documents.length === 0 ? <p className="text-muted-foreground p-2 text-sm">No extracted documents available.</p> : documents.map((document) => (
                    <label key={document.id} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-muted/50">
                      <Checkbox checked={selectedDocumentIds.includes(document.id)} onCheckedChange={() => toggleDocument(document.id)} />
                      <span className="min-w-0 flex-1 truncate">{document.file_path || document.id}</span>
                      <span className="text-muted-foreground text-xs">{document.chunks_count || 0} chunks</span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between"><h3 className="text-sm font-medium">Prompt profiles</h3><span className="text-muted-foreground text-xs">{selectedProfileFiles.length}/{maxProfiles} selected</span></div>
                <div className="max-h-56 space-y-1 overflow-auto rounded-md border p-2">
                  {config.profiles.length === 0 ? <p className="text-muted-foreground p-2 text-sm">No valid YAML profiles under PROMPT_DIR/entity_type.</p> : config.profiles.map((profile) => (
                    <label key={profile.file} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-muted/50">
                      <Checkbox checked={selectedProfileFiles.includes(profile.file)} onCheckedChange={() => toggleProfile(profile.file)} />
                      <span className="min-w-0 flex-1 truncate">{profile.file}{profile.active ? ' (active)' : ''}</span>
                      <span className="text-muted-foreground text-xs">~{profile.estimated_prompt_tokens} prompt tokens</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-t pt-4">
              <Button variant="outline" onClick={() => void calculateEstimate()} disabled={isSubmitting || selectedDocumentIds.length === 0 || selectedProfileFiles.length === 0}>
                Calculate estimate
              </Button>
              <Button onClick={() => void startExperiment()} disabled={isSubmitting || !estimate || !title.trim() || !benchmarkId}>
                <PlayIcon /> Start isolated comparison
              </Button>
              {estimate && <span className="text-sm"><strong>{formatUsd(estimate.estimated_cost_usd)}</strong> estimated extraction cost, {estimate.estimated_llm_calls} calls, {estimate.selected_chunks} selected chunks.</span>}
            </div>
            {estimate && <div className="overflow-x-auto rounded-md border">
              <table className="w-full min-w-[620px] text-left text-sm">
                <thead className="text-muted-foreground border-b text-xs uppercase"><tr><th className="px-3 py-2">Profile</th><th className="px-3 py-2">Prompt tokens</th><th className="px-3 py-2">Calls</th><th className="px-3 py-2">Input tokens</th><th className="px-3 py-2">Estimate</th></tr></thead>
                <tbody>{estimate.per_profile.map((item) => <tr key={item.profile_file} className="border-b last:border-0"><td className="px-3 py-2">{item.profile_file}</td><td className="px-3 py-2">{item.profile_prompt_tokens.toLocaleString()}</td><td className="px-3 py-2">{item.estimated_llm_calls}</td><td className="px-3 py-2">{item.estimated_input_tokens.toLocaleString()}</td><td className="px-3 py-2">{formatUsd(item.estimated_cost_usd)}</td></tr>)}</tbody>
              </table>
              <div className="text-muted-foreground border-t px-3 py-2 text-xs">{estimate.notes.join(' ')}</div>
            </div>}
          </>
        )}

        {experiments.length > 0 && <div className="border-t pt-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-semibold">Experiment results</h3>
            <Select value={selectedExperimentId} onValueChange={setSelectedExperimentId}>
              <SelectTrigger className="min-w-[300px]"><SelectValue placeholder="Select experiment" /></SelectTrigger>
              <SelectContent>{experiments.map((experiment) => <SelectItem key={experiment.id} value={experiment.id}>{experiment.title} ({experiment.status})</SelectItem>)}</SelectContent>
            </Select>
          </div>
          {selectedExperiment && <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className={`font-medium capitalize ${statusTone[selectedExperiment.status]}`}>{selectedExperiment.status}</span>
              <span>{selectedExperiment.optimization_mode}</span>
              <span>{selectedExperiment.document_ids.length} documents</span>
              <span>{formatUsd(selectedExperiment.estimate?.estimated_cost_usd)} estimated</span>
              {['queued', 'running'].includes(selectedExperiment.status) && <Button variant="outline" size="sm" onClick={() => void cancelExperiment()} disabled={isSubmitting}><SquareIcon /> Cancel</Button>}
            </div>
            {selectedExperiment.note && <p className="text-muted-foreground text-sm">{selectedExperiment.note}</p>}
            {selectedExperiment.error && <p className="text-sm text-red-400">{selectedExperiment.error}</p>}
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="text-muted-foreground border-b text-xs uppercase"><tr><th className="px-3 py-2">Profile</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Overall</th><th className="px-3 py-2">Graph</th><th className="px-3 py-2">Metadata</th><th className="px-3 py-2">Retrieval</th><th className="px-3 py-2">Directed</th><th className="px-3 py-2">Action</th></tr></thead>
                <tbody>{selectedExperiment.candidates.map((candidate) => <tr key={candidate.profile_file} className="border-b last:border-0"><td className="px-3 py-2">{candidate.profile_file}</td><td className={`px-3 py-2 capitalize ${statusTone[candidate.status]}`}>{candidate.status}</td><td className="px-3 py-2">{formatScore(candidate.scores.overall)}</td><td className="px-3 py-2">{formatScore(candidate.scores.graph)}</td><td className="px-3 py-2">{formatScore(candidate.scores.metadata)}</td><td className="px-3 py-2">{formatScore(candidate.scores.retrieval)}</td><td className="px-3 py-2">{formatScore(candidate.scores.directed)}</td><td className="px-3 py-2">{config?.promotion_enabled && selectedExperiment.optimization_mode === 'final' && candidate.status === 'completed' && !selectedExperiment.promotion ? <Button variant="outline" size="sm" onClick={() => void promoteCandidate(candidate.profile_file)} disabled={isSubmitting}>Promote</Button> : '-'}</td></tr>)}</tbody>
              </table>
            </div>
            {selectedExperiment.promotion && <p className="text-sm text-emerald-400">Promoted {selectedExperiment.promotion.profile_file}. Non-selected documents are now marked outdated by the new extraction revision.</p>}
          </div>}
        </div>}
      </CardContent>
    </Card>
  )
}
