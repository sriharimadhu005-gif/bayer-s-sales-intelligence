import { FormEvent, useEffect, useState } from 'react'
import {
  Calendar,
  Check,
  CheckCircle,
  FileSpreadsheet,
  FileText,
  Search,
  ArrowRight,
  Info,
  AlertCircle
} from 'lucide-react'
import { api } from '../api/client'
import type { Branch, Customer, ReportPrefill, ReportRequest, Sku } from '../types'

const fixedRoutes = Array.from({ length: 7 }, (_, index) => ({
  route_id: index + 1,
  route_name: `Route ${index + 1}`
}))
const allBranches: Branch[] = ['coffee', 'tea', 'others']

type Notice = { type: 'success' | 'empty' | 'error'; message: string } | null

function toInputDate(value?: string) {
  if (!value) return ''
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value
  const [day, month, year] = value.split('/')
  return day && month && year ? `${year}-${month}-${day.padStart(2, '0')}` : ''
}

function toIndianDate(value: string) {
  const [year, month, day] = value.split('-')
  return `${day}/${month}/${year}`
}

function toggleValue<T>(current: T[], value: T, complete: T[]) {
  const next = current.includes(value) ? current.filter((item) => item !== value) : [...current, value]
  return next.length ? next : complete
}

function ChipGroup<T extends string>({
  label,
  options,
  selected,
  onChange,
  disabled = false
}: {
  label: string
  options: T[]
  selected: T[]
  onChange: (value: T[]) => void
  disabled?: boolean
}) {
  return (
    <div className="chip-group" aria-label={label}>
      {options.map((option) => {
        const isSelected = selected.includes(option)
        return (
          <button
            key={option}
            type="button"
            className={`choice-chip ${isSelected ? 'selected' : ''}`}
            onClick={() => onChange(toggleValue(selected, option, options))}
            disabled={disabled}
          >
            {isSelected && <Check size={14} />}
            <span>
              {option === 'coffee' || option === 'tea' || option === 'others'
                ? option[0].toUpperCase() + option.slice(1)
                : option}
            </span>
          </button>
        )
      })}
    </div>
  )
}

function SearchableChecklist<T extends object, IdType extends string | number = number>({
  options,
  selectedIds,
  onChange,
  getId,
  getLabel,
  placeholder,
  isLoading,
  disabled
}: {
  options: T[]
  selectedIds: IdType[]
  onChange: (ids: IdType[]) => void
  getId: (option: T) => IdType
  getLabel: (option: T) => string
  placeholder: string
  isLoading?: boolean
  disabled?: boolean
}) {
  const [query, setQuery] = useState('')
  const visible = options.filter((option) => getLabel(option).toLowerCase().includes(query.toLowerCase()))
  const allSelected = options.length > 0 && options.every((option) => selectedIds.includes(getId(option)))

  return (
    <div className="selection-panel">
      <div className="selection-toolbar">
        <div className="search-input-wrapper">
          <Search className="search-icon" size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={placeholder}
            disabled={disabled || isLoading}
            aria-label={placeholder}
          />
        </div>
        <button
          type="button"
          className="text-button"
          onClick={() => onChange(allSelected ? [] : options.map(getId))}
          disabled={disabled || isLoading || !options.length}
        >
          {allSelected ? 'Clear all' : 'Select all'}
        </button>
      </div>
      <div className="checklist">
        {isLoading && <span className="select-state">Loading options...</span>}
        {!isLoading && !visible.length && <span className="select-state">No matching options found.</span>}
        {!isLoading &&
          visible.map((option) => {
            const id = getId(option)
            const isChecked = selectedIds.includes(id)
            return (
              <label className="check-option" key={String(id)}>
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() =>
                    onChange(isChecked ? selectedIds.filter((selected) => selected !== id) : [...selectedIds, id])
                  }
                  disabled={disabled}
                />
                <span>{getLabel(option)}</span>
              </label>
            )
          })}
      </div>
    </div>
  )
}

export function ReportView({
  prefill,
  onPrefillConsumed
}: {
  prefill: ReportPrefill | null
  onPrefillConsumed: () => void
}) {
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [routeIds, setRouteIds] = useState(fixedRoutes.map((route) => route.route_id))
  const [branches, setBranches] = useState<Branch[]>(allBranches)
  const [skuIds, setSkuIds] = useState<number[]>([])
  const [customerIds, setCustomerIds] = useState<string[]>([])
  const [skus, setSkus] = useState<Sku[]>([])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [loadingSkus, setLoadingSkus] = useState(false)
  const [loadingCustomers, setLoadingCustomers] = useState(false)
  const [generateChart, setGenerateChart] = useState(false)
  const [outputFormat, setOutputFormat] = useState<'excel' | 'pdf' | ''>('')
  const [notes, setNotes] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [hasAttempted, setHasAttempted] = useState(false)
  const [notice, setNotice] = useState<Notice>(null)

  const selectedRouteIds = routeIds.length ? routeIds : fixedRoutes.map((route) => route.route_id)
  const selectedBranches = branches.length ? branches : allBranches
  const dateError = dateFrom && dateTo && dateTo < dateFrom ? 'The end date must be on or after the start date.' : ''
  const isValid = Boolean(dateFrom && dateTo && outputFormat && !dateError)
  const routesSummary =
    routeIds.length === fixedRoutes.length ? 'All 7 routes' : `${routeIds.length} route${routeIds.length === 1 ? '' : 's'} selected`
  const skuSummary = skuIds.length ? `${skuIds.length} SKU${skuIds.length === 1 ? '' : 's'} selected` : 'All matching SKUs'
  const customerSummary =
    customerIds.length ? `${customerIds.length} customer${customerIds.length === 1 ? '' : 's'} selected` : 'All customers in selected routes'

  useEffect(() => {
    let cancelled = false
    async function loadSkus() {
      setLoadingSkus(true)
      try {
        const result =
          selectedBranches.length === allBranches.length
            ? await api.getSkus()
            : (await Promise.all(selectedBranches.map((branch) => api.getSkus(branch)))).flat()
        if (!cancelled) {
          setSkus(result)
          setSkuIds((current) => current.filter((id) => result.some((sku) => sku.sku_id === id)))
        }
      } catch {
        if (!cancelled) setSkus([])
      } finally {
        if (!cancelled) setLoadingSkus(false)
      }
    }
    void loadSkus()
    return () => {
      cancelled = true
    }
  }, [branches.join(',')])

  useEffect(() => {
    let cancelled = false
    async function loadCustomers() {
      setLoadingCustomers(true)
      try {
        const result = await api.getCustomers(selectedRouteIds)
        if (!cancelled) {
          setCustomers(result)
          setCustomerIds((current) => current.filter((id) => result.some((customer) => customer.customer_id === id)))
        }
      } catch {
        if (!cancelled) setCustomers([])
      } finally {
        if (!cancelled) setLoadingCustomers(false)
      }
    }
    void loadCustomers()
    return () => {
      cancelled = true
    }
  }, [routeIds.join(',')])

  useEffect(() => {
    if (!prefill) return
    setDateFrom(toInputDate(prefill.date_from))
    setDateTo(toInputDate(prefill.date_to))
    setRouteIds(prefill.route_ids?.length ? prefill.route_ids : fixedRoutes.map((route) => route.route_id))
    setBranches(prefill.branches?.length ? prefill.branches : allBranches)
    setSkuIds(prefill.sku_ids ?? [])
    setCustomerIds(prefill.customer_ids ?? [])
    setNotice({ type: 'success', message: 'Filters from chat were applied. Review them, then generate your report.' })
    onPrefillConsumed()
  }, [prefill])

  function toggleRoute(routeId: number) {
    const next = routeIds.includes(routeId)
      ? routeIds.filter((id) => id !== routeId)
      : [...routeIds, routeId]
    setRouteIds(next)
    setCustomerIds([])
  }

  function selectAllRoutes() {
    setRouteIds(fixedRoutes.map((r) => r.route_id))
    setCustomerIds([])
  }

  function clearAllRoutes() {
    setRouteIds([])
    setCustomerIds([])
  }

  function download(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    setTimeout(() => {
      link.remove()
      URL.revokeObjectURL(url)
    }, 1500)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setHasAttempted(true)
    setNotice(null)
    if (!isValid || !outputFormat) return
    const payload: ReportRequest = {
      date_from: toIndianDate(dateFrom),
      date_to: toIndianDate(dateTo),
      ...(routeIds.length === fixedRoutes.length ? {} : { route_ids: routeIds }),
      ...(branches.length === allBranches.length ? {} : { branches }),
      ...(skuIds.length ? { sku_ids: skuIds } : {}),
      ...(customerIds.length ? { customer_ids: customerIds } : {}),
      generate_chart: generateChart,
      output_format: outputFormat,
      ...(notes.trim() ? { notes: notes.trim() } : {}),
    }
    setIsGenerating(true)
    try {
      const result = await api.report(payload)
      if (result.kind === 'no_data') {
        setNotice({ type: 'empty', message: result.message })
      } else {
        download(result.blob, result.filename)
        setNotice({ type: 'success', message: `${result.filename} has been generated and downloaded successfully.` })
      }
    } catch (error) {
      setNotice({
        type: 'error',
        message: error instanceof Error ? error.message : 'Report generation failed. Please try again.'
      })
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <section className="workspace report-workspace" aria-label="Generate sales report">
      <header className="workspace-heading">
        <div>
          <p className="eyebrow">Structured export</p>
          <h1>Generate a report</h1>
          <p className="workspace-subtitle">Build a reusable sales view and export it in the format you need.</p>
        </div>
      </header>

      <form className="report-form" onSubmit={submit} noValidate>
        <fieldset disabled={isGenerating}>
          {/* Card 1: Date Range */}
          <div className="report-step-card">
            <div className="step-card-header">
              <div className="step-number-badge">01</div>
              <div className="step-header-text">
                <div className="step-title-row">
                  <h2>
                    Date range <span className="required-pill">Required</span>
                  </h2>
                </div>
                <p>Select the date range for the report. Both dates are included.</p>
              </div>
            </div>
            <div className="date-grid">
              <div className="date-field-group">
                <label className="date-field-label" htmlFor="date-from">
                  <Calendar size={14} />
                  <span>Start date</span>
                </label>
                <div className="date-input-wrapper">
                  <input
                    id="date-from"
                    type="date"
                    value={dateFrom}
                    onChange={(event) => setDateFrom(event.target.value)}
                    aria-invalid={Boolean((hasAttempted && !dateFrom) || dateError)}
                  />
                </div>
              </div>
              <div className="date-field-group">
                <label className="date-field-label" htmlFor="date-to">
                  <Calendar size={14} />
                  <span>End date</span>
                </label>
                <div className="date-input-wrapper">
                  <input
                    id="date-to"
                    type="date"
                    value={dateTo}
                    onChange={(event) => setDateTo(event.target.value)}
                    aria-invalid={Boolean((hasAttempted && !dateTo) || dateError)}
                  />
                </div>
              </div>
            </div>
            {hasAttempted && (!dateFrom || !dateTo) && (
              <p className="field-error-msg">Please select both a start and end date.</p>
            )}
            {dateError && <p className="field-error-msg">{dateError}</p>}
          </div>

          {/* Card 2: Routes (Modern Selectable Cards / Filter Chips) */}
          <div className="report-step-card">
            <div className="step-card-header">
              <div className="step-number-badge">02</div>
              <div className="step-header-text">
                <div className="step-title-row">
                  <h2>Routes</h2>
                  <span className="selection-summary-badge">{routesSummary}</span>
                </div>
                <p>Selecting routes updates the available customers below.</p>
              </div>
            </div>
            <div className="routes-toolbar">
              <button
                type="button"
                className="text-button"
                onClick={routeIds.length === fixedRoutes.length ? clearAllRoutes : selectAllRoutes}
              >
                {routeIds.length === fixedRoutes.length ? 'Clear all' : 'Select all'}
              </button>
            </div>
            <div className="routes-grid" role="group" aria-label="Route selection">
              {fixedRoutes.map((route) => {
                const isSelected = routeIds.includes(route.route_id)
                return (
                  <div
                    key={route.route_id}
                    className={`route-card-item ${isSelected ? 'selected' : ''}`}
                    onClick={() => toggleRoute(route.route_id)}
                    role="checkbox"
                    aria-checked={isSelected}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === ' ' || e.key === 'Enter') {
                        e.preventDefault()
                        toggleRoute(route.route_id)
                      }
                    }}
                  >
                    <div className="route-check-box">
                      {isSelected && <Check size={12} />}
                    </div>
                    <span>{route.route_name}</span>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Card 3: Customers */}
          <div className="report-step-card">
            <div className="step-card-header">
              <div className="step-number-badge">03</div>
              <div className="step-header-text">
                <div className="step-title-row">
                  <h2>Customers</h2>
                  <span className="selection-summary-badge">{customerSummary}</span>
                </div>
                <p>Only customers serviced on the selected routes appear here.</p>
              </div>
            </div>
            <SearchableChecklist
              options={customers}
              selectedIds={customerIds}
              onChange={setCustomerIds}
              getId={(customer) => customer.customer_id}
              getLabel={(customer) => customer.canonical_name}
              placeholder="Search customers by name..."
              isLoading={loadingCustomers}
            />
          </div>

          {/* Card 4: Product Selection */}
          <div className="report-step-card">
            <div className="step-card-header">
              <div className="step-number-badge">04</div>
              <div className="step-header-text">
                <div className="step-title-row">
                  <h2>Product selection</h2>
                  <span className="selection-summary-badge">{skuSummary}</span>
                </div>
                <p>Choose product branches first, then optionally refine to specific SKUs.</p>
              </div>
            </div>
            <label className="sub-label">Branches</label>
            <ChipGroup
              label="Product branches"
              options={allBranches}
              selected={branches}
              onChange={setBranches}
            />
            <label className="sub-label">SKUs</label>
            <SearchableChecklist
              options={skus}
              selectedIds={skuIds}
              onChange={setSkuIds}
              getId={(sku) => sku.sku_id}
              getLabel={(sku) => sku.sku_name}
              placeholder="Search SKUs by name..."
              isLoading={loadingSkus}
            />
          </div>

          {/* Card 5: Visual Summary / Chart */}
          <div className="report-step-card">
            <div className="step-card-header">
              <div className="step-number-badge">05</div>
              <div className="step-header-text">
                <div className="toggle-row">
                  <div>
                    <h2>Generate chart</h2>
                    <p>Include visual summary charts in the exported report.</p>
                  </div>
                  <label className="switch" aria-label="Toggle generate chart">
                    <input
                      type="checkbox"
                      checked={generateChart}
                      onChange={(event) => setGenerateChart(event.target.checked)}
                    />
                    <span />
                  </label>
                </div>
              </div>
            </div>
            {generateChart && (
              <div className="chart-placeholder-box">
                <p>Automatic sales volume & revenue charts will be embedded into the report.</p>
              </div>
            )}
          </div>

          {/* Card 6: Output Format */}
          <div className="report-step-card">
            <div className="step-card-header">
              <div className="step-number-badge">06</div>
              <div className="step-header-text">
                <h2>
                  Output format <span className="required-pill">Required</span>
                </h2>
                <p>Select the preferred file format for export.</p>
              </div>
            </div>
            <div className="format-options-grid" role="radiogroup" aria-label="Output format">
              <label
                className={`format-card ${outputFormat === 'excel' ? 'selected' : ''}`}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === ' ' || e.key === 'Enter') {
                    e.preventDefault()
                    setOutputFormat('excel')
                  }
                }}
              >
                <input
                  type="radio"
                  name="format"
                  value="excel"
                  checked={outputFormat === 'excel'}
                  onChange={() => setOutputFormat('excel')}
                />
                <div className="format-icon-badge format-icon-excel">
                  <FileSpreadsheet size={22} />
                </div>
                <div>
                  <strong>Excel (.xlsx)</strong>
                  <small>Full analysis workbook</small>
                </div>
              </label>
              <label
                className={`format-card ${outputFormat === 'pdf' ? 'selected' : ''}`}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === ' ' || e.key === 'Enter') {
                    e.preventDefault()
                    setOutputFormat('pdf')
                  }
                }}
              >
                <input
                  type="radio"
                  name="format"
                  value="pdf"
                  checked={outputFormat === 'pdf'}
                  onChange={() => setOutputFormat('pdf')}
                />
                <div className="format-icon-badge format-icon-pdf">
                  <FileText size={22} />
                </div>
                <div>
                  <strong>PDF (.pdf)</strong>
                  <small>Executive formatted document</small>
                </div>
              </label>
            </div>
            {hasAttempted && !outputFormat && (
              <p className="field-error-msg">Please select either Excel or PDF before generating.</p>
            )}
          </div>

          {/* Card 7: Description / Notes */}
          <div className="report-step-card">
            <div className="step-card-header">
              <div className="step-number-badge">07</div>
              <div className="step-header-text">
                <h2>Description / special notes</h2>
                <p>Optional instructions are passed to the report generation engine.</p>
              </div>
            </div>
            <textarea
              className="notes-textarea"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Any specific instructions for this report (e.g. exclude returns, highlight top 5 customers)..."
              rows={4}
            />
          </div>
        </fieldset>

        {/* Notices */}
        {notice && (
          <div className={`report-notice ${notice.type}`} role="status">
            {notice.type === 'success' && <CheckCircle size={18} />}
            {notice.type === 'empty' && <Info size={18} />}
            {notice.type === 'error' && <AlertCircle size={18} />}
            <span>{notice.message}</span>
            {notice.type === 'error' && (
              <button type="button" className="notice-dismiss-btn" onClick={() => setNotice(null)}>
                Dismiss
              </button>
            )}
          </div>
        )}

        {/* Bottom Action Card */}
        <div className="report-action-card">
          <p>Complete required fields (Date range & Format) to generate your report.</p>
          <button className="primary-button" type="submit" disabled={isGenerating || !isValid}>
            {isGenerating ? (
              <>
                <span className="button-spinner" />
                <span>Generating report...</span>
              </>
            ) : (
              <>
                <span>Generate report</span>
                <ArrowRight size={16} />
              </>
            )}
          </button>
        </div>
      </form>
    </section>
  )
}
