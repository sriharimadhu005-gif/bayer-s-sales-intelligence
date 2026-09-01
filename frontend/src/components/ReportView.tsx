import { FormEvent, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Branch, Customer, ReportPrefill, ReportRequest, Sku } from '../types'

const allDays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const fixedRoutes = Array.from({ length: 7 }, (_, index) => ({ route_id: index + 1, route_name: `Route ${index + 1}` }))
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

function ChipGroup<T extends string>({ label, options, selected, onChange, disabled = false }: {
  label: string
  options: T[]
  selected: T[]
  onChange: (value: T[]) => void
  disabled?: boolean
}) {
  return (
    <div className="chip-group" aria-label={label}>
      {options.map((option) => (
        <button key={option} type="button" className={`choice-chip ${selected.includes(option) ? 'selected' : ''}`} onClick={() => onChange(toggleValue(selected, option, options))} disabled={disabled}>
          {option === 'coffee' || option === 'tea' || option === 'others' ? option[0].toUpperCase() + option.slice(1) : option}
        </button>
      ))}
    </div>
  )
}

function SearchableChecklist<T extends object, IdType extends string | number = number>({ options, selectedIds, onChange, getId, getLabel, placeholder, isLoading, disabled }: {
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
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={placeholder} disabled={disabled || isLoading} aria-label={placeholder} />
        <button type="button" className="text-button" onClick={() => onChange(allSelected ? [] : options.map(getId))} disabled={disabled || isLoading || !options.length}>
          {allSelected ? 'Clear' : 'Select all'}
        </button>
      </div>
      <div className="checklist">
        {isLoading && <span className="select-state">Loading options...</span>}
        {!isLoading && !visible.length && <span className="select-state">No matching options.</span>}
        {!isLoading && visible.map((option) => {
          const id = getId(option)
          return <label className="check-option" key={id}><input type="checkbox" checked={selectedIds.includes(id)} onChange={() => onChange(selectedIds.includes(id) ? selectedIds.filter((selected) => selected !== id) : [...selectedIds, id])} disabled={disabled} /><span>{getLabel(option)}</span></label>
        })}
      </div>
    </div>
  )
}

export function ReportView({ prefill, onPrefillConsumed }: { prefill: ReportPrefill | null; onPrefillConsumed: () => void }) {
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [days, setDays] = useState(allDays)
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
  const routesSummary = routeIds.length === fixedRoutes.length ? 'All 7 routes' : `${routeIds.length} route${routeIds.length === 1 ? '' : 's'} selected`
  const skuSummary = skuIds.length ? `${skuIds.length} SKU${skuIds.length === 1 ? '' : 's'} selected` : 'All matching SKUs'
  const customerSummary = customerIds.length ? `${customerIds.length} customer${customerIds.length === 1 ? '' : 's'} selected` : 'All customers in selected routes'

  useEffect(() => {
    let cancelled = false
    async function loadSkus() {
      setLoadingSkus(true)
      try {
        const result = selectedBranches.length === allBranches.length
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
    return () => { cancelled = true }
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
    return () => { cancelled = true }
  }, [routeIds.join(',')])

  useEffect(() => {
    if (!prefill) return
    setDateFrom(toInputDate(prefill.date_from))
    setDateTo(toInputDate(prefill.date_to))
    setDays(prefill.days?.length ? prefill.days : allDays)
    setRouteIds(prefill.route_ids?.length ? prefill.route_ids : fixedRoutes.map((route) => route.route_id))
    setBranches(prefill.branches?.length ? prefill.branches : allBranches)
    setSkuIds(prefill.sku_ids ?? [])
    setCustomerIds(prefill.customer_ids ?? [])
    setNotice({ type: 'success', message: 'Filters from chat were applied. Review them, then generate your report.' })
    onPrefillConsumed()
  }, [prefill])

  function changeRoutes(nextIds: number[]) {
    setRouteIds(nextIds)
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
      ...(days.length === allDays.length ? {} : { days }),
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
      if (result.kind === 'no_data') setNotice({ type: 'empty', message: result.message })
      else {
        download(result.blob, result.filename)
        setNotice({ type: 'success', message: `${result.filename} has been generated and downloaded.` })
      }
    } catch (error) {
      setNotice({ type: 'error', message: error instanceof Error ? error.message : 'Report generation failed. Please try again.' })
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
        <div className="dataset-note"><span className="status-dot" />Evaluation dataset <span>As loaded for this phase</span></div>
      </header>

      <form className="report-form" onSubmit={submit} noValidate>
        <fieldset disabled={isGenerating}>
          <div className="form-section date-section">
            <div className="section-number">01</div>
            <div className="section-content">
              <div className="section-title-row"><div><h2>Date range <span className="required">Required</span></h2><p>Both dates are included in the report.</p></div></div>
              <div className="date-grid">
                <label>From<input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} aria-invalid={Boolean((hasAttempted && !dateFrom) || dateError)} /></label>
                <label>To<input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} aria-invalid={Boolean((hasAttempted && !dateTo) || dateError)} /></label>
              </div>
              {(hasAttempted && (!dateFrom || !dateTo)) && <p className="field-error">Select both a start and end date.</p>}
              {dateError && <p className="field-error">{dateError}</p>}
            </div>
          </div>

          <div className="form-section">
            <div className="section-number">02</div>
            <div className="section-content"><h2>Days of week</h2><p>All days are included by default. Select only the days to filter.</p><ChipGroup label="Days of week" options={allDays} selected={days} onChange={setDays} /></div>
          </div>

          <div className="form-section">
            <div className="section-number">03</div>
            <div className="section-content"><div className="section-title-row"><div><h2>Routes</h2><p>Changing routes refreshes the customer list.</p></div><span className="selection-summary">{routesSummary}</span></div>
              <SearchableChecklist options={fixedRoutes} selectedIds={routeIds} onChange={changeRoutes} getId={(route) => route.route_id} getLabel={(route) => route.route_name} placeholder="Search routes" />
            </div>
          </div>

          <div className="form-section sku-section">
            <div className="section-number">04</div>
            <div className="section-content"><div className="section-title-row"><div><h2>Product selection</h2><p>Choose branches first, then optionally refine to individual SKUs.</p></div><span className="selection-summary">{skuSummary}</span></div>
              <label className="input-label">Branch</label>
              <ChipGroup label="Product branches" options={allBranches} selected={branches} onChange={setBranches} />
              <label className="input-label sku-label">SKUs</label>
              <SearchableChecklist options={skus} selectedIds={skuIds} onChange={setSkuIds} getId={(sku) => sku.sku_id} getLabel={(sku) => sku.sku_name} placeholder="Search matching SKUs" isLoading={loadingSkus} />
            </div>
          </div>

          <div className="form-section">
            <div className="section-number">05</div>
            <div className="section-content"><div className="section-title-row"><div><h2>Customers</h2><p>Only customers mapped to the selected routes appear here.</p></div><span className="selection-summary">{customerSummary}</span></div>
              <SearchableChecklist options={customers} selectedIds={customerIds} onChange={setCustomerIds} getId={(customer) => customer.customer_id} getLabel={(customer) => customer.canonical_name} placeholder="Search customers" isLoading={loadingCustomers} />
            </div>
          </div>

          <div className="form-section compact-section">
            <div className="section-number">06</div>
            <div className="section-content"><div className="toggle-row"><div><h2>Generate chart</h2><p>Include a visual summary in the exported report.</p></div><label className="switch"><input type="checkbox" checked={generateChart} onChange={(event) => setGenerateChart(event.target.checked)} /><span /></label></div>
              {generateChart && <div className="chart-placeholder"><label>Chart type<select disabled value=""><option>Chart types will be configured by the backend team</option></select></label><p>Chart type selection is reserved for the pending final option set.</p></div>}
            </div>
          </div>

          <div className="form-section compact-section">
            <div className="section-number">07</div>
            <div className="section-content"><h2>Output format <span className="required">Required</span></h2><p>Select exactly one file format.</p>
              <div className="format-options" role="radiogroup" aria-label="Output format">
                <label className={`format-option ${outputFormat === 'excel' ? 'selected' : ''}`}><input type="radio" name="format" value="excel" checked={outputFormat === 'excel'} onChange={() => setOutputFormat('excel')} /><span className="format-icon">X</span><span><strong>Excel</strong><small>Editable workbook</small></span></label>
                <label className={`format-option ${outputFormat === 'pdf' ? 'selected' : ''}`}><input type="radio" name="format" value="pdf" checked={outputFormat === 'pdf'} onChange={() => setOutputFormat('pdf')} /><span className="format-icon">P</span><span><strong>PDF</strong><small>Formatted document</small></span></label>
              </div>
              {hasAttempted && !outputFormat && <p className="field-error">Choose Excel or PDF before generating.</p>}
            </div>
          </div>

          <div className="form-section notes-section">
            <div className="section-number">08</div>
            <div className="section-content"><h2>Description / notes</h2><p>Optional instructions are passed to the report engine as-is.</p><textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Any specific instructions for this report (e.g. exclude returns, highlight top 5 customers)..." rows={4} /></div>
          </div>
        </fieldset>

        {notice && <div className={`report-notice ${notice.type}`} role="status"><span>{notice.type === 'success' ? '✓' : notice.type === 'empty' ? 'i' : '!'}</span>{notice.message}{notice.type === 'error' && <button type="button" onClick={() => setNotice(null)}>Dismiss</button>}</div>}
        <div className="report-action"><p>Required fields must be complete before generating.</p><button className="primary-button" type="submit" disabled={isGenerating || !isValid}>{isGenerating ? <><span className="button-spinner" />Generating...</> : <>Generate report <span aria-hidden="true">→</span></>}</button></div>
      </form>
    </section>
  )
}
