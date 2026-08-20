import { useEffect, useMemo, useState } from 'react'
import { authFetch } from '../utils/authFetch'
import '../styles/PatrolResults.css'

const PAGE_SIZE = 12
const STATUS_LABEL = {
  pending: '待开始',
  running: '巡检中',
  paused: '已暂停',
  completed: '已完成',
  cancelled: '已取消',
}

const formatDate = (value) => {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

const formatSize = (bytes) => {
  if (!Number.isFinite(bytes)) return '--'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const mediaUrl = (relativePath) => (
  `/api/patrol-results/media/${relativePath.split('/').map(encodeURIComponent).join('/')}`
)

function ResultIcon({ type }) {
  if (type === 'video') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="14" height="14" rx="2" /><path d="m17 10 4-2v8l-4-2" /></svg>
  }
  if (type === 'track') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="18" r="2" /><circle cx="19" cy="6" r="2" /><path d="M7 18h2a3 3 0 0 0 3-3v-6a3 3 0 0 1 3-3h2" /></svg>
  }
  if (type === 'ai') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="3" /><path d="M9 9h6v6H9zM9 2v3m6-3v3M9 19v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3" /></svg>
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="8.5" cy="9" r="1.5" /><path d="m4 17 4.5-4 3.5 3 2.5-2 5.5 5" /></svg>
}

function TrackPreview({ points = [], large = false }) {
  const coordinates = points
    .map(point => [Number(point.lng), Number(point.lat)])
    .filter(([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat))

  if (coordinates.length === 0) return <div className="pr-track-empty">暂无有效轨迹点</div>

  const lngs = coordinates.map(point => point[0])
  const lats = coordinates.map(point => point[1])
  const minLng = Math.min(...lngs)
  const maxLng = Math.max(...lngs)
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const lngRange = maxLng - minLng || 0.00001
  const latRange = maxLat - minLat || 0.00001
  const pathPoints = coordinates.map(([lng, lat]) => {
    const x = 10 + ((lng - minLng) / lngRange) * 80
    const y = 90 - ((lat - minLat) / latRange) * 80
    return `${x.toFixed(2)},${y.toFixed(2)}`
  }).join(' ')
  const [startX, startY] = pathPoints.split(' ')[0].split(',')
  const [endX, endY] = pathPoints.split(' ').at(-1).split(',')

  return (
    <div className={`pr-track-preview ${large ? 'large' : ''}`}>
      <div className="pr-track-grid" />
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-label={`GPS 轨迹，共 ${coordinates.length} 个点`}>
        <polyline points={pathPoints} />
        <circle className="start" cx={startX} cy={startY} r="2.4" />
        <circle className="end" cx={endX} cy={endY} r="2.4" />
      </svg>
      <span className="pr-track-label start">起点</span>
      <span className="pr-track-label end">终点</span>
    </div>
  )
}

export default function PatrolResults() {
  const [items, setItems] = useState([])
  const [counts, setCounts] = useState({ all: 0, image: 0, video: 0, track: 0, ai: 0 })
  const [resultType, setResultType] = useState('all')
  const [searchText, setSearchText] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [previewItem, setPreviewItem] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchText.trim()), 300)
    return () => clearTimeout(timer)
  }, [searchText])

  useEffect(() => {
    const controller = new AbortController()
    const loadResults = async () => {
      setLoading(true)
      setError('')
      try {
        const params = new URLSearchParams({ result_type: resultType })
        if (debouncedSearch) params.set('query', debouncedSearch)
        const response = await authFetch(`/api/patrol-results?${params}`, { signal: controller.signal })
        if (!response.ok) throw new Error('巡航成果加载失败')
        const data = await response.json()
        setItems(data.items || [])
        setCounts(data.counts || { all: 0, image: 0, video: 0, track: 0, ai: 0 })
        setPage(1)
      } catch (requestError) {
        if (requestError.name !== 'AbortError') setError(requestError.message)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    loadResults()
    return () => controller.abort()
  }, [resultType, debouncedSearch, refreshKey])

  useEffect(() => {
    if (!previewItem) return undefined
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setPreviewItem(null)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [previewItem])

  const pageCount = Math.max(1, Math.ceil(items.length / PAGE_SIZE))
  const visibleItems = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE
    return items.slice(start, start + PAGE_SIZE)
  }, [items, page])

  const filters = [
    { value: 'all', label: '全部', count: counts.all },
    { value: 'image', label: '图片', count: counts.image },
    { value: 'video', label: '视频', count: counts.video },
    { value: 'track', label: '轨迹', count: counts.track },
    { value: 'ai', label: 'AI分析结果', count: counts.ai },
  ]

  const typeLabel = { image: '图片', video: '视频', track: '轨迹', ai: 'AI分析' }

  const renderCardPreview = (item) => {
    if (item.type === 'image') return <img src={mediaUrl(item.relative_path)} alt={item.name} loading="lazy" />
    if (item.type === 'video') return <video src={mediaUrl(item.relative_path)} preload="metadata" muted playsInline />
    if (item.type === 'track') return <TrackPreview points={item.gps_track} />
    return (
      <div className="pr-ai-preview">
        {item.preview_path
          ? <img src={mediaUrl(item.preview_path)} alt={item.name} loading="lazy" />
          : <span className="pr-ai-core"><ResultIcon type="ai" /></span>}
        <div className="pr-ai-scan" />
        <strong>{item.confidence === null ? 'AI' : `${item.confidence}%`}</strong>
        <small>{item.severity}</small>
      </div>
    )
  }

  const renderModalPreview = (item) => {
    if (item.type === 'image') return <img src={mediaUrl(item.relative_path)} alt={item.name} />
    if (item.type === 'video') return <video src={mediaUrl(item.relative_path)} controls autoPlay preload="metadata" playsInline />
    if (item.type === 'track') return <TrackPreview points={item.gps_track} large />
    return (
      <div className="pr-ai-detail">
        {item.preview_path
          ? <img src={mediaUrl(item.preview_path)} alt={item.name} />
          : <span className="pr-ai-detail-icon"><ResultIcon type="ai" /></span>}
        <span>AI ANALYSIS RESULT</span>
        <strong>{item.confidence === null ? '--' : `${item.confidence}%`}</strong>
        <small>分析置信度</small>
      </div>
    )
  }

  return (
    <div className="patrol-results-page">
      <header className="pr-header">
        <div>
          <span className="pr-kicker">PATROL ARCHIVE</span>
          <h1>巡检成果</h1>
          <p>集中查看巡航图片、视频、GPS 轨迹与 AI 分析结果</p>
        </div>
        <button className="pr-refresh" type="button" onClick={() => setRefreshKey(key => key + 1)} disabled={loading}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 4v7h-7" /></svg>
          刷新成果
        </button>
      </header>

      <section className="pr-summary" aria-label="成果统计">
        <button className={resultType === 'all' ? 'active' : ''} onClick={() => setResultType('all')}>
          <span className="pr-summary-icon all"><ResultIcon type="image" /></span>
          <span><small>成果总数</small><strong>{counts.all}</strong><em>项</em></span>
        </button>
        <button className={resultType === 'image' ? 'active' : ''} onClick={() => setResultType('image')}>
          <span className="pr-summary-icon image"><ResultIcon type="image" /></span>
          <span><small>图片数据</small><strong>{counts.image}</strong><em>张</em></span>
        </button>
        <button className={resultType === 'video' ? 'active' : ''} onClick={() => setResultType('video')}>
          <span className="pr-summary-icon video"><ResultIcon type="video" /></span>
          <span><small>视频数据</small><strong>{counts.video}</strong><em>个</em></span>
        </button>
        <button className={resultType === 'track' ? 'active' : ''} onClick={() => setResultType('track')}>
          <span className="pr-summary-icon track"><ResultIcon type="track" /></span>
          <span><small>巡航轨迹</small><strong>{counts.track}</strong><em>条</em></span>
        </button>
        <button className={resultType === 'ai' ? 'active' : ''} onClick={() => setResultType('ai')}>
          <span className="pr-summary-icon ai"><ResultIcon type="ai" /></span>
          <span><small>AI分析结果</small><strong>{counts.ai}</strong><em>项</em></span>
        </button>
      </section>

      <section className="pr-content">
        <div className="pr-toolbar">
          <div className="pr-tabs">
            {filters.map(filter => (
              <button key={filter.value} className={resultType === filter.value ? 'active' : ''} onClick={() => setResultType(filter.value)}>
                {filter.label}<span>{filter.count}</span>
              </button>
            ))}
          </div>
          <label className="pr-search">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></svg>
            <input value={searchText} onChange={event => setSearchText(event.target.value)} placeholder="搜索成果名称、设备、线路或标签" />
            {searchText && <button type="button" onClick={() => setSearchText('')} aria-label="清除搜索">×</button>}
          </label>
        </div>

        {loading ? (
          <div className="pr-state"><span className="pr-spinner" /><p>正在读取巡航成果...</p></div>
        ) : error ? (
          <div className="pr-state error"><strong>加载失败</strong><p>{error}</p><button onClick={() => setRefreshKey(key => key + 1)}>重新加载</button></div>
        ) : visibleItems.length === 0 ? (
          <div className="pr-state"><span className="pr-empty-icon"><ResultIcon type={resultType === 'all' ? 'image' : resultType} /></span><strong>暂无匹配的巡航成果</strong><p>请调整筛选条件，或先生成对应的巡航成果。</p></div>
        ) : (
          <div className="pr-grid">
            {visibleItems.map(item => {
              return (
                <article className={`pr-card ${item.type}`} key={item.id} onClick={() => setPreviewItem(item)}>
                  <div className="pr-media">
                    {renderCardPreview(item)}
                    <span className={`pr-type ${item.type}`}><ResultIcon type={item.type} />{typeLabel[item.type]}</span>
                    {item.type === 'video' && <span className="pr-play"><svg viewBox="0 0 24 24"><path d="m9 7 8 5-8 5Z" /></svg></span>}
                  </div>
                  <div className="pr-card-body">
                    <h2 title={item.name}>{item.name}</h2>
                    <p><span>巡航设备</span><strong>{item.device_name}</strong></p>
                    <p><span>采集时间</span><strong>{formatDate(item.captured_at)}</strong></p>
                    {item.type === 'ai' && <p><span>分析摘要</span><strong>{item.summary}</strong></p>}
                    <div className="pr-card-footer">
                      <span>{item.source}</span>
                      <span>{item.type === 'track' ? `${item.point_count} 点` : item.type === 'ai' ? (item.labels?.join('、') || item.severity) : formatSize(item.size)}</span>
                    </div>
                  </div>
                </article>
              )
            })}
          </div>
        )}

        {!loading && !error && items.length > 0 && (
          <footer className="pr-pagination">
            <span>共 {items.length} 条成果</span>
            <div>
              <button disabled={page === 1} onClick={() => setPage(value => value - 1)}>上一页</button>
              <strong>{page}</strong><span>/ {pageCount}</span>
              <button disabled={page === pageCount} onClick={() => setPage(value => value + 1)}>下一页</button>
            </div>
          </footer>
        )}
      </section>

      {previewItem && (
        <div className="pr-modal" role="dialog" aria-modal="true" onMouseDown={() => setPreviewItem(null)}>
          <div className="pr-modal-panel" onMouseDown={event => event.stopPropagation()}>
            <button className="pr-modal-close" onClick={() => setPreviewItem(null)} aria-label="关闭预览">×</button>
            <div className="pr-modal-media">
              {renderModalPreview(previewItem)}
            </div>
            <div className="pr-modal-info">
              <div><span>{typeLabel[previewItem.type]}成果</span><h2>{previewItem.name}</h2></div>
              <dl>
                <div><dt>巡航设备</dt><dd>{previewItem.device_name}</dd></div>
                <div><dt>采集时间</dt><dd>{formatDate(previewItem.captured_at)}</dd></div>
                {previewItem.type === 'track' && <div><dt>轨迹点数</dt><dd>{previewItem.point_count} 个</dd></div>}
                {previewItem.type === 'track' && <div><dt>任务状态</dt><dd>{STATUS_LABEL[previewItem.status] || previewItem.status}</dd></div>}
                {previewItem.type === 'ai' && <div><dt>分析摘要</dt><dd>{previewItem.summary}</dd></div>}
                {previewItem.type === 'ai' && <div><dt>风险等级</dt><dd>{previewItem.severity}</dd></div>}
                {previewItem.type === 'ai' && <div><dt>识别标签</dt><dd>{previewItem.labels?.join('、') || '--'}</dd></div>}
                {(previewItem.type === 'image' || previewItem.type === 'video') && <div><dt>文件大小</dt><dd>{formatSize(previewItem.size)}</dd></div>}
                <div><dt>{previewItem.type === 'track' ? '巡检线路' : previewItem.type === 'ai' ? '分析来源' : '数据来源'}</dt><dd>{previewItem.source}</dd></div>
              </dl>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
