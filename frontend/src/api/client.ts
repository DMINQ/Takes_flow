// Minimal fetch-based API client for TakeFlow backend.
// No axios - plain fetch wrapped with small helpers.

import type {
  CompletedPart,
  CreateJobRequest,
  ExportDownloadResponse,
  JobKind,
  JobResponse,
  MediaOut,
  ProjectMediaOut,
  ProjectOut,
  SourceDownloadResponse,
  TimelineResponse,
  UploadCompleteRequest,
  UploadInitResponse,
} from '../types/api'

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const API_PREFIX = '/api/v1'

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })

  if (!res.ok) {
    let detail: unknown = null
    try {
      detail = await res.json()
    } catch {
      // response body was not JSON, ignore
    }
    // Full error detail is logged to console only (dev diagnostics);
    // callers should present a simplified message to the user.
    console.error(`API error ${res.status} on ${path}`, detail)
    const message =
      (detail && typeof detail === 'object' && 'detail' in detail && typeof (detail as { detail: unknown }).detail === 'string'
        ? (detail as { detail: string }).detail
        : null) ?? `Request failed with status ${res.status}`
    throw new ApiError(message, res.status, detail)
  }

  if (res.status === 204) {
    return undefined as T
  }

  return (await res.json()) as T
}

// --- Uploads ---

const MAX_CONCURRENT_PART_UPLOADS = 4
const MAX_PART_UPLOAD_RETRIES = 3

interface UploadProgress {
  loadedBytes: number
  totalBytes: number
}

/**
 * Uploads a raw part/whole file to a presigned URL and returns the ETag
 * from the response headers (S3-compatible storages return it in `ETag`).
 */
async function putToPresignedUrl(
  url: string,
  method: string,
  headers: Record<string, string>,
  body: Blob,
): Promise<string> {
  const res = await fetch(url, {
    method,
    headers,
    body,
  })
  if (!res.ok) {
    throw new ApiError(`Upload PUT failed with status ${res.status}`, res.status, null)
  }
  // Local dev sink returns {"etag": "..."} as JSON; real S3 returns the
  // ETag response header. Support both.
  const headerEtag = res.headers.get('etag') || res.headers.get('ETag')
  if (headerEtag) {
    return headerEtag.replaceAll('"', '')
  }
  try {
    const json = (await res.json()) as { etag?: string }
    if (json.etag) return json.etag
  } catch {
    // no JSON body, ignore
  }
  // Fallback: some storages don't return an identifiable etag in dev mode.
  return `part-${Date.now()}`
}

async function putWithRetry(
  url: string,
  method: string,
  headers: Record<string, string>,
  body: Blob,
): Promise<string> {
  let lastError: unknown
  for (let attempt = 1; attempt <= MAX_PART_UPLOAD_RETRIES; attempt++) {
    try {
      return await putToPresignedUrl(url, method, headers, body)
    } catch (err) {
      lastError = err
      console.error(`Part upload attempt ${attempt} failed`, err)
      if (attempt < MAX_PART_UPLOAD_RETRIES) {
        await new Promise((r) => setTimeout(r, 500 * attempt))
      }
    }
  }
  throw lastError instanceof Error ? lastError : new Error('Part upload failed after retries')
}

/** Runs async tasks with a fixed concurrency limit. */
async function runWithConcurrency<T>(
  tasks: (() => Promise<T>)[],
  limit: number,
): Promise<T[]> {
  const results: T[] = new Array(tasks.length)
  let nextIndex = 0

  async function worker() {
    while (true) {
      const currentIndex = nextIndex++
      if (currentIndex >= tasks.length) return
      results[currentIndex] = await tasks[currentIndex]()
    }
  }

  const workers = Array.from({ length: Math.min(limit, tasks.length) }, () => worker())
  await Promise.all(workers)
  return results
}

export interface UploadFileResult {
  mediaId: string
}

/**
 * Encapsulates the full upload flow: init -> PUT (single or multipart,
 * parallel with retry) -> complete. Reports progress via onProgress.
 */
export async function uploadFile(
  file: File,
  onProgress?: (progress: UploadProgress) => void,
  projectId?: string | null,
): Promise<UploadFileResult> {
  const initResponse = await request<UploadInitResponse>('/uploads', {
    method: 'POST',
    body: JSON.stringify({
      filename: file.name,
      size_bytes: file.size,
      content_type: file.type || null,
      project_id: projectId || null,
    }),
  })

  let completedParts: CompletedPart[] = []
  let uploadedBytes = 0
  const totalBytes = file.size

  if (initResponse.mode === 'single') {
    if (!initResponse.single) {
      throw new Error('Upload init response missing single ticket for single mode')
    }
    const { url, method, headers } = initResponse.single
    await putWithRetry(url, method, headers, file)
    uploadedBytes = totalBytes
    onProgress?.({ loadedBytes: uploadedBytes, totalBytes })
    completedParts = []
  } else {
    const partSize = initResponse.part_size
    if (!partSize || initResponse.parts.length === 0) {
      throw new Error('Upload init response missing part info for multipart mode')
    }

    const tasks = initResponse.parts.map((part) => async () => {
      const start = (part.part_number - 1) * partSize
      const end = Math.min(start + partSize, file.size)
      const chunk = file.slice(start, end)
      const etag = await putWithRetry(part.url, part.method, part.headers, chunk)
      uploadedBytes += chunk.size
      onProgress?.({ loadedBytes: uploadedBytes, totalBytes })
      return { part_number: part.part_number, etag } as CompletedPart
    })

    completedParts = await runWithConcurrency(tasks, MAX_CONCURRENT_PART_UPLOADS)
    completedParts.sort((a, b) => a.part_number - b.part_number)
  }

  const completeBody: UploadCompleteRequest = { parts: completedParts }
  const media = await request<MediaOut>(`/uploads/${initResponse.session_id}/complete`, {
    method: 'POST',
    body: JSON.stringify(completeBody),
  })

  return { mediaId: media.file_id }
}

// --- Jobs ---

export async function createJob(
  mediaId: string,
  kind: JobKind,
  params?: Record<string, unknown>,
): Promise<{ jobId: string }> {
  const body: CreateJobRequest = { media_id: mediaId, kind, params: params ?? {} }
  const job = await request<JobResponse>('/jobs', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return { jobId: job.id }
}

export async function getJob(jobId: string): Promise<JobResponse> {
  return request<JobResponse>(`/jobs/${jobId}`)
}

const POLL_INTERVAL_MS = 3000
const POLL_MAX_ATTEMPTS = 200 // ~10 minutes at 3s interval

/**
 * Polls a job until it reaches a terminal state (completed/failed), or
 * throws once the attempt limit is exceeded.
 */
export async function pollJob(
  jobId: string,
  onProgress?: (job: JobResponse) => void,
): Promise<JobResponse> {
  for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt++) {
    const job = await getJob(jobId)
    onProgress?.(job)
    if (job.status === 'completed' || job.status === 'failed') {
      return job
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
  }
  throw new Error(`Polling job ${jobId} timed out after ${POLL_MAX_ATTEMPTS} attempts`)
}

// --- Timeline ---

export async function getTimeline(mediaId: string): Promise<TimelineResponse> {
  return request<TimelineResponse>(`/timeline/${mediaId}`)
}

// --- Export download ---

export async function getExportUrl(mediaId: string): Promise<ExportDownloadResponse> {
  return request<ExportDownloadResponse>(`/media/${mediaId}/export`)
}

/** Presigned GET URL for the original uploaded source file (for playback). */
export async function getSourceUrl(mediaId: string): Promise<SourceDownloadResponse> {
  return request<SourceDownloadResponse>(`/media/${mediaId}/source`)
}

// --- Projects ---

export async function listProjects(): Promise<ProjectOut[]> {
  return request<ProjectOut[]>('/projects')
}

export async function listProjectMedia(projectId: string): Promise<ProjectMediaOut[]> {
  return request<ProjectMediaOut[]>(`/projects/${projectId}/media`)
}
