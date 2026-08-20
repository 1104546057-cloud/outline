import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ANALYTICS_COLORS, useChart, fmtNum, fmtDate, CATEGORY_LABELS } from './AnalyticsShared'
import '../styles/Analytics.css'

/**
 * 研判模块仪表盘
 *
 * 路由：/statistics-analysis 与 /analytics/dashboard 共用本组件
 *
 * 内容：
 * - 顶部 4 个总览数字（设备总数 / 在线 / 离线 / 待处置告警）
 * - 指标卡片网格（来自 /api/analytics/overview 的 indicators）
 * - 关键趋势缩略图（默认展示最近选择的指标的 30 日趋势）
 */
export default function AnalyticsDashboard() {
  const [overview, setOverview] = useState(null)
  const [trendCode, setTrendCode] = useState('device_online_rate')
  const [trendData, setTrendData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const loadOverview = async () => {
    try {
      const data = await api('/overview')
      setOverview(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const loadTrend = async (code) => {
    try {
      const data = await api(`/indicators/${code}?days=30`)
      setTrendData(data)
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => { loadOverview() }, [])
  useEffect(() => {
    if (trendCode) loadTrend(trendCode)
  }, [trendCode])

  const { chartRef } = useChart(trendData ? {
    grid: { left: 50, right: 24, top: 30, bottom: 36 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: trendData.series.map((p) => fmtDate(p.date)),
      axisLine: { lineStyle: { color: ANALYTICS_COLORS.border } },
      axisLabel: { color: ANALYTICS_COLORS.textSecondary, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: ANALYTICS_COLORS.textSecondary, fontSize: 11 },
      splitLine: { lineStyle: { color: ANALYTICS_COLORS.border } },
    },
    series: [{
      name: trendData.name,
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      data: trendData.series.map((p) => p.value),
      lineStyle: { color: ANALYTICS_COLORS.cyan, width: 2 },
      itemStyle: { color: ANALYTICS_COLORS.cyan },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(43, 210, 255, .35)' },
            { offset: 1, color: 'rgba(43, 210, 255, 0)' },
          ],
        },
      },
    }],
  } : {}, [trendData])

  const deviceTotal = overview?.device_total ?? 0
  const deviceOnline = overview?.device_online ?? 0
  const deviceOffline = deviceTotal - deviceOnline

  return (
    <div className="analytics-dashboard-page">
      <div className="analytics-page-header">
        <h2>数据统计研判</h2>
        <div className="tabs">
          <Link className="tab active" to="/statistics-analysis">仪表盘</Link>
          <Link className="tab" to="/statistics-analysis/rules">研判规则</Link>
          <Link className="tab" to="/statistics-analysis/reports">报告中心</Link>
        </div>
      </div>

      <div className="analytics-body">
        {error && <div className="a-empty" style={{ color: 'var(--sub-danger)' }}>加载失败：{error}</div>}

        {/* 总览计数 */}
        <div className="metric-grid">
          <div className="metric-card">
            <div className="mc-name">设备总数</div>
            <div className="mc-value">{deviceTotal}<span className="mc-unit">台</span></div>
            <div className="mc-meta"><span className="mc-tag">实时</span><span>——</span></div>
          </div>
          <div className="metric-card">
            <div className="mc-name">在线设备</div>
            <div className="mc-value" style={{ color: 'var(--sub-success)' }}>{deviceOnline}<span className="mc-unit">台</span></div>
            <div className="mc-meta"><span className="mc-tag">在线</span><span>{deviceTotal ? ((deviceOnline / deviceTotal) * 100).toFixed(1) : 0}%</span></div>
          </div>
          <div className="metric-card">
            <div className="mc-name">离线设备</div>
            <div className="mc-value" style={{ color: 'var(--sub-warning)' }}>{deviceOffline}<span className="mc-unit">台</span></div>
            <div className="mc-meta"><span className="mc-tag">离线</span><span>——</span></div>
          </div>
          <div className="metric-card">
            <div className="mc-name">研判指标</div>
            <div className="mc-value">{overview?.indicators?.length ?? 0}<span className="mc-unit">项</span></div>
            <div className="mc-meta"><span className="mc-tag">字典</span><span>已启用</span></div>
          </div>
        </div>

        {/* 指标卡片网格 */}
        {loading ? (
          <div className="a-empty">正在加载指标…</div>
        ) : overview?.indicators?.length ? (
          <div className="metric-grid">
            {overview.indicators.map((ind) => (
              <div
                key={ind.code}
                className="metric-card"
                onClick={() => setTrendCode(ind.code)}
                title="点击下方查看该指标趋势"
              >
                <div className="mc-name">{ind.name}</div>
                <div className="mc-value">
                  {ind.value === null || ind.value === undefined ? '--' : fmtNum(ind.value)}
                  {ind.unit && <span className="mc-unit">{ind.unit}</span>}
                </div>
                <div className="mc-meta">
                  <span className="mc-tag">{CATEGORY_LABELS[ind.category] || ind.category}</span>
                  <span>{ind.date ? fmtDate(ind.date) : '——'}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="a-empty">暂无启用指标，请先在指标字典中添加</div>
        )}

        {/* 趋势区 */}
        <div className="analytics-panel">
          <h3>
            趋势分析
            <span style={{ marginLeft: 10, fontSize: 12, color: 'var(--sub-muted)', fontWeight: 400 }}>
              当前指标：{trendData?.name || '——'}（最近 30 日）
            </span>
          </h3>
          <div className="chart-box" ref={chartRef} />
        </div>
      </div>
    </div>
  )
}
