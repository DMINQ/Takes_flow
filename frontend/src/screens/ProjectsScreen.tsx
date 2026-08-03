import { useQuery } from '@tanstack/react-query'
import { listProjectMedia, listProjects } from '../api/client'
import { JOB_STAGE_LABELS, type ProjectMediaOut } from '../types/api'
import { useAppStore } from '../store/appStore'

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function MediaStatus({ media }: { media: ProjectMediaOut }) {
  if (!media.latest_job_id) {
    return <span className="media-status media-status--none">Не анализировался</span>
  }
  if (media.latest_job_status === 'completed') {
    return <span className="media-status media-status--done">Готово</span>
  }
  if (media.latest_job_status === 'failed') {
    return <span className="media-status media-status--failed">Ошибка анализа</span>
  }
  const stageLabel = media.latest_job_stage ? JOB_STAGE_LABELS[media.latest_job_stage] ?? media.latest_job_stage : null
  const percent = Math.round((media.latest_job_progress ?? 0) * 100)
  return (
    <span className="media-status media-status--running">
      {stageLabel ?? 'В обработке'} ({percent}%)
    </span>
  )
}

function ProjectMediaList({ projectId }: { projectId: string }) {
  const setMediaId = useAppStore((s) => s.setMediaId)
  const setAnalysisJobId = useAppStore((s) => s.setAnalysisJobId)
  const setStep = useAppStore((s) => s.setStep)

  const { data, isLoading, error } = useQuery({
    queryKey: ['project-media', projectId],
    queryFn: () => listProjectMedia(projectId),
  })

  if (isLoading) return <p>Загрузка файлов...</p>
  if (error) return <p className="error-text">Не удалось загрузить файлы проекта.</p>

  function openMedia(media: ProjectMediaOut) {
    setMediaId(media.id)
    if (media.latest_job_status === 'completed') {
      setStep('timeline')
    } else if (media.latest_job_id) {
      setAnalysisJobId(media.latest_job_id)
      setStep('analysis')
    } else {
      setStep('analysis')
    }
  }

  return (
    <ul className="project-media-list">
      {data?.map((media) => (
        <li key={media.id} className="project-media-list__item" onClick={() => openMedia(media)}>
          <span className="project-media-list__name">{media.filename}</span>
          <span className="project-media-list__duration">{formatDuration(media.duration)}</span>
          <MediaStatus media={media} />
        </li>
      ))}
      {data?.length === 0 && <li className="project-media-list__empty">В этом проекте пока нет файлов.</li>}
    </ul>
  )
}

export function ProjectsScreen() {
  const setProjectId = useAppStore((s) => s.setProjectId)
  const setMediaId = useAppStore((s) => s.setMediaId)
  const setStep = useAppStore((s) => s.setStep)
  const activeProjectId = useAppStore((s) => s.projectId)

  const { data: projects, isLoading, error } = useQuery({
    queryKey: ['projects'],
    queryFn: listProjects,
  })

  function openProject(projectId: string) {
    setProjectId(projectId)
  }

  function startNewProject() {
    setProjectId(null)
    setMediaId(null)
    setStep('upload')
  }

  function addFileToProject(projectId: string) {
    setProjectId(projectId)
    setMediaId(null)
    setStep('upload')
  }

  return (
    <div className="screen projects-screen">
      <h1>Мои проекты</h1>
      <button type="button" onClick={startNewProject}>
        + Новый проект
      </button>

      {isLoading && <p>Загрузка проектов...</p>}
      {error && <p className="error-text">Не удалось загрузить список проектов.</p>}

      <ul className="project-list">
        {projects?.map((project) => (
          <li key={project.id} className="project-list__item">
            <div className="project-list__header" onClick={() => openProject(project.id)}>
              <span className="project-list__name">{project.name}</span>
              <span className="project-list__count">
                {project.media_count} {project.media_count === 1 ? 'файл' : 'файлов'}
              </span>
            </div>

            {activeProjectId === project.id && (
              <div className="project-list__details">
                <ProjectMediaList projectId={project.id} />
                <button type="button" onClick={() => addFileToProject(project.id)}>
                  + Добавить файл
                </button>
              </div>
            )}
          </li>
        ))}
        {projects?.length === 0 && <li className="project-list__empty">Проектов пока нет. Загрузите первый файл.</li>}
      </ul>
    </div>
  )
}
