import type { Branch, ChatResponse, Customer, ReportRequest, ReportResult, Sku } from '../types'
import { mockChat, mockCustomers, mockReport, mockSkus } from './mock'

const useMocks = import.meta.env.VITE_USE_MOCKS === 'true'
const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')

class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${baseUrl}${path}`, { headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) }, ...init })
  } catch {
    throw new ApiError('Unable to connect to the Sales Intelligence service.')
  }
  if (!response.ok) {
    const error = await response.json().catch(() => null) as { detail?: string; message?: string } | null
    throw new ApiError(error?.detail ?? error?.message ?? 'The service could not complete that request.', response.status)
  }
  return response.json() as Promise<T>
}

export const api = {
  getSkus: async (branch?: Branch): Promise<Sku[]> => useMocks ? mockSkus(branch) : request(`/meta/skus${branch ? `?branch=${branch}` : ''}`),
  getCustomers: async (routeIds: number[]): Promise<Customer[]> => useMocks ? mockCustomers(routeIds) : request(`/meta/customers?route_ids=${routeIds.join(',')}`),
  chat: async (message: string, conversationId: string | null): Promise<ChatResponse> => useMocks ? mockChat(message, conversationId) : request('/chat', { method: 'POST', body: JSON.stringify({ message, conversation_id: conversationId }) }),
  report: async (payload: ReportRequest): Promise<ReportResult> => {
    if (useMocks) return mockReport(payload)
    let response: Response
    try {
      response = await fetch(`${baseUrl}/reports`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
    } catch {
      throw new ApiError('Unable to connect to the Sales Intelligence service.')
    }
    if (!response.ok) {
      const error = await response.json().catch(() => null) as { detail?: string; message?: string } | null
      throw new ApiError(error?.detail ?? error?.message ?? 'Report generation failed.', response.status)
    }
    const disposition = response.headers.get('content-disposition') ?? ''
    const ext = payload.output_format === 'pdf' ? 'pdf' : 'xlsx'
    const fallbackFilename = `sales-report-${payload.date_from.replaceAll('/', '-')}.${ext}`
    // RFC 5987: prefer filename*=UTF-8''<percent-encoded> over filename=
    const rfc5987Match = disposition.match(/filename\*=UTF-8''([^;\s]+)/i)
    const plainMatch = disposition.match(/filename="([^"]+)"|filename=([^;\s]+)/i)
    const rawFilename = rfc5987Match
      ? decodeURIComponent(rfc5987Match[1])
      : (plainMatch?.[1] ?? plainMatch?.[2] ?? '').trim()
    const filename = rawFilename || fallbackFilename
    const isJson = response.headers.get('content-type')?.includes('application/json')
    if (isJson) {
      const data = await response.json() as { status?: string; message?: string }
      if (data.status === 'no_data') return { kind: 'no_data', message: data.message ?? 'No data found for these filters.' }
    }
    const contentType = payload.output_format === 'pdf' 
      ? 'application/pdf' 
      : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    const rawBlob = await response.blob()
    const blob = new Blob([rawBlob], { type: contentType })
    return { kind: 'download', blob, filename }
  },
}

export { ApiError }
