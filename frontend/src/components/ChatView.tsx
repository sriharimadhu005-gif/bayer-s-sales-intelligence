import { FormEvent, KeyboardEvent, useRef, useState } from 'react'
import {
  RotateCcw,
  ArrowUp,
  ArrowRight,
  FileSpreadsheet,
  Download,
  Sparkles,
  User,
  AlertCircle,
  WifiOff,
  HelpCircle,
  ChevronRight,
} from 'lucide-react'
import { api, ApiError } from '../api/client'
import { InlineChart } from './InlineChart'
import type { ChartPayload, ClarificationOption, ClarificationPayload, DataTable, ReportPrefill } from '../types'

type Message = {
  id: string
  role: 'assistant' | 'user'
  text: string
  table?: DataTable | null
  chart?: ChartPayload | null
  prefill?: ReportPrefill | null
  excelDownloadUrl?: string | null
  excelFilename?: string | null
  reportDisplayName?: string | null
  reportPeriodLabel?: string | null
  clarification?: ClarificationPayload | null
  errorKind?: 'connection' | 'query'
}

const initialMessage: Message = {
  id: 'welcome',
  role: 'assistant',
  text: 'Ask a focused sales question, or generate a standard report directly — for example:\n\n• "Which route had the highest coffee volume?"\n• "Generate the Sales Performance Report for 1 April to 15 April"\n• "Give me the BDE report for last month"',
}

export function ChatView({ onGenerateReport }: { onGenerateReport: (prefill: ReportPrefill) => void }) {
  const [messages, setMessages] = useState<Message[]>([initialMessage])
  const [draft, setDraft] = useState('')
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [isSending, setIsSending] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  async function sendMessage(textToSend: string) {
    const message = textToSend.trim()
    if (!message || isSending) return
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: 'user', text: message }])
    setDraft('')
    setIsSending(true)
    try {
      const response = await api.chat(message, conversationId)
      setConversationId(response.conversation_id)
      setMessages((current) => [...current, {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: response.answer_text,
        table: response.table,
        chart: response.chart,
        prefill: response.report_eligible ? response.report_prefill : null,
        excelDownloadUrl: response.excel_download_url,
        excelFilename: response.excel_filename,
        reportDisplayName: response.report_display_name,
        reportPeriodLabel: response.report_period_label,
        clarification: response.clarification,
      }])
    } catch (error) {
      const isConnectionError = error instanceof ApiError || error instanceof TypeError
      setMessages((current) => [...current, {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: isConnectionError
          ? 'I can’t reach the Sales Intelligence service right now. Check the connection and try again.'
          : 'I couldn’t answer that question. Try narrowing the date range or phrasing it differently.',
        errorKind: isConnectionError ? 'connection' : 'query',
      }])
    } finally {
      setIsSending(false)
      window.setTimeout(() => inputRef.current?.focus(), 0)
    }
  }

  function submit(event?: FormEvent) {
    event?.preventDefault()
    void sendMessage(draft)
  }

  function handleSelectOption(option: ClarificationOption) {
    void sendMessage(`${option.id}. ${option.label}`)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void submit()
    }
  }

  function clearConversation() {
    if (conversationId) {
      void api.clearConversation(conversationId)
    }
    setMessages([initialMessage])
    setConversationId(null)
    setDraft('')
    inputRef.current?.focus()
  }

  const lastMessage = messages[messages.length - 1]
  const activeClarification = lastMessage?.role === 'assistant' ? lastMessage.clarification : null

  return (
    <section className="workspace chat-workspace" aria-label="Sales data chat">
      <header className="workspace-heading">
        <div>
          <p className="eyebrow">Conversational analysis</p>
          <h1>Ask your sales data</h1>
          <p className="workspace-subtitle">Get direct answers, supporting tables, and report-ready insights.</p>
        </div>
        <button className="secondary-button" type="button" onClick={clearConversation}>
          <RotateCcw size={16} />
          <span>New chat</span>
        </button>
      </header>

      <div className="chat-shell">
        <div className="chat-context">
          <span className="status-dot-active" aria-hidden="true" />
          <span>Sales Data Assistant</span>
        </div>

        <div className="messages" aria-live="polite">
          {messages.map((message) => (
            <article className={`message-row ${message.role}`} key={message.id}>
              {message.role === 'assistant' && (
                <div className="avatar assistant-avatar" aria-hidden="true">
                  <Sparkles size={16} />
                </div>
              )}
              <div className={`message-bubble ${message.errorKind ? `message-${message.errorKind}` : ''}`}>
                {message.errorKind === 'connection' && (
                  <p className="bubble-kicker" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <WifiOff size={14} />
                    <span>Connection issue</span>
                  </p>
                )}
                {message.errorKind === 'query' && (
                  <p className="bubble-kicker" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <AlertCircle size={14} />
                    <span>Couldn’t complete analysis</span>
                  </p>
                )}
                <p>{message.text}</p>
                {message.table && (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          {message.table.columns.map((column) => (
                            <th key={column}>{column}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {message.table.rows.map((row, index) => (
                          <tr key={index}>
                            {row.map((cell, cellIndex) => (
                              <td key={cellIndex}>{cell}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {message.chart && <InlineChart chart={message.chart} />}
                {message.excelDownloadUrl && (
                  <div className="excel-download-card">
                    <div className="excel-download-status">
                      <div className="excel-download-icon">
                        <FileSpreadsheet size={22} />
                      </div>
                      <div className="excel-status-text">
                        <strong>
                          {message.reportDisplayName ? `${message.reportDisplayName} Generated` : 'Report Generated Successfully'}
                        </strong>
                        {message.reportPeriodLabel && (
                          <span className="excel-period-text">{message.reportPeriodLabel}</span>
                        )}
                        <span className="excel-filename-text">
                          {message.excelFilename || 'Sales_Report.xlsx'}
                        </span>
                      </div>
                    </div>
                    <a
                      href={message.excelDownloadUrl}
                      download={message.excelFilename || 'Sales_Report.xlsx'}
                      className="excel-download-action-btn"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <Download size={16} />
                      <span>Download Excel</span>
                    </a>
                  </div>
                )}
                {message.clarification && (
                  <div className="bubble-clarification-card">
                    <div className="bubble-clarification-title">
                      <HelpCircle size={15} />
                      <span>{message.clarification.prompt_hint || 'Select an option to continue:'}</span>
                    </div>
                    <div className="bubble-clarification-options">
                      {message.clarification.options.map((opt) => (
                        <button
                          key={opt.id}
                          type="button"
                          className="bubble-option-btn"
                          onClick={() => handleSelectOption(opt)}
                          disabled={isSending}
                        >
                          <span className="bubble-option-num">{opt.id}</span>
                          <div className="bubble-option-body">
                            <span className="bubble-option-label">{opt.label}</span>
                            {opt.detail && opt.detail !== opt.badge && (
                              <span className="bubble-option-detail">{opt.detail}</span>
                            )}
                          </div>
                          {opt.badge && <span className="bubble-option-badge">{opt.badge}</span>}
                          <ChevronRight size={14} className="bubble-option-arrow" />
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {message.prefill && !message.excelDownloadUrl && (
                  <button
                    type="button"
                    className="report-handoff"
                    onClick={() => onGenerateReport(message.prefill!)}
                  >
                    <span>Generate this as a report</span>
                    <ArrowRight size={15} />
                  </button>
                )}
              </div>
              {message.role === 'user' && (
                <div className="avatar user-avatar" aria-hidden="true">
                  <User size={16} />
                </div>
              )}
            </article>
          ))}
          {isSending && (
            <article className="message-row assistant" aria-label="Assistant is processing your request">
              <div className="avatar assistant-avatar" aria-hidden="true">
                <Sparkles size={16} />
              </div>
              <div className="message-bubble typing">
                <span />
                <span />
                <span />
              </div>
            </article>
          )}
        </div>

        {activeClarification && !isSending && (
          <div className="situational-question-bar" role="region" aria-label="Available options">
            <div className="question-bar-header">
              <span className="question-bar-tag">
                <HelpCircle size={13} className="question-icon" />
                <span>Clarification Needed</span>
              </span>
              <span className="question-bar-prompt">{activeClarification.question}</span>
            </div>
            <div className="question-bar-chips">
              {activeClarification.options.map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  className="question-chip"
                  onClick={() => handleSelectOption(opt)}
                  title={opt.detail || opt.label}
                >
                  <span className="chip-badge-num">{opt.id}</span>
                  <span className="chip-label-text">{opt.label}</span>
                  {opt.badge && <span className="chip-rate-badge">{opt.badge}</span>}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="chat-composer-wrap">
          <form className="chat-composer" onSubmit={submit}>
            <label className="sr-only" htmlFor="chat-message">
              Ask a sales question
            </label>
            <textarea
              id="chat-message"
              ref={inputRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything about customers, routes, products or sales..."
              rows={1}
              disabled={isSending}
            />
            <button
              className="send-button"
              type="submit"
              disabled={!draft.trim() || isSending}
              aria-label="Send message"
            >
              <ArrowUp size={20} />
            </button>
          </form>
          <p className="composer-hint">
            Enter to send <span>•</span> Shift + Enter for a new line
          </p>
        </div>
      </div>
    </section>
  )
}
