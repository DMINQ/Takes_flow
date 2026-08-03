import { useAppStore, type AppStep } from './store/appStore'
import { ProjectsScreen } from './screens/ProjectsScreen'
import { UploadScreen } from './screens/UploadScreen'
import { AnalysisScreen } from './screens/AnalysisScreen'
import { TimelineScreen } from './screens/TimelineScreen'
import { ExportScreen } from './screens/ExportScreen'
import { DownloadScreen } from './screens/DownloadScreen'
import './App.css'

const STEPS: { key: AppStep; label: string }[] = [
  { key: 'projects', label: 'Проекты' },
  { key: 'upload', label: 'Загрузка' },
  { key: 'analysis', label: 'Анализ' },
  { key: 'timeline', label: 'Таймлайн' },
  { key: 'export', label: 'Экспорт' },
  { key: 'download', label: 'Готово' },
]

function StepIndicator({ current }: { current: AppStep }) {
  const currentIndex = STEPS.findIndex((s) => s.key === current)
  return (
    <nav className="step-indicator" aria-label="Прогресс">
      {STEPS.map((s, idx) => {
        const state = idx < currentIndex ? 'done' : idx === currentIndex ? 'active' : 'pending'
        return (
          <div key={s.key} className={`step step--${state}`}>
            <span className="step__dot">{idx < currentIndex ? '✓' : idx + 1}</span>
            <span className="step__label">{s.label}</span>
            {idx < STEPS.length - 1 && <span className="step__connector" />}
          </div>
        )
      })}
    </nav>
  )
}

function App() {
  const step = useAppStore((s) => s.step)

  return (
    <div className="app-shell">
      <div className="app-glow" aria-hidden="true" />
      <header className="app-header">
        <div className="app-brand">
          <span className="app-logo">TF</span>
          <h1 className="app-title">TakeFlow</h1>
        </div>
        <StepIndicator current={step} />
      </header>
      <main className="app-main">
        <div className="app-card">
          {step === 'projects' && <ProjectsScreen />}
          {step === 'upload' && <UploadScreen />}
          {step === 'analysis' && <AnalysisScreen />}
          {step === 'timeline' && <TimelineScreen />}
          {step === 'export' && <ExportScreen />}
          {step === 'download' && <DownloadScreen />}
        </div>
      </main>
    </div>
  )
}

export default App
