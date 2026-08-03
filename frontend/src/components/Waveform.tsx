import { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin, { type Region } from 'wavesurfer.js/dist/plugins/regions.js'
import type { RegionOut } from '../types/api'

const KEEP_COLOR = 'rgba(76, 175, 80, 0.3)'
const AUTO_CUT_COLOR = 'rgba(158, 158, 158, 0.4)'
const REVIEW_COLOR = 'rgba(255, 193, 7, 0.35)'
const REVIEW_MARKED_COLOR = 'rgba(244, 67, 54, 0.5)'

function regionColor(region: RegionOut, isMarkedForCut: boolean): string {
  if (region.kind === 'keep') return KEEP_COLOR
  if (region.kind === 'auto_cut') return AUTO_CUT_COLOR
  return isMarkedForCut ? REVIEW_MARKED_COLOR : REVIEW_COLOR
}

interface WaveformProps {
  audioUrl: string
  regions: RegionOut[]
  isMarkedForCut: (region: RegionOut) => boolean
  onRegionClick: (region: RegionOut) => void
}

/**
 * Renders the audio waveform with overlaid timeline regions using
 * wavesurfer.js + its regions plugin. Region start/end are the raw float
 * seconds from the backend - never rounded here, only used for display via
 * formatSeconds elsewhere.
 */
export function Waveform({ audioUrl, regions, isMarkedForCut, onRegionClick }: WaveformProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const wavesurferRef = useRef<WaveSurfer | null>(null)
  const regionsPluginRef = useRef<RegionsPlugin | null>(null)
  const [isReady, setIsReady] = useState(false)

  // Init wavesurfer once per audioUrl.
  useEffect(() => {
    if (!containerRef.current) return

    const regionsPlugin = RegionsPlugin.create()
    const wavesurfer = WaveSurfer.create({
      container: containerRef.current,
      waveColor: 'rgba(148, 163, 184, 0.6)',
      progressColor: '#7c5cff',
      cursorColor: '#38bdf8',
      height: 110,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      url: audioUrl,
      plugins: [regionsPlugin],
    })

    wavesurferRef.current = wavesurfer
    regionsPluginRef.current = regionsPlugin

    wavesurfer.on('ready', () => setIsReady(true))

    regionsPlugin.on('region-clicked', (region: Region, e: MouseEvent) => {
      e.stopPropagation()
      wavesurfer.setTime(region.start)
      wavesurfer.play()
      const original = regions[Number(region.id)]
      if (original) onRegionClick(original)
    })

    return () => {
      wavesurfer.destroy()
      wavesurferRef.current = null
      regionsPluginRef.current = null
      setIsReady(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioUrl])

  // (Re)render regions whenever the region list or cut selection changes.
  useEffect(() => {
    const regionsPlugin = regionsPluginRef.current
    if (!regionsPlugin || !isReady) return

    regionsPlugin.clearRegions()
    regions.forEach((region, index) => {
      regionsPlugin.addRegion({
        id: String(index),
        start: region.start,
        end: region.end,
        color: regionColor(region, isMarkedForCut(region)),
        drag: false,
        resize: false,
        content: region.kind === 'review' ? (isMarkedForCut(region) ? 'вырезать' : 'проверить') : undefined,
      })
    })
  }, [regions, isReady, isMarkedForCut])

  return <div ref={containerRef} className="waveform" />
}
