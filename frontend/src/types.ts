export type Branch = 'coffee' | 'tea' | 'others'
export type ChartType = 'bar' | 'line' | 'pie'

export interface Route {
  route_id: number
  route_name: string
}

export interface Sku {
  sku_id: number
  sku_name: string
  branch: Branch
}

export interface Customer {
  customer_id: string
  canonical_name: string
}

export interface DataTable {
  columns: string[]
  rows: Array<Array<string | number>>
}

export interface ChartPayload {
  type: ChartType
  data: {
    labels?: string[]
    values?: number[]
    image_url?: string
  }
}

export interface ReportPrefill {
  date_from?: string
  date_to?: string
  days?: string[] | null
  route_ids?: number[] | null
  branches?: Branch[] | null
  sku_ids?: number[] | null
  customer_ids?: string[] | null
}

export interface ChatResponse {
  conversation_id: string
  answer_text: string
  table: DataTable | null
  chart: ChartPayload | null
  report_eligible: boolean
  report_prefill: ReportPrefill | null
}

export interface ReportRequest {
  date_from: string
  date_to: string
  days?: string[]
  route_ids?: number[]
  branches?: Branch[]
  sku_ids?: number[]
  customer_ids?: string[]
  generate_chart: boolean
  chart_type?: ChartType
  output_format: 'excel' | 'pdf'
  notes?: string
}

export type ReportResult =
  | { kind: 'download'; blob: Blob; filename: string }
  | { kind: 'no_data'; message: string }
