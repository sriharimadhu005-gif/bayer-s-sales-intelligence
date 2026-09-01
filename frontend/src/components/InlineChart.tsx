import type { ChartPayload } from '../types'

export function InlineChart({ chart }: { chart: ChartPayload }) {
  if (chart.data.image_url) return <img className="chart-image" src={chart.data.image_url} alt="Sales chart returned by the analysis service" />
  const labels = chart.data.labels ?? []
  const values = chart.data.values ?? []
  const maximum = Math.max(...values, 1)

  return (
    <div className="mini-chart" aria-label={`${chart.type} chart`}>
      <div className="mini-chart-bars">
        {values.map((value, index) => (
          <div className="mini-chart-column" key={`${labels[index]}-${value}`}>
            <span className="mini-chart-value">{value.toLocaleString()}</span>
            <div className="mini-chart-track"><div className="mini-chart-bar" style={{ height: `${Math.max((value / maximum) * 100, 6)}%` }} /></div>
            <span className="mini-chart-label">{labels[index] ?? `Item ${index + 1}`}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
