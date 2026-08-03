import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getSourceUrl, getTimeline } from '../api/client'
import type { RegionOut } from '../types/api'
import { useAppStore } from '../store/appStore'
import { Waveform } from '../components/Waveform'
import { formatSeconds } from '../utils/format'

/** Groups REVIEW regions by take_group so duplicates are reviewed together. */
function groupReviewRegions(regions: RegionOut[]): Map<string, RegionOut[]> {
  const groups = new Map<string, RegionOut[]>()
  for (const region of regions) {
    if (region.kind !== 'review') continue
    const key = region.take_group ?? 'ungrouped'
    const list = groups.get(key) ?? []
    list.push(region)
    groups.set(key, list)
  }
  return groups
}

export function TimelineScreen() {
  const mediaId = useAppStore((s) => s.mediaId)
  const setStep = useAppStore((s) => s.setStep)
  const toggleCut = useAppStore((s) => s.toggleCut)
  const isCutSelected = useAppStore((s) => s.isCutSelected)
  const [selectedRegion, setSelectedRegion] = useState<RegionOut | null>(null)

  const sourceQuery = useQuery({
    queryKey: ['source-url', mediaId],
    queryFn: () => getSourceUrl(mediaId!),
    enabled: !!mediaId,
  })

  const timelineQuery = useQuery({
    queryKey: ['timeline', mediaId],
    queryFn: () => getTimeline(mediaId!),
    enabled: !!mediaId,
  })

  const timelineData = timelineQuery.data
  const regions = useMemo(() => timelineData?.regions ?? [], [timelineData])
  const reviewGroups = useMemo(() => groupReviewRegions(regions), [regions])

  if (!mediaId) {
    return <p>Сначала загрузите и проанализируйте файл.</p>
  }

  if (timelineQuery.isLoading || sourceQuery.isLoading) {
    return <p>Загружаем таймлайн...</p>
  }

  if (timelineQuery.isError || sourceQuery.isError) {
    return <p className="error-text">Не удалось загрузить таймлайн. Попробуйте обновить страницу.</p>
  }

  if (regions.length === 0) {
    return <p>Анализ ещё не завершён. Подождите или перезапустите анализ.</p>
  }

  return (
    <div className="screen timeline-screen">
      <h1>Таймлайн</h1>

      {sourceQuery.data && (
        <Waveform
          audioUrl={sourceQuery.data.url}
          regions={regions}
          isMarkedForCut={(region) => isCutSelected({ start: region.start, end: region.end })}
          onRegionClick={setSelectedRegion}
        />
      )}

      {selectedRegion && (
        <div className="region-detail">
          <p>
            <strong>{selectedRegion.speaker ?? 'Неизвестный спикер'}</strong>{' '}
            ({formatSeconds(selectedRegion.start)}–{formatSeconds(selectedRegion.end)})
          </p>
          {selectedRegion.text && <p>{selectedRegion.text}</p>}
        </div>
      )}

      <h2>Дубли на проверку</h2>
      {reviewGroups.size === 0 && <p>Нет дублей, требующих проверки.</p>}
      {Array.from(reviewGroups.entries()).map(([groupKey, groupRegions]) => (
        <div key={groupKey} className="take-group">
          <h3>Группа дублей: {groupKey}</h3>
          <ul>
            {groupRegions.map((region, idx) => {
              const marked = isCutSelected({ start: region.start, end: region.end })
              return (
                <li key={idx} className={marked ? 'take-item take-item--cut' : 'take-item'}>
                  <span>
                    {formatSeconds(region.start)}–{formatSeconds(region.end)}
                    {region.speaker ? ` · ${region.speaker}` : ''}
                  </span>
                  {region.text && <span className="take-item__text">{region.text}</span>}
                  <button
                    type="button"
                    onClick={() => toggleCut({ start: region.start, end: region.end })}
                  >
                    {marked ? 'Оставить (отменить вырезание)' : 'Вырезать'}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      ))}

      <div className="timeline-actions">
        <button type="button" onClick={() => setStep('export')}>
          Перейти к экспорту
        </button>
      </div>
    </div>
  )
}
