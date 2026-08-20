import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api, ANALYTICS_COLORS, useChart, fmtNum, fmtDate, CATEGORY_LABELS } from './AnalyticsShared'
import '../styles/Analytics.css'

/**
 * 指标详情页：单指标下钻
 *
 * 路由：/statistics-analysis/indicator/:code
 */
export default function AnalyticsIndicatorDetail() {
  const { code } = useParams()
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [compare, setCompare] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let disposed = false
    setLoading(true)
    api(`/indicators/${code}?days=${days}`)
      .then((d) => { if (!disposed) setData(d) })
      .catch((e) => { if (!disposed) setError(e.message) })
      .finally(() => { if (!disposed) setLoading(false) })
    return () => { disposed = true }
  }, [code, days])

  const series = data?.series || []
  // 构造同环比序列（窗口平移）
  const buildShifted = (arr, offset) => {
    const out = new Array(arr.length).fill(null)
    for (let i = 0; i < arr.length; i++) {
      const src = i - offset
      if (src >= 0 && src < arr.length) out[i] = arr[src]
    }
    return out
  }

  const chartOption = data ? {
    legend: {
      top: 0,
      textStyle: { color: ANALYTICS_COLORS.textSecondary, fontSize: 11 },
      data: compare ? ['当期', '7 日前', '14 日前'] : ['当期'],
    },
    grid: { left: 60, right: 24, top: 40, bottom: 40 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: series.map((p) => fmtDate(p.date)),
      axisLine: { lineStyle: { color: ANALYTICS_COLORS.border } },
      axisLabel: { color: ANALYTICS_COLORS.textSecondary, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      name: data.unit || '',
      nameTextStyle: { color: ANALYTICS_COLORS.muted, fontSize: 11 },
      axisLabel: { color: ANALYTICS_COLORS.textSecondary, fontSize: 11 },
      splitLine: { lineStyle: { color: ANALYTICS_COLORS.border } },
    },
    series: [
      {
        name: '当期', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,
        data: series.map((p) => p.value),
        lineStyle: { color: ANALYTICS_COLORS.cyan, width: 2 },
        itemStyle: { color: ANALYTICS_COLORS.cyan },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(43, 210, 255, .3)' },
              { offset: 1, color: 'rgba(43, 210, 255, 0)' },
            ],
          },
        },
      },
      ...(compare ? [
        {
          name: '7 日前', type: 'line', smooth: true, symbol: 'none',
          data: buildShifted(series.map((p) => p.value), 7),
          lineStyle: { color: ANALYTICS_COLORS.warning, width: 1.5, type: 'dashed' },
          itemStyle: { color: ANALYTICS_COLORS.warning },
        },
        {
          name: '14 日前', type: 'line', smooth: true, symbol: 'none',
          data: buildShifted(series.map((p) => p.value), 14),
          lineStyle: { color: ANALYTICS_COLORS.purple, width: 1.5, type: 'dashed' },
          itemStyle: { color: ANALYTICS_COLORS.purple },
        },
      ] : []),
    ],
  } : {}

  const { chartRef } = useChart(chartOption, [data, compare])

  // 计算基础统计
  const values = series.map((p) => p.value).filter((v) => v !== null && v !== undefined)
  const latest = values.length ? values[values.length - 1] : null
  const avg = values.length ? values.reduce((s, v) => s + v, 0) / values.length : null
  const max = values.length ? Math.max(...values) : null
  const min = values.length ? Math.min(...values) : null

  return (
    <div className="analytics-indicator-detail-page">
      <div className="analytics-page-header">
        <h2>
          <Link to="/statistics-analysis" style={{ color: 'var(--sub-muted)', textDecoration: 'none' }}>研判</Link>
          {' / '}
          {data?.name || code}
        </h2>
        <div className="tabs">
          {[7, 30, 90, 365].map((d) => (
            <button
              key={d}
              className={`tab ${days === d ? 'active' : ''}`}
              onClick={() => setDays(d)}
            >
              {d === 365 ? '1 年' : `${d} 天`}
            </button>
          ))}
        </div>
      </div>

      <div className="analytics-body">
        {error && <div className="a-empty" style={{ color: 'var(--sub-danger)' }}>{error}</div>}

        {/* 概览数字 */}
        <div className="metric-grid">
          <div className="metric-card">
            <div className="mc-name">最新值</div>
            <div className="mc-value">{latest === null ? '--' : fmtNum(latest)}<span className="mc-unit">{data?.unit || ''}</span></div>
            <div className="mc-meta"><span className="mc-tag">最新</span><span>{series.length ? fmtDate(series[series.length - 1].date) : '——'}</span></div>
          </div>
          <div className="metric-card">
            <div className="mc-name">均值</div>
            <div className="mc-value">{avg === null ? '--' : fmtNum(avg)}<span className="mc-unit">{data?.unit || ''}</span></div>
            <div className="mc-meta"><span className="mc-tag">区间均值</span><span>共 {values.length} 个样本</span></div>
          </div>
          <div className="metric-card">
            <div className="mc-name">最大</div>
            <div className="mc-value" style={{ color: 'var(--sub-success)' }}>{max === null ? '--' : fmtNum(max)}<span className="mc-unit">{data?.unit || ''}</span></div>
            <div className="mc-meta"><span className="mc-tag">峰值</span><span>——</span></div>
          </div>
          <div className="metric-card">
            <div className="mc-name">最小</div>
            <div className="mc-value" style={{ color: 'var(--sub-warning)' }}>{min === null ? '--' : fmtNum(min)}<span className="mc-unit">{data?.unit || ''}</span></div>
            <div className="mc-meta"><span className="mc-tag">谷值</span><span>——</span></div>
          </div>
        </div>

        {/* 主趋势图 */}
        <div className="analytics-panel">
          <h3>
            时序趋势
            <span style={{ marginLeft: 10, fontSize: 12, color: 'var(--sub-muted)', fontWeight: 400 }}>
              {CATEGORY_LABELS[data?.category] || data?.category || ''} · {data?.unit || ''}
            </span>
            <div className="panel-tools">
              <label style={{ fontSize: 12, color: 'var(--sub-text-secondary)', cursor: 'pointer' }}>
                <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} style={{ marginRight: 4 }} />
                同环比
              </label>
            </div>
          </h3>
          <div className="chart-box" ref={chartRef} />
        </div>

        {/* 明细表格 */}
        <div className="analytics-panel">
          <h3>明细记录</h3>
          {loading ? <div className="a-empty">加载中…</div> : (
            <table className="a-table">
              <thead>
                <tr><th>日期</th><th>数值</th><th>单位</th><th>样本数</th></tr>
              </thead>
              <tbody>
                {series.slice().reverse().slice(0, 100).map((p, i) => (
                  <tr key={i}>
                    <td>{fmtDate(p.date)}</td>
                    <td>{p.value === null ? '--' : fmtNum(p.value)}</td>
                    <td>{data?.unit || ''}</td>
                    <td>{p.sample_count ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
