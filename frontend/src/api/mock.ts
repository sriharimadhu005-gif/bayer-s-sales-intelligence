import type { Branch, ChatResponse, Customer, ReportRequest, ReportResult, Sku } from '../types'

const wait = (ms = 550) => new Promise((resolve) => window.setTimeout(resolve, ms))

const allSkus: Sku[] = [
  { sku_id: 11, sku_name: 'Filter Coffee 250g', branch: 'coffee' },
  { sku_id: 12, sku_name: 'Classic Coffee 100g', branch: 'coffee' },
  { sku_id: 21, sku_name: 'Masala Chai 250g', branch: 'tea' },
  { sku_id: 22, sku_name: 'Green Tea 25 Bags', branch: 'tea' },
  { sku_id: 31, sku_name: 'Cocoa Mix 200g', branch: 'others' },
]

const customers: Record<number, Customer[]> = {
  1: [{ customer_id: 'A132', canonical_name: 'Aarav Traders' }, { customer_id: 'A125', canonical_name: 'City Mart' }],
  2: [{ customer_id: 'B428', canonical_name: 'Evergreen Stores' }, { customer_id: 'B202', canonical_name: 'Lakshmi Wholesale' }],
  3: [{ customer_id: 'C301', canonical_name: 'Sunrise Traders' }, { customer_id: 'C302', canonical_name: 'Metro Cash & Carry' }],
  4: [{ customer_id: 'D401', canonical_name: 'Pioneer Agencies' }],
  5: [{ customer_id: 'E501', canonical_name: 'Golden Mart' }],
  6: [{ customer_id: 'F601', canonical_name: 'Coastal Distributors' }],
  7: [{ customer_id: 'G701', canonical_name: 'North Star Retail' }],
}

export async function mockSkus(branch?: Branch): Promise<Sku[]> {
  await wait(240)
  return branch ? allSkus.filter((sku) => sku.branch === branch) : allSkus
}

export async function mockCustomers(routeIds: number[]): Promise<Customer[]> {
  await wait(280)
  return [...new Map(routeIds.flatMap((id) => customers[id] ?? []).map((customer) => [customer.customer_id, customer])).values()]
}

export async function mockChat(message: string, conversationId: string | null): Promise<ChatResponse> {
  await wait(780)
  if (/unreachable|connection error/i.test(message)) throw new TypeError('Failed to fetch')
  if (/nothing|unknown|no data/i.test(message)) {
    return { conversation_id: conversationId ?? crypto.randomUUID(), answer_text: "I couldn't find data for that. Try narrowing the date range or checking the product name.", table: null, chart: null, report_eligible: false, report_prefill: null, clarification: null }
  }
  if (/\b(bs|shanthi|clarify|options)\b/i.test(message)) {
    return {
      conversation_id: conversationId ?? crypto.randomUUID(),
      answer_text: "I found multiple variants for 'BS'. Which one did you mean?",
      table: null,
      chart: null,
      report_eligible: false,
      report_prefill: null,
      excel_download_url: null,
      excel_filename: null,
      clarification: {
        question: "Which variant of 'BS' did you mean?",
        entity_type: 'sku',
        prompt_hint: 'Select a pack size or variant:',
        options: [
          { id: 1, label: 'Coffee-Cafe Supreme-200', value: '1', badge: 'Rs.730.00/kg', detail: 'Std Rate: Rs.730.00/kg' },
          { id: 2, label: 'Coffee-Cafe Supreme-500', value: '2', badge: 'Rs.725.00/kg', detail: 'Std Rate: Rs.725.00/kg' },
          { id: 3, label: 'Coffee-Cafe Supreme-1000', value: '3', badge: 'Rs.720.00/kg', detail: 'Std Rate: Rs.720.00/kg' },
        ],
      },
    }
  }
  if (/generate report|export to excel|download report|create excel|convert this into excel|give this as xlsx|excel|xlsx/i.test(message)) {
    return {
      conversation_id: conversationId ?? crypto.randomUUID(),
      answer_text: 'Report generated successfully.',
      table: null,
      chart: null,
      report_eligible: true,
      report_prefill: null,
      excel_download_url: '/api/chat/mock/download-report/mock-report-id',
      excel_filename: 'Sales_Report_Demo.xlsx',
    }
  }
  const asksForChart = /chart|graph|compare|trend/i.test(message)
  return {
    conversation_id: conversationId ?? crypto.randomUUID(),
    answer_text: 'Route 3 led coffee volume last week with 1,240 units, ahead of Route 1 by 18%.',
    table: { columns: ['Route', 'Coffee volume', 'Share'], rows: [['Route 3', '1,240', '31%'], ['Route 1', '1,051', '26%'], ['Route 5', '842', '21%']] },
    chart: asksForChart ? { type: 'bar', data: { labels: ['Route 3', 'Route 1', 'Route 5'], values: [1240, 1051, 842] } } : null,
    report_eligible: true,
    report_prefill: { date_from: '10/08/2026', date_to: '16/08/2026', route_ids: [3], branches: ['coffee'], sku_ids: null, customer_ids: null },
    excel_download_url: null,
    excel_filename: null,
  }
}

export async function mockReport(request: ReportRequest): Promise<ReportResult> {
  await wait(1000)
  if (request.route_ids?.includes(7) && request.customer_ids?.includes('G701')) return { kind: 'no_data', message: 'No data found for these filters.' }
  const body = `Sales Intelligence Report\n${request.date_from} - ${request.date_to}\nFormat: ${request.output_format.toUpperCase()}\n\nDemo output - connect the FastAPI Report Engine for production reports.`
  const blob = new Blob([body], { type: request.output_format === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  return { kind: 'download', blob, filename: `sales-report-${request.date_from.replaceAll('/', '-')}.${request.output_format === 'pdf' ? 'pdf' : 'xlsx'}` }
}
