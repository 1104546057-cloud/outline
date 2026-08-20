import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { api, adminApi, fmtDateTime } from './AnalyticsShared'
import '../styles/Analytics.css'

const STATUS_LABELS = {
  pending: '待生成', running: '生成中', completed: '已完成', failed: '失败',
}
const STATUS_CLASS = {
  pending: 'sev-medium', running: 'sev-low', completed: 'sev-low', failed: 'sev-high',
}

function emptyTemplate() {
  return { name: '', description: '', format: 'pdf', config: '{"indicators":[],"period":"last_30d"}' }
}

/**
 * 报告中心
 * 路由：/statistics-analysis/reports
 */
export default function AnalyticsReports() {
  const [tab, setTab] = useState('runs')
  const [templates, setTemplates] = useState([])
  const [runs, setRuns] = useState([])
  const [indicators, setIndicators] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showTpl, setShowTpl] = useState(false)
  const [tplForm, setTplForm] = useState(emptyTemplate())
  const [triggering, setTriggering] = useState(false)

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const [tplList, runList, indList] = await Promise.all([
        adminApi('/report-templates'),
        adminApi('/reports/runs'),
        api('/indicators'),
      ])
      setTemplates(tplList)
      setRuns(runList)
      setIndicators(indList)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  const saveTemplate = async () => {
    try {
      const body = {
        name: tplForm.name,
        description: tplForm.description,
        format: tplForm.format,
        config: JSON.parse(tplForm.config),
        is_active: true,
      }
      await adminApi('/report-templates', { method: 'POST', body: JSON.stringify(body) })
      setShowTpl(false)
      setTplForm(emptyTemplate())
      loadAll()
    } catch (e) {
      alert(`保存失败：${e.message}`)
    }
  }

  const triggerRun = async (tplId) => {
    setTriggering(true)
    try {
      await adminApi('/reports/run', {
        method: 'POST',
        body: JSON.stringify({ template_id: tplId }),
      })
      loadAll()
    } catch (e) {
      alert(e.message)
    } finally {
      setTriggering(false)
    }
  }

  return (
    <div className="analytics-reports-page">
      <div className="analytics-page-header">
        <h2>报告中心</h2>
        <div className="tabs">
          <Link className="tab" to="/statistics-analysis">仪表盘</Link>
          <Link className="tab" to="/statistics-analysis/rules">研判规则</Link>
          <Link className="tab active" to="/statistics-analysis/reports">报告中心</Link>
        </div>
      </div>

      <div className="analytics-body">
        {error && <div className="a-empty" style={{ color: 'var(--sub-danger)' }}>加载失败：{error}</div>}

        <div className="analytics-panel">
          <h3>
            <button className={`tab ${tab === 'runs' ? 'active' : ''}`} onClick={() => setTab('runs')} style={{ marginRight: 8 }}>生成记录</button>
            <button className={`tab ${tab === 'templates' ? 'active' : ''}`} onClick={() => setTab('templates')}>报告模板</button>
            <div className="panel-tools">
              {tab === 'templates' && <button className="a-btn" onClick={() => setShowTpl(true)}>+ 新建模板</button>}
            </div>
          </h3>

          {loading ? <div className="a-empty">加载中…</div> : tab === 'runs' ? (
            <table className="a-table">
              <thead>
                <tr>
                  <th>编号</th><th>模板</th><th>状态</th><th>周期</th>
                  <th>触发时间</th><th>完成时间</th><th>文件</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td>#{r.id}</td>
                    <td>模板 #{r.template_id}</td>
                    <td><span className={`sev-badge ${STATUS_CLASS[r.status]}`}>{STATUS_LABELS[r.status]}</span></td>
                    <td>{r.period_start ? `${fmtDateTime(r.period_start)} ~ ${fmtDateTime(r.period_end)}` : '——'}</td>
                    <td>{fmtDateTime(r.created_at)}</td>
                    <td>{r.finished_at ? fmtDateTime(r.finished_at) : '——'}</td>
                    <td>
                      {r.file_path ? (
                        <a className="a-btn ghost" href={r.file_path} target="_blank" rel="noopener noreferrer">下载</a>
                      ) : (
                        <span style={{ color: 'var(--sub-muted)' }}>未生成</span>
                      )}
                    </td>
                  </tr>
                ))}
                {!runs.length && <tr><td colSpan={7}><div className="a-empty">暂无生成记录</div></td></tr>}
              </tbody>
            </table>
          ) : (
            <table className="a-table">
              <thead>
                <tr>
                  <th>模板名</th><th>格式</th><th>说明</th><th>创建时间</th><th>操作</th>
                </tr>
              </thead>
              <tbody>
                {templates.map((t) => (
                  <tr key={t.id}>
                    <td>{t.name}</td>
                    <td><span className="mc-tag">{t.format.toUpperCase()}</span></td>
                    <td style={{ color: 'var(--sub-muted)', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.description || '——'}</td>
                    <td>{fmtDateTime(t.created_at)}</td>
                    <td>
                      <button className="a-btn" onClick={() => triggerRun(t.id)} disabled={triggering}>
                        {triggering ? '触发中…' : '立即生成'}
                      </button>
                    </td>
                  </tr>
                ))}
                {!templates.length && <tr><td colSpan={5}><div className="a-empty">暂无模板，点击右上「新建模板」</div></td></tr>}
              </tbody>
            </table>
          )}
        </div>

        {/* 可用指标参考 */}
        <div className="analytics-panel">
          <h3>可用指标（模板配置可引用）</h3>
          <table className="a-table">
            <thead><tr><th>编码</th><th>名称</th><th>类别</th><th>单位</th></tr></thead>
            <tbody>
              {indicators.map((i) => (
                <tr key={i.id}>
                  <td><code style={{ color: 'var(--sub-cyan)' }}>{i.code}</code></td>
                  <td>{i.name}</td>
                  <td>{i.category}</td>
                  <td>{i.unit || '——'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 新建模板模态 */}
      {showTpl && (
        <div className="a-modal-mask" onClick={() => setShowTpl(false)}>
          <div className="a-modal" onClick={(e) => e.stopPropagation()}>
            <h3>新建报告模板</h3>
            <div className="a-form-row">
              <label>模板名称 *</label>
              <input className="a-input" value={tplForm.name} onChange={(e) => setTplForm({ ...tplForm, name: e.target.value })} placeholder="例如：周度运营报告" />
            </div>
            <div className="a-form-row">
              <label>输出格式</label>
              <select className="a-select" value={tplForm.format} onChange={(e) => setTplForm({ ...tplForm, format: e.target.value })}>
                <option value="pdf">PDF</option>
                <option value="excel">Excel</option>
              </select>
            </div>
            <div className="a-form-row">
              <label>说明</label>
              <textarea className="a-textarea" value={tplForm.description} onChange={(e) => setTplForm({ ...tplForm, description: e.target.value })} />
            </div>
            <div className="a-form-row">
              <label>配置（JSON）</label>
              <textarea
                className="a-textarea"
                style={{ minHeight: 120, fontFamily: 'monospace' }}
                value={tplForm.config}
                onChange={(e) => setTplForm({ ...tplForm, config: e.target.value })}
              />
              <small style={{ color: 'var(--sub-muted)' }}>
                {'{ "indicators": ["device_online_rate", "patrol_task_completion_rate"], "period": "last_30d" }'}
              </small>
            </div>
            <div className="a-form-actions">
              <button className="a-btn ghost" onClick={() => setShowTpl(false)}>取消</button>
              <button className="a-btn" onClick={saveTemplate} disabled={!tplForm.name}>保存</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
