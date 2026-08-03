// Types mirroring backend Pydantic schemas (backend/src/api/schemas/*).
// Keep in sync with backend/src/domain/enums.py and backend/src/api/schemas/*.py.

// --- Uploads ---

export type UploadMode = 'single' | 'multipart'

export interface TicketOut {
  url: string
  method: string
  headers: Record<string, string>
  expires_at: string | null
}

export interface PartTicketOut {
  part_number: number
  url: string
  method: string
  headers: Record<string, string>
}

export interface UploadInitResponse {
  session_id: string
  project_id: string
  mode: UploadMode
  storage_key: string
  part_size: number | null
  part_count: number | null
  single: TicketOut | null
  parts: PartTicketOut[]
  expires_at: string | null
}

export interface CompletedPart {
  part_number: number
  etag: string
}

export interface UploadCompleteRequest {
  parts: CompletedPart[]
}

export interface MediaOut {
  file_id: string
  project_id: string
  filename: string
  size_bytes: number
  content_type: string | null
  checksum: string | null
}

// --- Jobs ---

export type JobKind = 'analysis' | 'export'

export type JobStatus = 'pending' | 'queued' | 'processing' | 'completed' | 'failed'

export interface CreateJobRequest {
  media_id: string
  kind: JobKind
  params?: Record<string, unknown>
}

export interface JobResponse {
  id: string
  media_id: string
  kind: JobKind
  status: JobStatus
  progress: number
  stage: string | null
  error: string | null
}

// Human-readable labels for JobResponse.stage (pipeline plugin names).
export const JOB_STAGE_LABELS: Record<string, string> = {
  ingest: 'Загружаем файл...',
  denoise: 'Убираем шум...',
  diarize: 'Определяем спикеров...',
  cut_silence: 'Вырезаем паузы...',
  transcribe: 'Распознаём речь...',
  bad_take: 'Проверяем дубли...',
  persist_transcript: 'Сохраняем транскрипт...',
  persist_timeline: 'Сохраняем таймлайн...',
  load_timeline: 'Загружаем таймлайн...',
  assemble_export: 'Собираем итоговый файл...',
  master: 'Мастерим звук...',
  persist_export: 'Сохраняем экспорт...',
}

// --- Timeline ---

export type RegionKind = 'keep' | 'auto_cut' | 'review'

export type CutReason = 'silence' | 'bad_take' | 'alternate'

export interface RegionOut {
  // NOTE: start/end are raw floats from the backend. Never round them for
  // logic (e.g. building export_selection) - only format with toFixed for
  // display purposes.
  start: number
  end: number
  kind: RegionKind
  reason: CutReason | null
  take_group: string | null
  text: string | null
  speaker: string | null
}

export interface TimelineResponse {
  media_id: string
  regions: RegionOut[]
}

// --- Media / export ---

export interface ExportDownloadResponse {
  url: string
  method: string
  expires_at: string | null
}

// Response shape for GET /media/{media_id}/source is identical.
export type SourceDownloadResponse = ExportDownloadResponse

// --- Projects ---

export interface ProjectOut {
  id: string
  name: string
  created_at: string | null
  media_count: number
}

export interface ProjectMediaOut {
  id: string
  filename: string
  duration: number | null
  created_at: string | null
  latest_job_id: string | null
  latest_job_kind: JobKind | null
  latest_job_status: JobStatus | null
  latest_job_progress: number | null
  latest_job_stage: string | null
}
