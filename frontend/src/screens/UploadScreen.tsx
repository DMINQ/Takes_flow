import { useCallback, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { uploadFile } from '../api/client'
import { useAppStore } from '../store/appStore'

export function UploadScreen() {
  const [isDragging, setIsDragging] = useState(false)
  const [progressPercent, setProgressPercent] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const projectId = useAppStore((s) => s.projectId)
  const setMediaId = useAppStore((s) => s.setMediaId)
  const setStep = useAppStore((s) => s.setStep)

  const mutation = useMutation({
    mutationFn: (file: File) =>
      uploadFile(
        file,
        ({ loadedBytes, totalBytes }) => {
          setProgressPercent(totalBytes > 0 ? Math.round((loadedBytes / totalBytes) * 100) : 0)
        },
        projectId,
      ),
    onSuccess: ({ mediaId }) => {
      setMediaId(mediaId)
      setStep('analysis')
    },
  })

  const handleFile = useCallback(
    (file: File | undefined) => {
      if (!file) return
      setProgressPercent(0)
      mutation.mutate(file)
    },
    [mutation],
  )

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      setIsDragging(false)
      handleFile(e.dataTransfer.files[0])
    },
    [handleFile],
  )

  return (
    <div className="screen upload-screen">
      <h1>{projectId ? 'Добавить файл в проект' : 'Загрузка аудио'}</h1>
      {projectId && (
        <button type="button" onClick={() => setStep('projects')}>
          ← Назад к проектам
        </button>
      )}
      <div
        className={`dropzone${isDragging ? ' dropzone--active' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragging(true)
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
      >
        <p>Перетащите файл сюда или нажмите, чтобы выбрать</p>
        <input
          ref={inputRef}
          type="file"
          accept="audio/*,video/*"
          hidden
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>

      {mutation.isPending && (
        <div className="progress">
          <div className="progress__bar" style={{ width: `${progressPercent}%` }} />
          <span>{progressPercent}%</span>
        </div>
      )}

      {mutation.isError && (
        <p className="error-text">
          Не удалось загрузить файл. Попробуйте ещё раз.
        </p>
      )}
    </div>
  )
}
