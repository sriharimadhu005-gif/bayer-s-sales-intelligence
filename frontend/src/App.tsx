import { useState } from 'react'
import { MessageSquare, FileSpreadsheet, ShieldCheck } from 'lucide-react'
import { ChatView } from './components/ChatView'
import { ReportView } from './components/ReportView'
import type { ReportPrefill } from './types'
import bayarsLogo from './assets/bayars-logo.png'

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
        <div className="sidebar-branding">
          <div className="brand-logo-wrapper">
            <img
              src={bayarsLogo}
              alt="Bayar's Coffee — The Warmth of Goodness!"
              className="brand-logo-img"
              width="160"
              height="79"
            />
          </div>
          <p className="brand-subtitle">Sales Intelligence Portal</p>
        </div>

        <nav aria-label="Primary navigation">
          <button
            className={`nav-item ${activeView === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveView('chat')}
            type="button"
          >
            <span className="nav-icon">
              <MessageSquare size={18} />
            </span>
            <span>Ask data</span>
          </button>
          <button
            className={`nav-item ${activeView === 'report' ? 'active' : ''}`}
            onClick={() => setActiveView('report')}
            type="button"
          >
            <span className="nav-icon">
              <FileSpreadsheet size={18} />
            </span>
            <span>Generate report</span>
          </button>
        </nav>

        <div className="sidebar-footer">
          <div className="workspace-badge-card">
            <div className="workspace-badge-icon">
              <ShieldCheck size={16} />
            </div>
            <div className="workspace-badge-info">
              <span className="workspace-badge-title">Private Workspace</span>
              <span className="workspace-badge-subtitle">Enterprise Access</span>
            </div>
          </div>
        </div>
      </aside>

      <div className="main-area">
        <header className="topline">
          <div className="topline-brand">
            <span>Bayar's Coffee</span>
            <span className="topline-slash">/</span>
            <span className="topline-section">Analytics & Intelligence</span>
          </div>
          <div className="topline-status">
            <span className="status-dot-active" aria-hidden="true" />
            <span>Operational</span>
          </div>
        </header>

        <div className={activeView === 'chat' ? 'view active' : 'view'}>
          <ChatView onGenerateReport={openReport} />
        </div>
        <div className={activeView === 'report' ? 'view active' : 'view'}>
          <ReportView prefill={prefill} onPrefillConsumed={() => setPrefill(null)} />
        </div>
      </div>
    </main>
  )
}
