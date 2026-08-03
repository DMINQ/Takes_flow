import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getExportUrl } from '../api/client'
import { useAppStore } from '../store/appStore'

function isExpired(expiresAt: string | null): boolean {
  if (!expiresAt) return false
  return new Date(expiresAt).getTime() <= Date.now()
}

export function DownloadScreen() {
  const mediaId = useAppStore((s) => s.mediaId)
  const reset = useAppStore((s) => s.reset)
  const [refreshCount, setRefreshCount] = useState(0)

  const exportQuery = useQuery({
    queryKey: ['export-url', mediaId, refreshCount],
    queryFn: () => getExportUrl(mediaId!),
    enabled: !!mediaId,
  })

  if (!mediaId) {
    return <p>Сначала загрузите файл.</p>
  }

  if (exportQuery.isLoading) {
    return <p>Получаем ссылку на скачивание...</p>
  }

  if (exportQuery.isError) {
    return <p className="error-text">Не удалось получить ссылку на скачивание.</p>
  }

  const data = exportQuery.data!
  const expired = isExpired(data.expires_at)

  return (
    <div className="screen download-screen">
      <h1>Готово</h1>
      <p>Файл готов к скачиванию.</p>

      {data.expires_at && (
        <p className="status-text">
          Ссылка действует до: {new Date(data.expires_at).toLocaleString('ru-RU')}
        </p>
      )}

      {expired ? (
        <button type="button" onClick={() => setRefreshCount((c) => c + 1)}>
          Получить новую ссылку
        </button>
      ) : (
        <a href={data.url} download className="download-button">
          Скачать
        </a>
      )}

      <div className="download-actions">
        <button type="button" onClick={reset}>
          Загрузить другой файл
        </button>
      </div>
    </div>
  )
}
