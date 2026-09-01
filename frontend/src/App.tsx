import { useState } from 'react'
import { ChatView } from './components/ChatView'
import { ReportView } from './components/ReportView'
import type { ReportPrefill } from './types'

type View = 'chat' | 'report'

export default function App() {
  const [activeView, setActiveView] = useState<View>('chat')
  const [prefill, setPrefill] = useState<ReportPrefill | null>(null)

  function openReport(prefillFromChat: ReportPrefill) {
    setPrefill(prefillFromChat)
    setActiveView('report')
  }

  return (
    <main className="app-shell">
      <aside className="app-sidebar">
        <div className="brand"><div className="brand-mark">S</div><div><span>SALES</span><strong>Intelligence</strong></div></div>
        <nav aria-label="Primary navigation">
          <button className={`nav-item ${activeView === 'chat' ? 'active' : ''}`} onClick={() => setActiveView('chat')} type="button"><span className="nav-icon">◌</span>Ask data</button>
          <button className={`nav-item ${activeView === 'report' ? 'active' : ''}`} onClick={() => setActiveView('report')} type="button"><span className="nav-icon">▤</span>Generate report</button>
        </nav>
        <div className="sidebar-bottom"><div className="secure-note"><span>⌁</span><p>Private sales workspace<br /><small>Internal access</small></p></div><p className="phase-label">Evaluation build<br />v0.1</p></div>
      </aside>
      <div className="main-area">
        <div className="topline"><span>SALES ANALYTICS PLATFORM</span><span>Internal workspace</span></div>
        <div className={activeView === 'chat' ? 'view active' : 'view'}><ChatView onGenerateReport={openReport} /></div>
        <div className={activeView === 'report' ? 'view active' : 'view'}><ReportView prefill={prefill} onPrefillConsumed={() => setPrefill(null)} /></div>
      </div>
    </main>
  )
}
