import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeftIcon, ChevronLeftIcon, ChevronRightIcon, ExternalLinkIcon, Loader2Icon, MinusIcon, PlusIcon } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import {
  ExplorationReview,
  ExplorationSession,
  ExplorationSource,
  fetchSourcePdf,
  getExplorationSession,
  locateSourcePdf,
  sourcePdfUrl
} from '@/api/lightrag'
import Button from '@/components/ui/Button'
import { webuiPrefix } from '@/lib/constants'
import { errorMessage } from '@/lib/utils'
import { matchingTextItemIndexes, sourceDocumentId, sourceEvidenceQuote } from '@/lib/reviewSource'
import { getDocument, GlobalWorkerOptions, TextLayer, type PDFDocumentProxy } from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

GlobalWorkerOptions.workerSrc = pdfWorkerUrl

type ViewerSource = ExplorationSource

const positiveInteger = (value: string | null): number | null => {
  if (value === null || value === '') return null
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null
}

const reviewTimestamp = (review: ExplorationReview): number => {
  const value = review.updated_at || review.created_at || ''
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? 0 : parsed
}

const pageContainsQuote = async (
  pdf: PDFDocumentProxy,
  pageNumber: number,
  quote: string
): Promise<boolean> => {
  if (!quote || pageNumber < 1 || pageNumber > pdf.numPages) return false
  const page = await pdf.getPage(pageNumber)
  const content = await page.getTextContent()
  const items = content.items.flatMap((item) => 'str' in item ? [item.str] : [])
  return matchingTextItemIndexes(items, quote).length > 0
}

function PdfPage({
  pdf,
  pageNumber,
  quote,
  zoom,
  onTextMatch
}: {
  pdf: PDFDocumentProxy
  pageNumber: number
  quote: string
  zoom: number
  onTextMatch: (pageNumber: number, matched: boolean) => void
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const textLayerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    let renderTask: ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']> | null = null
    let textLayer: TextLayer | null = null

    const render = async () => {
      const page = await pdf.getPage(pageNumber)
      if (cancelled) return
      const viewport = page.getViewport({ scale: zoom })
      const canvas = canvasRef.current
      const textContainer = textLayerRef.current
      if (!canvas || !textContainer) return

      canvas.width = Math.ceil(viewport.width)
      canvas.height = Math.ceil(viewport.height)
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`
      textContainer.replaceChildren()
      textContainer.style.width = `${viewport.width}px`
      textContainer.style.height = `${viewport.height}px`
      textContainer.style.setProperty('--total-scale-factor', String(viewport.scale))

      renderTask = page.render({ canvas, viewport })
      const textContent = await page.getTextContent()
      if (cancelled) return
      textLayer = new TextLayer({ textContentSource: textContent, container: textContainer, viewport })
      await Promise.all([renderTask.promise, textLayer.render()])
      if (cancelled) return

      const matchedIndexes = matchingTextItemIndexes(textLayer.textContentItemsStr, quote)
      textLayer.textDivs.forEach((element, index) => {
        if (matchedIndexes.includes(index)) element.classList.add('pdf-evidence-hit')
      })
      onTextMatch(pageNumber, matchedIndexes.length > 0)
      textLayer.textDivs[matchedIndexes[0]]?.scrollIntoView({ block: 'center', inline: 'center' })
    }

    void render().catch(() => onTextMatch(pageNumber, false))
    return () => {
      cancelled = true
      renderTask?.cancel()
      textLayer?.cancel()
    }
  }, [onTextMatch, pageNumber, pdf, quote, zoom])

  return (
    <div className="relative shrink-0 bg-white shadow-lg" aria-label={`PDF page ${pageNumber}`}>
      <canvas ref={canvasRef} className="block" />
      <div ref={textLayerRef} className="pdf-source-text-layer" />
    </div>
  )
}

export default function ReviewSourceViewer() {
  const [params] = useSearchParams()
  const sessionId = params.get('sessionId') || ''
  const candidateId = params.get('candidateId') || ''
  const hopIndex = positiveInteger(params.get('hopIndex'))
  const sourceIndex = positiveInteger(params.get('sourceIndex'))
  const routeIsValid = Boolean(sessionId && candidateId && hopIndex != null && sourceIndex != null)
  const [session, setSession] = useState<ExplorationSession | null>(null)
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [pageNumber, setPageNumber] = useState(1)
  const [zoom, setZoom] = useState(1.25)
  const [loading, setLoading] = useState(routeIsValid)
  const [loadError, setLoadError] = useState(routeIsValid ? '' : 'The source link is incomplete.')
  const [matchedPage, setMatchedPage] = useState<number | null>(null)
  const [verifiedQuotePage, setVerifiedQuotePage] = useState<number | null>(null)

  const candidate = session?.candidates.find((item) => item.id === candidateId)
  const hop = hopIndex == null ? undefined : candidate?.path[hopIndex]
  const source: ViewerSource | undefined = sourceIndex == null ? undefined : hop?.sources[sourceIndex]
  const documentId = source ? sourceDocumentId(source) : null
  const quote = source ? sourceEvidenceQuote(source) : ''
  const latestReview = useMemo(() => {
    return [...(session?.reviews || [])]
      .filter((review) => review.candidate_id === candidateId)
      .sort((left, right) => reviewTimestamp(right) - reviewTimestamp(left))[0]
  }, [candidateId, session?.reviews])

  const hasTextMatch = matchedPage === pageNumber

  useEffect(() => {
    if (!sessionId || !candidateId || hopIndex == null || sourceIndex == null) {
      return
    }
    let cancelled = false
    let loadedPdf: PDFDocumentProxy | null = null

    const load = async () => {
      setLoading(true)
      setLoadError('')
      const response = await getExplorationSession(sessionId)
      if (cancelled) return
      const loadedSession = response.session
      const loadedCandidate = loadedSession.candidates.find((item) => item.id === candidateId)
      const loadedSource = loadedCandidate?.path[hopIndex]?.sources[sourceIndex]
      if (!loadedCandidate || !loadedSource) throw new Error('The selected review source no longer exists.')
      const loadedDocumentId = sourceDocumentId(loadedSource)
      if (!loadedDocumentId) throw new Error('No original PDF is linked to this source.')

      setSession(loadedSession)
      const loadedQuote = sourceEvidenceQuote(loadedSource)
      const bytes = await fetchSourcePdf(loadedDocumentId)
      const task = getDocument({ data: new Uint8Array(bytes) })
      loadedPdf = await task.promise
      if (cancelled) {
        await loadedPdf.destroy()
        return
      }

      const pageCandidates = [
        loadedSource.pdf_location?.page,
        ...(loadedSource.pdf_location?.pages || [])
      ].filter((page, index, pages): page is number => (
        Number.isInteger(page) && page > 0 && pages.indexOf(page) === index
      ))
      let pageHint: number | null = null
      const matchingPages: number[] = []
      for (const candidatePage of pageCandidates) {
        if (await pageContainsQuote(loadedPdf, candidatePage, loadedQuote)) {
          matchingPages.push(candidatePage)
        }
      }
      if (matchingPages.length === 1) pageHint = matchingPages[0]
      if (!pageHint && loadedQuote) {
        try {
          pageHint = (await locateSourcePdf(loadedDocumentId, loadedQuote.slice(0, 1000))).page
        } catch {
          pageHint = null
        }
      }
      setVerifiedQuotePage(pageHint)
      pageHint ||= pageCandidates[0] || null
      setPdf(loadedPdf)
      setPageNumber(Math.min(Math.max(pageHint || 1, 1), loadedPdf.numPages))
    }

    void load()
      .catch((error) => {
        if (!cancelled) setLoadError(errorMessage(error))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
      void loadedPdf?.destroy()
    }
  }, [candidateId, hopIndex, sessionId, sourceIndex])

  const handleTextMatch = useCallback((renderedPage: number, matched: boolean) => {
    setMatchedPage(matched ? renderedPage : null)
  }, [])

  return (
    <main className="bg-muted/30 flex min-h-screen flex-col">
      <header className="bg-background sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <a href={`${webuiPrefix}#/`} className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm">
            <ArrowLeftIcon className="size-4" /> Back to WebUI
          </a>
          <h1 className="mt-1 truncate text-base font-semibold">{source?.document || 'PDF evidence'}</h1>
        </div>
        {documentId && (
          <a href={sourcePdfUrl(documentId)} target="_blank" rel="noreferrer" className="text-primary inline-flex items-center gap-1 text-sm hover:underline">
            Open original PDF <ExternalLinkIcon className="size-4" />
          </a>
        )}
      </header>

      {loading ? (
        <div className="flex flex-1 items-center justify-center gap-2 py-24 text-sm"><Loader2Icon className="size-5 animate-spin" /> Loading review source...</div>
      ) : loadError ? (
        <div className="mx-auto mt-12 max-w-xl border border-red-500/30 bg-red-500/5 p-5 text-sm text-red-600">{loadError}</div>
      ) : source && hop && pdf ? (
        <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_360px]">
          <section className="min-w-0 overflow-auto p-4">
            <div className="bg-background sticky top-0 z-10 mx-auto mb-4 flex w-fit items-center gap-2 border p-1 shadow-sm">
              <Button variant="ghost" size="icon" onClick={() => setPageNumber((value) => Math.max(1, value - 1))} disabled={pageNumber <= 1} tooltip="Previous page"><ChevronLeftIcon /></Button>
              <span className="min-w-24 text-center text-sm">Page {pageNumber} / {pdf.numPages}</span>
              <Button variant="ghost" size="icon" onClick={() => setPageNumber((value) => Math.min(pdf.numPages, value + 1))} disabled={pageNumber >= pdf.numPages} tooltip="Next page"><ChevronRightIcon /></Button>
              <span className="border-l pl-2" />
              <Button variant="ghost" size="icon" onClick={() => setZoom((value) => Math.max(0.75, value - 0.25))} disabled={zoom <= 0.75} tooltip="Zoom out"><MinusIcon /></Button>
              <span className="min-w-12 text-center text-xs">{Math.round(zoom * 100)}%</span>
              <Button variant="ghost" size="icon" onClick={() => setZoom((value) => Math.min(2.5, value + 0.25))} disabled={zoom >= 2.5} tooltip="Zoom in"><PlusIcon /></Button>
            </div>
            <div className="flex min-w-max justify-center pb-12">
              <PdfPage pdf={pdf} pageNumber={pageNumber} quote={verifiedQuotePage === pageNumber ? quote : ''} zoom={zoom} onTextMatch={handleTextMatch} />
            </div>
          </section>

          <aside className="bg-background space-y-5 overflow-auto border-l p-5">
            <section>
              <p className="text-muted-foreground text-xs font-medium uppercase">Graph assertion</p>
              <p className="mt-2 break-words text-sm font-semibold">
                {hop.source} <span className="text-muted-foreground">[{hop.relation}]</span> {hop.target}
              </p>
              {hop.description && <p className="text-muted-foreground mt-2 break-words text-sm">{hop.description}</p>}
            </section>

            <section className="border-t pt-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-muted-foreground text-xs font-medium uppercase">Evidence to verify</p>
                <span className={`text-xs ${hasTextMatch ? 'text-emerald-600' : 'text-amber-600'}`}>
                  {hasTextMatch ? 'Marked verbatim in PDF' : 'No verbatim mark on this page'}
                </span>
              </div>
              <blockquote className="mt-2 border-l-2 border-amber-500 bg-amber-500/5 px-3 py-2 text-sm break-words">
                {quote || 'No exact relation quote was stored for this source.'}
              </blockquote>
              {source.pdf_location?.status && (
                <p className="text-muted-foreground mt-2 text-xs">Source location: {source.pdf_location.status}</p>
              )}
            </section>

            <section className="border-t pt-4">
              <p className="text-muted-foreground text-xs font-medium uppercase">Review comment</p>
              {latestReview ? (
                <div className="mt-2 space-y-2">
                  <p className="text-muted-foreground text-xs">Reviewed by {latestReview.reviewer}</p>
                  <p className="whitespace-pre-wrap break-words text-sm">{latestReview.note || 'No comment recorded.'}</p>
                </div>
              ) : (
                <p className="text-muted-foreground mt-2 text-sm">No review exists yet. Return to Human Review to assess the complete path.</p>
              )}
            </section>
          </aside>
        </div>
      ) : null}
    </main>
  )
}
