import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// The screen/step the app is currently on.
export type AppStep = 'projects' | 'upload' | 'analysis' | 'timeline' | 'export' | 'download'

export interface CutSelection {
  // Raw float seconds from the timeline API - never rounded.
  start: number
  end: number
}

interface AppState {
  step: AppStep
  projectId: string | null
  mediaId: string | null
  analysisJobId: string | null
  exportJobId: string | null
  // Regions the user marked for removal, keyed by "start:end" (raw floats
  // stringified) to allow toggling without duplicates.
  cutsToRemove: Map<string, CutSelection>

  setStep: (step: AppStep) => void
  setProjectId: (projectId: string | null) => void
  setMediaId: (mediaId: string | null) => void
  setAnalysisJobId: (jobId: string | null) => void
  setExportJobId: (jobId: string | null) => void
  toggleCut: (region: CutSelection) => void
  isCutSelected: (region: CutSelection) => boolean
  clearCuts: () => void
  reset: () => void
}

function cutKey(region: CutSelection): string {
  return `${region.start}:${region.end}`
}

// Persisted so a page reload restores the user's place (which project/media
// they were on) instead of dropping back to an empty Upload screen. Only
// identity/navigation fields are persisted — job ids and cut selections are
// tied to one in-flight run and are safe (and correct) to lose on reload;
// re-entering a project re-fetches their current state from the backend.
export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      step: 'projects',
      projectId: null,
      mediaId: null,
      analysisJobId: null,
      exportJobId: null,
      cutsToRemove: new Map(),

      setStep: (step) => set({ step }),
      setProjectId: (projectId) => set({ projectId }),
      setMediaId: (mediaId) => set({ mediaId }),
      setAnalysisJobId: (jobId) => set({ analysisJobId: jobId }),
      setExportJobId: (jobId) => set({ exportJobId: jobId }),

      toggleCut: (region) => {
        const key = cutKey(region)
        const next = new Map(get().cutsToRemove)
        if (next.has(key)) {
          next.delete(key)
        } else {
          next.set(key, region)
        }
        set({ cutsToRemove: next })
      },

      isCutSelected: (region) => get().cutsToRemove.has(cutKey(region)),

      clearCuts: () => set({ cutsToRemove: new Map() }),

      reset: () =>
        set({
          step: 'projects',
          projectId: null,
          mediaId: null,
          analysisJobId: null,
          exportJobId: null,
          cutsToRemove: new Map(),
        }),
    }),
    {
      name: 'takeflow-app-store',
      partialize: (state) => ({
        step: state.step,
        projectId: state.projectId,
        mediaId: state.mediaId,
      }),
    },
  ),
)
