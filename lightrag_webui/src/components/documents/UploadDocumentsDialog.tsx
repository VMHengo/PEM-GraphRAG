import { useState, useCallback } from 'react'
import { FileRejection } from 'react-dropzone'
import Button from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/Dialog'
import FileUploader from '@/components/ui/FileUploader'
import { toast } from 'sonner'
import { errorMessage } from '@/lib/utils'
import { confirmDocumentExtraction, getTrackStatus, uploadDocument } from '@/api/lightrag'
import type { DocStatusResponse } from '@/api/lightrag'

import { Loader2Icon, UploadIcon } from 'lucide-react'
import { useTranslation } from 'react-i18next'

const ESTIMATE_SECONDS_PER_CHUNK_LOW = 5
const ESTIMATE_SECONDS_PER_CHUNK_HIGH = 15
const ESTIMATE_INPUT_TOKENS_PER_CHUNK = 3000
const ESTIMATE_OUTPUT_TOKENS_PER_CHUNK = 800
const GPT_4_1_INPUT_USD_PER_1M = 2
const GPT_4_1_OUTPUT_USD_PER_1M = 8
const WARN_CHUNKS = 80
const WARN_COST_USD = 0.05

interface UploadDocumentsDialogProps {
  onDocumentsUploaded?: () => Promise<void>
  /**
   * Fired once per batch as soon as the first file is accepted by the server.
   * Lets the parent start its activity probe as early as possible (rather
   * than waiting for the whole sequential batch to finish).
   */
  onUploadBatchAccepted?: () => void
}

interface UploadEstimate {
  fileCount: number
  estimatedTextLength: number
  estimatedChunks: number
  estimatedInputTokens: number
  estimatedOutputTokens: number
  estimatedCostUsd: number
  estimatedMinutesLow: number
  estimatedMinutesHigh: number
  warnings: string[]
}

const formatNumber = (value: number) => new Intl.NumberFormat().format(value)

const formatCost = (value: number) =>
  new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: value < 0.1 ? 3 : 2,
    maximumFractionDigits: value < 0.1 ? 3 : 2
  }).format(value)

const estimateChunkedDocuments = (documents: DocStatusResponse[]): UploadEstimate => {
  const estimatedTextLength = documents.reduce((sum, doc) => sum + (doc.content_length ?? 0), 0)
  const estimatedChunks = Math.max(
    1,
    documents.reduce((sum, doc) => sum + (doc.chunks_count ?? 0), 0)
  )
  const estimatedInputTokens = estimatedChunks * ESTIMATE_INPUT_TOKENS_PER_CHUNK
  const estimatedOutputTokens = estimatedChunks * ESTIMATE_OUTPUT_TOKENS_PER_CHUNK
  const estimatedCostUsd =
    (estimatedInputTokens / 1_000_000) * GPT_4_1_INPUT_USD_PER_1M +
    (estimatedOutputTokens / 1_000_000) * GPT_4_1_OUTPUT_USD_PER_1M
  const estimatedMinutesLow = Math.ceil((estimatedChunks * ESTIMATE_SECONDS_PER_CHUNK_LOW) / 60)
  const estimatedMinutesHigh = Math.ceil((estimatedChunks * ESTIMATE_SECONDS_PER_CHUNK_HIGH) / 60)
  const warnings = []

  if (estimatedChunks >= WARN_CHUNKS) {
    warnings.push(`Large ingestion: estimated ${formatNumber(estimatedChunks)} chunks.`)
  }
  if (estimatedCostUsd >= WARN_COST_USD) {
    warnings.push(`Estimated LLM extraction cost exceeds ${formatCost(WARN_COST_USD)}.`)
  }

  return {
    fileCount: documents.length,
    estimatedTextLength,
    estimatedChunks,
    estimatedInputTokens,
    estimatedOutputTokens,
    estimatedCostUsd,
    estimatedMinutesLow,
    estimatedMinutesHigh,
    warnings
  }
}

const waitForChunking = async (trackId: string): Promise<DocStatusResponse[]> => {
  const maxAttempts = 360
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const status = await getTrackStatus(trackId)
    const documents = status.documents ?? []
    const failed = documents.filter((doc) => doc.status === 'failed')
    if (failed.length > 0) {
      throw new Error(failed[0].error_msg || 'Chunking failed')
    }
    const chunked = documents.filter((doc) => doc.metadata?.skip_kg && doc.chunks_count)
    if (chunked.length > 0 && chunked.length === documents.length) {
      return chunked
    }
    await new Promise((resolve) => setTimeout(resolve, 2000))
  }
  throw new Error('Timed out while waiting for chunking to finish')
}

export default function UploadDocumentsDialog({
  onDocumentsUploaded,
  onUploadBatchAccepted
}: UploadDocumentsDialogProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [progresses, setProgresses] = useState<Record<string, number>>({})
  const [fileErrors, setFileErrors] = useState<Record<string, string>>({})
  const [pendingDocs, setPendingDocs] = useState<DocStatusResponse[]>([])
  const [pendingEstimate, setPendingEstimate] = useState<UploadEstimate | null>(null)

  const closeEstimateDialog = useCallback(() => {
    if (isUploading) {
      return
    }
    setPendingDocs([])
    setPendingEstimate(null)
  }, [isUploading])

  const handleRejectedFiles = useCallback(
    (rejectedFiles: FileRejection[]) => {
      // Process rejected files and add them to fileErrors
      rejectedFiles.forEach(({ file, errors }) => {
        // Get the first error message
        let errorMsg = errors[0]?.message || t('documentPanel.uploadDocuments.fileUploader.fileRejected', { name: file.name })

        // Simplify error message for unsupported file types
        if (errorMsg.includes('file-invalid-type')) {
          errorMsg = t('documentPanel.uploadDocuments.fileUploader.unsupportedType')
        }

        // Set progress to 100% to display error message
        setProgresses((pre) => ({
          ...pre,
          [file.name]: 100
        }))

        // Add error message to fileErrors
        setFileErrors(prev => ({
          ...prev,
          [file.name]: errorMsg
        }))
      })
    },
    [setProgresses, setFileErrors, t]
  )

  const handleDocumentsUpload = useCallback(
    async (filesToUpload: File[]) => {
      setIsUploading(true)
      let hasSuccessfulUpload = false

      // Only clear errors for files that are being uploaded, keep errors for rejected files
      setFileErrors(prev => {
        const newErrors = { ...prev };
        filesToUpload.forEach(file => {
          delete newErrors[file.name];
        });
        return newErrors;
      });

      // Show uploading toast
      const toastId = toast.loading('Uploading and chunking document(s)')

      try {
        // Track errors locally to ensure we have the final state
        const uploadErrors: Record<string, string> = {}
        let batchProbeTriggered = false
        const preparedDocs: DocStatusResponse[] = []

        // Create a collator that supports Chinese sorting
        const collator = new Intl.Collator(['zh-CN', 'en'], {
          sensitivity: 'accent',  // consider basic characters, accents, and case
          numeric: true           // enable numeric sorting, e.g., "File 10" will be after "File 2"
        });
        const sortedFiles = [...filesToUpload].sort((a, b) =>
          collator.compare(a.name, b.name)
        );

        // Upload files in sequence, not parallel
        for (const file of sortedFiles) {
          try {
            // Initialize upload progress
            setProgresses((pre) => ({
              ...pre,
              [file.name]: 0
            }))

            const result = await uploadDocument(file, (percentCompleted: number) => {
              console.debug(t('documentPanel.uploadDocuments.single.uploading', { name: file.name, percent: percentCompleted }))
              setProgresses((pre) => ({
                ...pre,
                [file.name]: percentCompleted
              }))
            }, { deferExtraction: true })

            if (result.status !== 'success') {
              uploadErrors[file.name] = result.message
              setFileErrors(prev => ({
                ...prev,
                [file.name]: result.message
              }))
            } else {
              // Mark that we had at least one successful upload
              hasSuccessfulUpload = true
              if (!batchProbeTriggered) {
                batchProbeTriggered = true
                onUploadBatchAccepted?.()
              }
              if (result.track_id) {
                const chunkedDocs = await waitForChunking(result.track_id)
                preparedDocs.push(...chunkedDocs)
              }
            }
          } catch (err) {
            console.error(`Upload failed for ${file.name}:`, err)

            // Handle HTTP errors, including 400 errors
            let errorMsg = errorMessage(err)
            const duplicateFileMsg = t('documentPanel.uploadDocuments.fileUploader.duplicateFile')

            // If it's an axios error with response data, try to extract more detailed error info
            if (err && typeof err === 'object' && 'response' in err) {
              const axiosError = err as { response?: { status: number, data?: { detail?: string } } }
              const status = axiosError.response?.status
              const detail = axiosError.response?.data?.detail
              if (status === 409) {
                // Server now rejects same-name uploads with HTTP 409 instead of
                // returning a 200 ``status="duplicated"`` payload.  Map the most
                // common cases (existing record / file in INPUT dir) back to the
                // dedicated "duplicate file" UI affordance, and surface other
                // 409 reasons (pipeline busy / scanning) verbatim from the
                // server detail so users can tell why they were rejected.
                if (
                  typeof detail === 'string' &&
                  (/already contains/i.test(detail) || /Status:/i.test(detail))
                ) {
                  errorMsg = duplicateFileMsg
                } else {
                  errorMsg = detail || errorMsg
                }
              } else if (status === 400) {
                errorMsg = detail || errorMsg
              }

              // Set progress to 100% to display error message
              setProgresses((pre) => ({
                ...pre,
                [file.name]: 100
              }))
            }

            // Record error message in both local tracking and state
            uploadErrors[file.name] = errorMsg
            setFileErrors(prev => ({
              ...prev,
              [file.name]: errorMsg
            }))
          }
        }

        // Check if any files failed to upload using our local tracking
        const hasErrors = Object.keys(uploadErrors).length > 0

        // Update toast status
        if (hasErrors) {
          toast.error(t('documentPanel.uploadDocuments.batch.error'), { id: toastId })
        } else {
          toast.success('Chunking complete. Confirm extraction to continue.', { id: toastId })
          setPendingDocs(preparedDocs)
          setPendingEstimate(estimateChunkedDocuments(preparedDocs))
        }

        // Only update if at least one file was uploaded successfully
        if (hasSuccessfulUpload) {
          // Refresh document list
          if (onDocumentsUploaded) {
            onDocumentsUploaded().catch(err => {
              console.error('Error refreshing documents:', err)
            })
          }
        }
      } catch (err) {
        console.error('Unexpected error during upload:', err)
        toast.error(t('documentPanel.uploadDocuments.generalError', { error: errorMessage(err) }), { id: toastId })
      } finally {
        setIsUploading(false)
      }
    },
    [setIsUploading, setProgresses, setFileErrors, t, onDocumentsUploaded, onUploadBatchAccepted]
  )

  const handleConfirmUpload = useCallback(async () => {
    const docs = pendingDocs
    setIsUploading(true)
    try {
      for (const doc of docs) {
        await confirmDocumentExtraction(doc.id)
      }
      toast.success('Extraction queued')
      setPendingDocs([])
      setPendingEstimate(null)
      if (onDocumentsUploaded) {
        onDocumentsUploaded().catch(err => {
          console.error('Error refreshing documents:', err)
        })
      }
    } catch (err) {
      toast.error(`Failed to queue extraction: ${errorMessage(err)}`)
    } finally {
      setIsUploading(false)
    }
  }, [onDocumentsUploaded, pendingDocs])

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(nextOpen) => {
          if (!nextOpen && !isUploading) {
            setProgresses({})
            setFileErrors({})
            setPendingDocs([])
            setPendingEstimate(null)
          }
          setOpen(nextOpen)
        }}
      >
        <DialogTrigger asChild>
          <Button variant="default" side="bottom" tooltip={t('documentPanel.uploadDocuments.tooltip')} size="sm">
            <UploadIcon /> {t('documentPanel.uploadDocuments.button')}
          </Button>
        </DialogTrigger>
        <DialogContent className="sm:max-w-xl" onCloseAutoFocus={(e) => e.preventDefault()}>
          <DialogHeader>
            <DialogTitle>{t('documentPanel.uploadDocuments.title')}</DialogTitle>
            <DialogDescription>
              {t('documentPanel.uploadDocuments.description')}
            </DialogDescription>
          </DialogHeader>
          <FileUploader
            maxFileCount={Infinity}
            maxSize={200 * 1024 * 1024}
            description={t('documentPanel.uploadDocuments.fileTypes')}
            onUpload={handleDocumentsUpload}
            onReject={handleRejectedFiles}
            progresses={progresses}
            fileErrors={fileErrors}
            disabled={isUploading}
          />
          {isUploading && (
            <div className="mt-4 flex items-start gap-3 rounded-md border bg-muted/40 p-3 text-sm">
              <Loader2Icon className="mt-0.5 h-4 w-4 shrink-0 animate-spin" />
              <div>
                <div className="font-medium">Preparing document chunks</div>
                <div className="text-muted-foreground">
                  Upload and chunking are running in the background. You can close this window; the extraction estimate
                  will appear when chunking finishes.
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={pendingEstimate !== null} onOpenChange={(nextOpen) => {
        if (!nextOpen) closeEstimateDialog()
      }}>
        <DialogContent className="sm:max-w-lg" onCloseAutoFocus={(e) => e.preventDefault()}>
          <DialogHeader>
            <DialogTitle>Confirm document ingestion</DialogTitle>
            <DialogDescription>
              Review the estimated processing time and LLM extraction cost before extraction starts.
            </DialogDescription>
          </DialogHeader>
          {pendingEstimate && (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-3 rounded-md border p-3">
                <div>
                  <div className="text-muted-foreground">Files</div>
                  <div className="font-medium">{pendingEstimate.fileCount}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Stage</div>
                  <div className="font-medium">Chunked, awaiting extraction</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Estimated text length</div>
                  <div className="font-medium">{formatNumber(pendingEstimate.estimatedTextLength)} chars</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Estimated chunks</div>
                  <div className="font-medium">{formatNumber(pendingEstimate.estimatedChunks)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Estimated time</div>
                  <div className="font-medium">
                    {pendingEstimate.estimatedMinutesLow}-{pendingEstimate.estimatedMinutesHigh} min
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Estimated cost</div>
                  <div className="font-medium">{formatCost(pendingEstimate.estimatedCostUsd)}</div>
                </div>
              </div>

              <div className="rounded-md border p-3">
                <div className="font-medium">Token estimate</div>
                <div className="mt-1 text-muted-foreground">
                  Input: {formatNumber(pendingEstimate.estimatedInputTokens)} tokens, output:{' '}
                  {formatNumber(pendingEstimate.estimatedOutputTokens)} tokens. Assumes GPT-4.1 standard pricing
                  at $2 / 1M input tokens and $8 / 1M output tokens.
                </div>
              </div>

              {pendingEstimate.warnings.length > 0 && (
                <div className="rounded-md border border-yellow-500/40 bg-yellow-500/10 p-3 text-yellow-700 dark:text-yellow-300">
                  <div className="font-medium">Warnings</div>
                  <ul className="mt-1 list-disc space-y-1 pl-5">
                    {pendingEstimate.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={closeEstimateDialog} disabled={isUploading}>
              Cancel
            </Button>
            <Button onClick={handleConfirmUpload} disabled={isUploading}>
              Start extraction
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
