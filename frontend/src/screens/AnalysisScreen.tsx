import { useEffect, useRef, useState } from 'react'
import { createJob, pollJob, type ApiError } from '../api/client'
import { JOB_STAGE_LABELS, type JobResponse } from '../types/api'
import { useAppStore } from '../store/appStore'

export function AnalysisScreen() {
  const mediaId = useAppStore((s) => s.mediaId)
  const analysisJobId = useAppStore((s) => s.analysisJobId)
  const setAnalysisJobId = useAppStore((s) => s.setAnalysisJobId)
  const setStep = useAppStore((s) => s.setStep)
  const [job, setJob] = useState<JobResponse | null>(null)
  const [simplifiedError, setSimplifiedError] = useState<string | null>(null)
  const startedRef = useRef(false)

  useEffect(() => {
    if (!mediaId || startedRef.current) return
    startedRef.current = true

    // Coming from the projects list with a job already in flight resumes
    // polling that job instead of starting a duplicate analysis run.
    async function run() {
      try {
        const jobId = analysisJobId ?? (await createJob(mediaId!, 'analysis')).jobId
        setAnalysisJobId(jobId)
        const finalJob = await pollJob(jobId, (progressJob) => setJob(progressJob))
        setJob(finalJob)
        if (finalJob.status === 'completed') {
          setStep('timeline')
        } else {
          // finalJob.status === 'failed'; full error detail is already
          // logged to console by the API client / here for dev diagnostics.
          console.error('Analysis job failed', finalJob.error)
          setSimplifiedError('Не удалось проанализировать файл. Попробуйте загрузить его снова.')
        }
      } catch (err) {
        console.error('Analysis job error', err)
        const apiErr = err as ApiError
        setSimplifiedError(apiErr.message || 'Произошла ошибка при анализе файла.')
      }
    }

    run()
  }, [mediaId, analysisJobId, setAnalysisJobId, setStep])

  if (!mediaId) {
    return <p>Сначала загрузите файл.</p>
  }

  return (
    <div className="screen analysis-screen">
      <h1>Анализ аудио</h1>
      <p>Определяем паузы, дубли дублей и спикеров...</p>

      {job && !simplifiedError && (
        <div className="progress">
          <div className="progress__bar" style={{ width: `${Math.round(job.progress * 100)}%` }} />
          <span>{Math.round(job.progress * 100)}%</span>
        </div>
      )}

      <p className="status-text">
        Статус: {job?.status ?? 'ожидание запуска'}
        {job?.stage ? ` — ${JOB_STAGE_LABELS[job.stage] ?? job.stage}` : ''}
      </p>

      {simplifiedError && (
        <div>
          <p className="error-text">{simplifiedError}</p>
          <button type="button" onClick={() => useAppStore.getState().setStep('upload')}>
            Загрузить другой файл
          </button>
        </div>
      )}
    </div>
  )
}
