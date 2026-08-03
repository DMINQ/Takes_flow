import { useEffect, useRef, useState } from 'react'
import { createJob, pollJob, type ApiError } from '../api/client'
import type { JobResponse } from '../types/api'
import { useAppStore, type CutSelection } from '../store/appStore'

/**
 * Builds the export_selection param: one "cut:{start}:{end}" string per
 * REVIEW region marked for removal, using the exact raw float values (no
 * rounding) so the backend can match them precisely against the timeline.
 */
function buildExportSelection(cuts: CutSelection[]): string[] {
  return cuts.map((cut) => `cut:${cut.start}:${cut.end}`)
}

export function ExportScreen() {
  const mediaId = useAppStore((s) => s.mediaId)
  const cutsToRemove = useAppStore((s) => s.cutsToRemove)
  const setStep = useAppStore((s) => s.setStep)
  const setExportJobId = useAppStore((s) => s.setExportJobId)
  const [job, setJob] = useState<JobResponse | null>(null)
  const [simplifiedError, setSimplifiedError] = useState<string | null>(null)
  const startedRef = useRef(false)

  useEffect(() => {
    if (!mediaId || startedRef.current) return
    startedRef.current = true

    async function run() {
      try {
        const exportSelection = buildExportSelection(Array.from(cutsToRemove.values()))
        const { jobId } = await createJob(mediaId!, 'export', { export_selection: exportSelection })
        setExportJobId(jobId)
        const finalJob = await pollJob(jobId, (progressJob) => setJob(progressJob))
        setJob(finalJob)
        if (finalJob.status === 'completed') {
          setStep('download')
        } else {
          console.error('Export job failed', finalJob.error)
          setSimplifiedError('Не удалось собрать экспорт. Попробуйте ещё раз.')
        }
      } catch (err) {
        console.error('Export job error', err)
        const apiErr = err as ApiError
        setSimplifiedError(apiErr.message || 'Произошла ошибка при экспорте.')
      }
    }

    run()
  }, [mediaId, cutsToRemove, setStep, setExportJobId])

  if (!mediaId) {
    return <p>Сначала загрузите файл.</p>
  }

  return (
    <div className="screen export-screen">
      <h1>Экспорт</h1>
      <p>Собираем финальный файл с учётом отмеченных вырезаний...</p>

      {job && !simplifiedError && (
        <div className="progress">
          <div className="progress__bar" style={{ width: `${Math.round(job.progress * 100)}%` }} />
          <span>{Math.round(job.progress * 100)}%</span>
        </div>
      )}

      <p className="status-text">Статус: {job?.status ?? 'ожидание запуска'}</p>

      {simplifiedError && (
        <div>
          <p className="error-text">{simplifiedError}</p>
          <button type="button" onClick={() => setStep('timeline')}>
            Вернуться к таймлайну
          </button>
        </div>
      )}
    </div>
  )
}
