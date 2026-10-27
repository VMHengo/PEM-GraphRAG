import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  CircleIcon,
  CircleHelpIcon,
  DownloadIcon,
  ExternalLinkIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
  SaveIcon
} from 'lucide-react'
import { toast } from 'sonner'
import {
  ExplorationCandidate,
  ExplorationConditions,
  ExplorationInferenceVerdict,
  ExplorationInterest,
  ExplorationReview,
  ExplorationReviewRequest,
  ExplorationSession,
  ExplorationSessionSummary,
  ExplorationVerdict,
  downloadExplorationReviewSheet,
  getExplorationSession,
  getExplorationSessions,
  saveExplorationReview,
  startExplorationSession
} from '@/api/lightrag'
import Badge from '@/components/ui/Badge'
import Button from '@/components/ui/Button'
import Checkbox from '@/components/ui/Checkbox'
import Input from '@/components/ui/Input'
import NumberInput from '@/components/ui/NumberInput'
import Progress from '@/components/ui/Progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/Select'
import Textarea from '@/components/ui/Textarea'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/Tooltip'
import { errorMessage } from '@/lib/utils'

const REVIEW_LIMIT = 20
const REVIEWER_STORAGE_KEY = 'pem-reviewer-name'

const verdictOptions: Array<{ value: ExplorationVerdict; label: string }> = [
  { value: 'supported', label: 'Supported' },
  { value: 'partial', label: 'Partially supported' },
  { value: 'contradicted', label: 'Contradicted' },
  { value: 'unclear', label: 'Unclear' }
]

const interestOptions: Array<{ value: ExplorationInterest; label: string }> = [
  { value: 'interesting', label: 'Interesting' },
  { value: 'neutral', label: 'Neutral' },
  { value: 'not_interesting', label: 'Not interesting' },
  { value: 'unclear', label: 'Unclear' }
]

const conditionOptions: Array<{ value: ExplorationConditions; label: string }> = [
  { value: 'compatible', label: 'Compatible' },
  { value: 'incompatible', label: 'Incompatible' },
  { value: 'unclear', label: 'Unclear' }
]

const inferenceVerdictOptions: Array<{ value: ExplorationInferenceVerdict; label: string }> = [
  { value: 'plausible', label: 'Plausible' },
  { value: 'conditional', label: 'Conditional' },
  { value: 'contradicted', label: 'Contradicted' },
  { value: 'not_derivable', label: 'Not derivable' }
]

const rubricDescriptions = {
  hop: 'Does the document text support this one arrow? Check which thing affects which, and whether it increases or decreases.',
  interest: 'Would this connection be useful or surprising to investigate? Judge interest separately from whether it is correct.',
  correctness: 'Do all arrows form a believable chain from the first topic to the last? A wrong arrow makes the whole chain questionable.',
  conditions: 'Can these arrows be combined? Check whether they refer to the same kind of cell, situation, and time.'
} as const

const formatDate = (value?: string) => {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

const formatRevision = (session: ExplorationSession | null) => {
  const revision = session?.extraction_revision
  if (!revision) return 'Legacy / unknown'
  const fingerprint = revision.fingerprint ? revision.fingerprint.slice(0, 12) : 'unknown'
  return `${revision.version} / ${revision.prompt_profile} / ${fingerprint}`
}

const parseStarts = (value: string) =>
  [...new Set(value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean))]

const candidateSpanText = (span: NonNullable<ExplorationCandidate['path'][number]['sources'][number]['candidate_span']>) => {
  if (typeof span === 'string') return span
  if (span.text) return span.text
  return JSON.stringify(span)
}

const isWebUrl = (value: string) => /^https?:\/\//i.test(value)
const readableDescription = (value: string) => [...new Set(value.split('<SEP>').map((part) => part.trim()).filter(Boolean))].join(' ')

const exclusionLabels: Record<string, string> = {
  invalid_or_unresolved_path: 'Missing source or unsupported edge',
  unsupported_path_length: 'Fewer than two or more than four hops',
  different_start_node: 'Starts at a different node',
  unsupported_edge: 'Not a directed causal edge',
  edge_order_mismatch: 'Edge direction does not match the path',
  missing_source_chunk: 'Source text unavailable',
  unclassified_domain: 'Unknown subject area',
  same_domain: 'Same subject area',
  target_diversity_limit: 'More than two paths to one target'
}

function SourceExcerpt({ source }: { source: ExplorationCandidate['path'][number]['sources'][number] }) {
  const excerpt = source.context_excerpt
  if (excerpt && excerpt.match_start >= 0 && excerpt.match_end <= excerpt.text.length
    && excerpt.match_start < excerpt.match_end) {
    return (
      <div className="mt-2">
        <p className="text-muted-foreground text-xs">
          {excerpt.status === 'exact_text_match'
            ? 'Exact match in extracted text; relation still requires review.'
            : excerpt.status === 'candidate_related_text'
              ? 'Possibly related text; direction and relation are unverified.'
              : 'Both terms found nearby; relation still requires review.'}
        </p>
        <p className="mt-1 whitespace-pre-wrap break-words text-sm">
          {excerpt.text.slice(0, excerpt.match_start)}
          <mark className="bg-amber-300/40 text-inherit">{excerpt.text.slice(excerpt.match_start, excerpt.match_end)}</mark>
          {excerpt.text.slice(excerpt.match_end)}
        </p>
      </div>
    )
  }
  return source.candidate_span
    ? <p className="mt-2 whitespace-pre-wrap break-words text-sm">{candidateSpanText(source.candidate_span)}</p>
    : <p className="text-muted-foreground mt-2 text-xs">No reliable short text match found. Inspect the extracted chunk before rating this hop.</p>
}

function RubricLabel({ label, description }: { label: string; description: string }) {
  const [open, setOpen] = useState(false)

  return (
    <span className="inline-flex items-center gap-1">
      <span>{label}</span>
      <TooltipProvider delayDuration={250}>
        <Tooltip open={open} onOpenChange={setOpen}>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground focus-visible:text-foreground inline-flex size-5 shrink-0 items-center justify-center rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2"
              aria-label={`Help for ${label}`}
              onClick={() => setOpen((current) => !current)}
            >
              <CircleHelpIcon className="size-3.5" aria-hidden="true" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-xs text-xs">
            {description}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </span>
  )
}

type ReviewEditorProps = {
  sessionId: string
  candidate: ExplorationCandidate
  reviewer: string
  review?: ExplorationReview
  isSaving: boolean
  onSave: (request: ExplorationReviewRequest) => Promise<void>
  onPrevious: () => void
  onNext: () => void
  hasPrevious: boolean
  hasNext: boolean
}

function ReviewEditor({
  sessionId,
  candidate,
  reviewer,
  review,
  isSaving,
  onSave,
  onPrevious,
  onNext,
  hasPrevious,
  hasNext
}: ReviewEditorProps) {
  const [interest, setInterest] = useState<ExplorationInterest | ''>(review?.interest || '')
  const [correctness, setCorrectness] = useState<ExplorationVerdict | ''>(review?.correctness || '')
  const [conditions, setConditions] = useState<ExplorationConditions | ''>(review?.conditions || '')
  const [inferenceVerdict, setInferenceVerdict] = useState<ExplorationInferenceVerdict | ''>(
    review?.inference_verdict || ''
  )
  const [inferenceHelpOpen, setInferenceHelpOpen] = useState(false)
  const [hopVerdicts, setHopVerdicts] = useState<Array<ExplorationVerdict | ''>>(
    candidate.path.map((_, index) => review?.hop_verdicts[index] || '')
  )
  const [followUp, setFollowUp] = useState(review?.follow_up || false)
  const [note, setNote] = useState(review?.note || '')
  const hasContradictedHop = review?.hop_verdicts.includes('contradicted') || false
  const hasIncompatibleConditions = review?.conditions === 'incompatible'

  const complete = Boolean(
    reviewer.trim() && interest && correctness && conditions && hopVerdicts.every(Boolean)
    && (!candidate.inferred_connection || inferenceVerdict)
  )

  const submit = () => {
    if (!complete || !interest || !correctness || !conditions) {
      toast.error('Complete the reviewer, path and hop verdicts, and inferred-claim verdict first')
      return
    }
    const request: ExplorationReviewRequest = {
      candidate_id: candidate.id,
      reviewer: reviewer.trim(),
      interest,
      correctness,
      hop_verdicts: hopVerdicts as ExplorationVerdict[],
      conditions,
      follow_up: followUp,
      note: note.trim()
    }
    if (inferenceVerdict) request.inference_verdict = inferenceVerdict
    void onSave(request)
  }

  return (
    <div className="min-w-0 space-y-5" data-session-id={sessionId}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold break-words">{candidate.from} to {candidate.to}</h3>
            {review ? (
              <Badge className="border-emerald-500/40 bg-emerald-500/10 text-emerald-400" variant="outline">
                Reviewed
              </Badge>
            ) : (
              <Badge className="border-amber-500/40 bg-amber-500/10 text-amber-400" variant="outline">
                Unreviewed
              </Badge>
            )}
            {hasContradictedHop && (
              <Badge className="border-red-500/40 bg-red-500/10 text-red-500" variant="outline">
                Reviewed: contradicted hop
              </Badge>
            )}
            {hasIncompatibleConditions && (
              <Badge className="border-red-500/40 bg-red-500/10 text-red-500" variant="outline">
                Reviewed: incompatible conditions
              </Badge>
            )}
          </div>
          <p className="text-muted-foreground mt-1 text-xs">
            {candidate.hops} {candidate.hops === 1 ? 'hop' : 'hops'} · {candidate.status}
            {review?.updated_at || review?.created_at
              ? ` · Saved ${formatDate(review.updated_at || review.created_at)}`
              : ''}
          </p>
          <p className="text-muted-foreground mt-1 text-xs break-words">
            Start domains: {candidate.start_domains.join(', ') || '-'} · Target domains: {candidate.target_domains.join(', ') || '-'}
          </p>
          {candidate.inferred_connection ? (
            <div className="mt-3 space-y-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono break-all">
                  {candidate.from} --[{candidate.inferred_connection.status === 'candidate'
                    ? candidate.inferred_connection.label || candidate.inferred_connection.relation || 'indirect relation'
                    : 'not composable'}]--&gt; {candidate.to}
                </span>
                <Badge variant="outline" className="border-amber-500/40 text-amber-500">
                  {candidate.inferred_connection.status === 'candidate' ? 'Hypothesis' : 'Not composable'}
                </Badge>
                <TooltipProvider delayDuration={250}>
                  <Tooltip open={inferenceHelpOpen} onOpenChange={setInferenceHelpOpen}>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        className="text-muted-foreground hover:text-foreground focus-visible:text-foreground inline-flex size-5 shrink-0 items-center justify-center rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2"
                        aria-label="Show inferred hypothesis details"
                        onClick={() => setInferenceHelpOpen((current) => !current)}
                      >
                        <CircleHelpIcon className="size-3.5" aria-hidden="true" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-sm space-y-2 text-xs">
                      <p>Path-derived review aid only; not a new graph edge or a direct statement verified in source text.</p>
                      <p>
                        {candidate.inferred_connection.path_hops} path {candidate.inferred_connection.path_hops === 1 ? 'hop' : 'hops'}
                        {candidate.inferred_connection.polarity ? ` / ${candidate.inferred_connection.polarity} polarity` : ''}
                      </p>
                      {candidate.inferred_connection.rule && <p>Rule: {candidate.inferred_connection.rule}</p>}
                      {candidate.inferred_connection.caveats.length > 0 && (
                        <ul className="list-disc space-y-0.5 pl-4">
                          {candidate.inferred_connection.caveats.map((caveat, index) => (
                            <li key={`${caveat}-${index}`} className="break-words">{caveat}</li>
                          ))}
                        </ul>
                      )}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <div className="max-w-sm space-y-1">
                <RubricLabel
                  label="Inferred-claim verdict"
                  description="Do the checked arrows really imply the suggested connection between the first and last topic? The documents do not state this connection directly."
                />
                <Select
                  value={inferenceVerdict}
                  onValueChange={(value) => setInferenceVerdict(value as ExplorationInferenceVerdict)}
                >
                  <SelectTrigger aria-label="Inferred-claim verdict">
                    <SelectValue placeholder="Assess the indirect hypothesis" />
                  </SelectTrigger>
                  <SelectContent>
                    {inferenceVerdictOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          ) : (
            <p className="text-muted-foreground mt-2 text-xs">
              No inferred connection available (legacy session or no inference).
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={onPrevious} disabled={!hasPrevious} tooltip="Previous candidate">
            <ArrowLeftIcon />
            <span className="sr-only">Previous candidate</span>
          </Button>
          <Button variant="outline" size="icon" onClick={onNext} disabled={!hasNext} tooltip="Next candidate">
            <ArrowRightIcon />
            <span className="sr-only">Next candidate</span>
          </Button>
        </div>
      </div>

      <div className="space-y-4">
        {candidate.path.map((hop, index) => (
          <section key={`${candidate.id}-hop-${index}`} className="space-y-3 border-b pb-4 last:border-b-0">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <p className="text-muted-foreground text-xs font-medium uppercase">Hop {index + 1}</p>
                <p className="mt-1 text-sm font-medium break-words">
                  {hop.source} <span className="text-muted-foreground">[{hop.relation}]</span> {hop.target}
                </p>
                {hop.description && <p className="text-muted-foreground mt-1 text-sm break-words">{readableDescription(hop.description)}</p>}
              </div>
              <div className="w-full shrink-0 sm:w-48">
                <div className="mb-1 text-sm font-medium">
                  <RubricLabel label="Hop verdict" description={rubricDescriptions.hop} />
                </div>
                <Select
                  value={hopVerdicts[index]}
                  onValueChange={(value) => setHopVerdicts((current) =>
                    current.map((item, itemIndex) => itemIndex === index ? value as ExplorationVerdict : item)
                  )}
                >
                  <SelectTrigger aria-label={`Hop ${index + 1} verdict`}>
                    <SelectValue placeholder="Hop verdict" />
                  </SelectTrigger>
                  <SelectContent>
                    {verdictOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="space-y-3 pl-3 sm:pl-5">
              {hop.sources.length === 0 && <p className="text-muted-foreground text-sm">No source excerpt supplied.</p>}
              {hop.sources.map((source, sourceIndex) => (
                <div key={`${source.chunk_id}-${sourceIndex}`} className="border-l px-3 py-1 text-sm">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                    <span className="font-medium break-all">{source.document || source.chunk_id}</span>
                    <span className="text-muted-foreground break-all">Chunk {source.chunk_id}</span>
                    {source.url && isWebUrl(source.url) && (
                      <a className="text-primary inline-flex items-center gap-1 hover:underline" href={source.url} target="_blank" rel="noreferrer">
                        Source <ExternalLinkIcon className="size-3" />
                      </a>
                    )}
                  </div>
                  <SourceExcerpt source={source} />
                  <details className="group mt-2 text-xs">
                    <summary className="text-muted-foreground hover:text-foreground focus-visible:text-foreground inline-flex cursor-pointer list-none items-center gap-1 font-medium focus-visible:outline-2 focus-visible:outline-offset-2 [&::-webkit-details-marker]:hidden">
                      {source.full_chunk_text
                        ? source.full_chunk_truncated ? 'Extracted chunk (truncated)' : 'Full extracted chunk'
                        : 'Abbreviated chunk preview'}
                      <ChevronDownIcon className="size-3.5 transition-transform group-open:rotate-180" aria-hidden="true" />
                    </summary>
                    {source.full_chunk_truncated && (
                      <p className="mt-2 font-medium text-amber-600">
                        Retained extracted text is truncated at 12,000 characters.
                      </p>
                    )}
                    <p className="mt-2 whitespace-pre-wrap break-words">
                      {source.full_chunk_text || source.chunk_excerpt || 'No chunk preview available.'}
                    </p>
                  </details>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>

      <div className="grid gap-4 border-t pt-4 md:grid-cols-3">
        <div className="space-y-1 text-sm font-medium">
          <RubricLabel label="Interest" description={rubricDescriptions.interest} />
          <Select value={interest} onValueChange={(value) => setInterest(value as ExplorationInterest)}>
            <SelectTrigger aria-label="Interest"><SelectValue placeholder="Select interest" /></SelectTrigger>
            <SelectContent>{interestOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="space-y-1 text-sm font-medium">
          <RubricLabel label="Overall correctness" description={rubricDescriptions.correctness} />
          <Select value={correctness} onValueChange={(value) => setCorrectness(value as ExplorationVerdict)}>
            <SelectTrigger aria-label="Overall correctness"><SelectValue placeholder="Select verdict" /></SelectTrigger>
            <SelectContent>{verdictOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="space-y-1 text-sm font-medium">
          <RubricLabel label="Conditions" description={rubricDescriptions.conditions} />
          <Select value={conditions} onValueChange={(value) => setConditions(value as ExplorationConditions)}>
            <SelectTrigger aria-label="Conditions"><SelectValue placeholder="Select compatibility" /></SelectTrigger>
            <SelectContent>{conditionOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent>
          </Select>
        </div>
      </div>

      <label className="block space-y-1 text-sm font-medium">
        <span>Review note</span>
        <Textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={2000} rows={3} placeholder="Reasoning, uncertainty, or follow-up context" />
      </label>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <Checkbox checked={followUp} onCheckedChange={(checked) => setFollowUp(checked === true)} />
          Needs follow-up
        </label>
        <Button onClick={submit} disabled={!complete || isSaving}>
          {isSaving ? <Loader2Icon className="animate-spin" /> : <SaveIcon />}
          {review ? 'Save revision' : 'Save review'}
        </Button>
      </div>
    </div>
  )
}

export default function HumanReviewManager() {
  const [reviewer, setReviewer] = useState(() => {
    try {
      return window.localStorage.getItem(REVIEWER_STORAGE_KEY) || ''
    } catch {
      return ''
    }
  })
  const [sessions, setSessions] = useState<ExplorationSessionSummary[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState('')
  const [session, setSession] = useState<ExplorationSession | null>(null)
  const [selectedCandidateId, setSelectedCandidateId] = useState('')
  const [isLoadingSessions, setIsLoadingSessions] = useState(false)
  const [isLoadingSession, setIsLoadingSession] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [isDownloading, setIsDownloading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [title, setTitle] = useState('')
  const [startsText, setStartsText] = useState('')
  const [hopDepth, setHopDepth] = useState(2)
  const [limit, setLimit] = useState(REVIEW_LIMIT)

  useEffect(() => {
    try {
      if (reviewer.trim()) window.localStorage.setItem(REVIEWER_STORAGE_KEY, reviewer.trim())
      else window.localStorage.removeItem(REVIEWER_STORAGE_KEY)
    } catch {
      // Review remains usable when browser storage is unavailable.
    }
  }, [reviewer])

  const loadSessions = useCallback(async () => {
    setIsLoadingSessions(true)
    try {
      const response = await getExplorationSessions()
      setSessions(response.sessions)
      setSelectedSessionId((current) =>
        response.sessions.some((item) => item.id === current) ? current : response.sessions[0]?.id || ''
      )
    } catch (error) {
      toast.error(`Failed to load review sessions: ${errorMessage(error)}`)
    } finally {
      setIsLoadingSessions(false)
    }
  }, [])

  const loadSession = useCallback(async (sessionId: string, quiet = false) => {
    if (!sessionId) return
    if (!quiet) {
      setIsLoadingSession(true)
      setSession(null)
      setSelectedCandidateId('')
    }
    try {
      const response = await getExplorationSession(sessionId)
      setSession(response.session)
      setSelectedCandidateId((current) =>
        response.session.candidates.some((candidate) => candidate.id === current)
          ? current
          : response.session.candidates[0]?.id || ''
      )
    } catch (error) {
      if (!quiet) toast.error(`Failed to load review session: ${errorMessage(error)}`)
    } finally {
      if (!quiet) setIsLoadingSession(false)
    }
  }, [])

  useEffect(() => {
    const timeoutId = window.setTimeout(() => void loadSessions(), 0)
    return () => window.clearTimeout(timeoutId)
  }, [loadSessions])

  useEffect(() => {
    if (!selectedSessionId) return
    const timeoutId = window.setTimeout(() => void loadSession(selectedSessionId), 0)
    return () => window.clearTimeout(timeoutId)
  }, [loadSession, selectedSessionId])

  useEffect(() => {
    if (!session?.id || !['queued', 'running'].includes(session.status)) return
    const sessionId = session.id
    const intervalId = window.setInterval(() => void loadSession(sessionId, true), 5000)
    return () => window.clearInterval(intervalId)
  }, [loadSession, session?.id, session?.status])

  const latestReviews = useMemo(() => {
    const reviews = new Map<string, ExplorationReview>()
    for (const review of session?.reviews || []) {
      if (review.reviewer.trim().toLocaleLowerCase() === reviewer.trim().toLocaleLowerCase()) {
        reviews.set(review.candidate_id, review)
      }
    }
    return reviews
  }, [session?.reviews, reviewer])

  const candidates = useMemo(() => session?.candidates.slice(0, REVIEW_LIMIT) || [], [session?.candidates])
  const selectedIndex = candidates.findIndex((candidate) => candidate.id === selectedCandidateId)
  const selectedCandidate = selectedIndex >= 0 ? candidates[selectedIndex] : undefined
  const reviewedCount = candidates.filter((candidate) => latestReviews.has(candidate.id)).length
  const progress = candidates.length ? reviewedCount / candidates.length * 100 : 0

  const createSession = async () => {
    const starts = parseStarts(startsText)
    if (!title.trim() || starts.length === 0) {
      toast.error('Add a session title and at least one starting subject')
      return
    }
    setIsCreating(true)
    try {
      const response = await startExplorationSession({
        title: title.trim(),
        starts,
        hop_depth: hopDepth,
        limit
      })
      setSessions((current) => [response.session, ...current.filter((item) => item.id !== response.session.id)])
      setSelectedSessionId(response.session.id)
      setSession(response.session)
      setSelectedCandidateId(response.session.candidates[0]?.id || '')
      setShowCreate(false)
      setTitle('')
      setStartsText('')
      toast.success('Human review session created')
    } catch (error) {
      toast.error(`Could not create review session: ${errorMessage(error)}`)
    } finally {
      setIsCreating(false)
    }
  }

  const downloadReviewSheet = async () => {
    if (!selectedSessionId) return
    setIsDownloading(true)
    try {
      const { blob, filename } = await downloadExplorationReviewSheet(selectedSessionId)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      toast.error(`Could not download review sheet: ${errorMessage(error)}`)
    } finally {
      setIsDownloading(false)
    }
  }

  const saveReview = async (request: ExplorationReviewRequest) => {
    if (!session) return
    setIsSaving(true)
    try {
      const response = await saveExplorationReview(session.id, request)
      const savedReview = { ...request, ...response.review }
      setSession((current) => current && current.id === session.id
        ? {
          ...current,
          reviews: [...(current.reviews || []), savedReview]
        }
        : current
      )
      setSessions((current) => current.map((item) => item.id === session.id
        ? { ...item, review_count: (item.review_count || 0) + 1 }
        : item
      ))
      const nextUnreviewed = candidates.find((candidate, index) =>
        index > selectedIndex && candidate.id !== request.candidate_id && !latestReviews.has(candidate.id)
      )
      if (nextUnreviewed) setSelectedCandidateId(nextUnreviewed.id)
      toast.success(latestReviews.has(request.candidate_id) ? 'Review revision saved' : 'Review saved')
    } catch (error) {
      toast.error(`Could not save review: ${errorMessage(error)}`)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h3 className="font-semibold">Human Review</h3>
          <p className="text-muted-foreground text-sm">Review up to 20 exploratory paths against their source excerpts.</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <label className="flex flex-col gap-1 text-sm font-medium sm:w-44">
            <span className="leading-5">Reviewer</span>
            <Input className="h-10 w-full" value={reviewer} onChange={(event) => setReviewer(event.target.value)} maxLength={80} placeholder="Name or initials" />
          </label>
          <div className="flex min-w-72 flex-col gap-1">
            <span className="text-sm font-medium leading-5">Session</span>
            <Select value={selectedSessionId} onValueChange={setSelectedSessionId}>
              <SelectTrigger><SelectValue placeholder={isLoadingSessions ? 'Loading sessions...' : 'Select a saved session'} /></SelectTrigger>
              <SelectContent>
                {sessions.map((item) => <SelectItem key={item.id} value={item.id}>{item.title} · {formatDate(item.created_at)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <Button variant="outline" size="icon" onClick={() => void loadSessions()} disabled={isLoadingSessions} tooltip="Refresh sessions">
            <RefreshCwIcon className={isLoadingSessions ? 'animate-spin' : ''} />
            <span className="sr-only">Refresh sessions</span>
          </Button>
          <Button
            variant="outline"
            size="icon"
            onClick={() => void downloadReviewSheet()}
            disabled={!selectedSessionId || isDownloading}
            tooltip="Download review sheet"
          >
            {isDownloading ? <Loader2Icon className="animate-spin" /> : <DownloadIcon />}
            <span className="sr-only">Download review sheet</span>
          </Button>
          <Button size="sm" onClick={() => setShowCreate((current) => !current)}><PlusIcon /> New Session</Button>
        </div>
      </div>

      {showCreate && (
        <div className="space-y-4 border-y py-4">
          <div className="grid gap-4 lg:grid-cols-[minmax(220px,1fr)_minmax(300px,2fr)_140px_140px]">
            <label className="space-y-1 text-sm font-medium">
              <span>Title</span>
              <Input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={160} placeholder="October path review" />
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>Starting nodes</span>
              <Input value={startsText} onChange={(event) => setStartsText(event.target.value)} placeholder="e.g. Heat Generation" list="review-start-nodes" />
              <datalist id="review-start-nodes">
                <option value="Heat Generation" />
                <option value="Electrode Calendering" />
              </datalist>
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>Max hops</span>
              <NumberInput value={hopDepth} min={2} max={4} onValueChange={(value) => setHopDepth(value ?? 2)} />
            </label>
            <label className="space-y-1 text-sm font-medium">
              <span>Cases</span>
              <NumberInput value={limit} min={1} max={REVIEW_LIMIT} onValueChange={(value) => setLimit(value ?? REVIEW_LIMIT)} />
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button size="sm" onClick={() => void createSession()} disabled={isCreating}>
              {isCreating ? <Loader2Icon className="animate-spin" /> : <PlusIcon />} Create Session
            </Button>
          </div>
        </div>
      )}

      {isLoadingSession && <div className="flex items-center gap-2 py-12 text-sm text-muted-foreground"><Loader2Icon className="animate-spin" /> Loading session...</div>}

      {!isLoadingSession && !session && (
        <div className="border-y py-12 text-center text-sm text-muted-foreground">Create or select a session to begin reviewing.</div>
      )}

      {!isLoadingSession && session && (
        <>
          <div className="grid gap-3 border-y py-3 text-sm md:grid-cols-2 xl:grid-cols-4">
            <div><span className="text-muted-foreground">Status:</span> <span className="capitalize">{session.status}</span></div>
            <div><span className="text-muted-foreground">Created:</span> {formatDate(session.created_at)}</div>
            <div className="md:col-span-2"><span className="text-muted-foreground">Extraction revision:</span> <span className="break-all">{formatRevision(session)}</span></div>
          </div>

          {['queued', 'running'].includes(session.status) && (
            <p className="text-muted-foreground text-sm">
              Starting subjects processed: {session.completed_starts || 0} of {session.starts.length}
            </p>
          )}
          {session.error && <p className="text-destructive text-sm">{session.error}</p>}
          {(session.seed_errors || []).map((failure) => (
            <p key={failure.start} className="text-amber-600 text-sm break-words">
              {failure.start}: {failure.error}
            </p>
          ))}
          {(session.seed_diagnostics || []).map((item) => (
            <p key={item.start} className="text-muted-foreground text-sm">
              {item.start}: {item.paths_examined} retrieved paths, {item.eligible_paths} eligible before session selection.
              {Object.entries(item.excluded_paths || {}).map(([reason, count]) =>
                ` ${exclusionLabels[reason] || reason}: ${count}.`
              )}
            </p>
          ))}
          {(session.seed_diagnostics || []).filter((item) => item.eligible_paths === 0 && !item.excluded_paths).map((item) => (
            <p key={item.start} className="text-muted-foreground text-sm">
              {item.start}: {item.paths_examined === 0
                ? 'No directed paths were found from this node.'
                : `${item.paths_examined} directed paths were found, but none met the source and cross-area review filters.`}
            </p>
          ))}
          {session.status === 'completed' && !session.seed_diagnostics?.length && candidates.length < session.limit && (
            <p className="text-muted-foreground text-sm">
              Only {candidates.length} eligible {candidates.length === 1 ? 'path' : 'paths'} found for {session.starts.join(', ')}.
              Try another starting node or hop depth in a new session; increasing the case limit alone will not add paths.
            </p>
          )}

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="font-medium">Review progress</span>
              <span className="text-muted-foreground">{reviewedCount} of {candidates.length} reviewed</span>
            </div>
            <Progress value={progress} className="h-2" aria-label={`${reviewedCount} of ${candidates.length} reviewed`} />
          </div>

          {candidates.length === 0 ? (
            <div className="border-y py-12 text-center text-sm text-muted-foreground">
              {['queued', 'running'].includes(session.status)
                ? 'Candidates are being prepared. This view refreshes automatically.'
                : 'This session has no candidates.'}
            </div>
          ) : (
            <div className="grid min-w-0 gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
              <div className="max-h-[72vh] space-y-1 overflow-auto border-r pr-3">
                {candidates.map((candidate, index) => {
                  const reviewed = latestReviews.has(candidate.id)
                  const selected = candidate.id === selectedCandidateId
                  return (
                    <button
                      key={candidate.id}
                      type="button"
                      onClick={() => setSelectedCandidateId(candidate.id)}
                      className={`flex w-full items-start gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors ${selected ? 'bg-accent text-accent-foreground' : 'hover:bg-muted/60'}`}
                    >
                      {reviewed ? <CheckCircle2Icon className="mt-0.5 size-4 shrink-0 text-emerald-400" /> : <CircleIcon className="mt-0.5 size-4 shrink-0 text-amber-400" />}
                      <span className="min-w-0 flex-1">
                        <span className="block text-xs text-muted-foreground">Case {index + 1} · {reviewed ? 'Reviewed' : 'Unreviewed'}</span>
                        <span className="mt-0.5 block break-words">{candidate.from} to {candidate.to}</span>
                      </span>
                    </button>
                  )
                })}
              </div>

              {selectedCandidate && (
                <ReviewEditor
                  key={`${session.id}-${selectedCandidate.id}-${reviewer}-${latestReviews.get(selectedCandidate.id)?.updated_at || latestReviews.get(selectedCandidate.id)?.created_at || 'new'}`}
                  sessionId={session.id}
                  candidate={selectedCandidate}
                  reviewer={reviewer}
                  review={latestReviews.get(selectedCandidate.id)}
                  isSaving={isSaving}
                  onSave={saveReview}
                  onPrevious={() => setSelectedCandidateId(candidates[selectedIndex - 1]?.id || selectedCandidate.id)}
                  onNext={() => setSelectedCandidateId(candidates[selectedIndex + 1]?.id || selectedCandidate.id)}
                  hasPrevious={selectedIndex > 0}
                  hasNext={selectedIndex < candidates.length - 1}
                />
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
