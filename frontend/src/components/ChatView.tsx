import { FormEvent, KeyboardEvent, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import { InlineChart } from './InlineChart'
import type { ChartPayload, DataTable, ReportPrefill } from '../types'

type Message = {
  id: string
  role: 'assistant' | 'user'
  text: string
  table?: DataTable | null
  chart?: ChartPayload | null
  prefill?: ReportPrefill | null
  errorKind?: 'connection' | 'query'
}

const initialMessage: Message = {
  id: 'welcome',
  role: 'assistant',
  text: 'Ask a focused sales question - for example, “Which route had the highest coffee volume last week?”',
}

export function ChatView({ onGenerateReport }: { onGenerateReport: (prefill: ReportPrefill) => void }) {
  const [messages, setMessages] = useState<Message[]>([initialMessage])
  const [draft, setDraft] = useState('')
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [isSending, setIsSending] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  async function submit(event?: FormEvent) {
    event?.preventDefault()
    const message = draft.trim()
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

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void submit()
    }
  }

  function clearConversation() {
    setMessages([initialMessage])
    setConversationId(null)
    setDraft('')
    inputRef.current?.focus()
  }

  return (
    <section className="workspace chat-workspace" aria-label="Sales data chat">
      <header className="workspace-heading">
        <div>
          <p className="eyebrow">Conversational analysis</p>
          <h1>Ask your sales data</h1>
          <p className="workspace-subtitle">Get direct answers, supporting tables, and report-ready insights.</p>
        </div>
        <button className="secondary-button" type="button" onClick={clearConversation}>
          <span aria-hidden="true">↺</span> New chat
        </button>
      </header>

      <div className="chat-shell">
        <div className="chat-context"><span className="status-dot" />Data analysis assistant <span>15-day evaluation dataset</span></div>
        <div className="messages" aria-live="polite">
          {messages.map((message) => (
            <article className={`message-row ${message.role}`} key={message.id}>
              {message.role === 'assistant' && <div className="avatar assistant-avatar" aria-hidden="true">SI</div>}
              <div className={`message-bubble ${message.errorKind ? `message-${message.errorKind}` : ''}`}>
                {message.errorKind === 'connection' && <p className="bubble-kicker">Connection issue</p>}
                {message.errorKind === 'query' && <p className="bubble-kicker">Couldn’t complete analysis</p>}
                <p>{message.text}</p>
                {message.table && (
                  <div className="table-wrap">
                    <table>
                      <thead><tr>{message.table.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
                      <tbody>{message.table.rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody>
                    </table>
                  </div>
                )}
                {message.chart && <InlineChart chart={message.chart} />}
                {message.prefill && (
                  <button type="button" className="report-handoff" onClick={() => onGenerateReport(message.prefill!)}>
                    Generate this as a report <span aria-hidden="true">→</span>
                  </button>
                )}
              </div>
              {message.role === 'user' && <div className="avatar user-avatar" aria-hidden="true">You</div>}
            </article>
          ))}
          {isSending && (
            <article className="message-row assistant" aria-label="Assistant is processing your request">
              <div className="avatar assistant-avatar" aria-hidden="true">SI</div>
              <div className="message-bubble typing"><span /><span /><span /></div>
            </article>
          )}
        </div>
        <form className="chat-composer" onSubmit={submit}>
          <label className="sr-only" htmlFor="chat-message">Ask a sales question</label>
          <textarea
            id="chat-message"
            ref={inputRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about routes, products, customers, or sales trends..."
            rows={1}
            disabled={isSending}
          />
          <button className="send-button" type="submit" disabled={!draft.trim() || isSending} aria-label="Send message">↑</button>
        </form>
        <p className="composer-hint">Enter to send <span>•</span> Shift + Enter for a new line</p>
      </div>
    </section>
  )
}
