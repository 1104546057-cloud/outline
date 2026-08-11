import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { api, adminApi, CATEGORY_LABELS } from './AnalyticsShared'
import '../styles/Analytics.css'

const RULE_TYPES = {
  threshold: '阈值越界',
  zscore: '基线偏离 (Z-Score)',
  consecutive: '连续异常',
  ratio: '比率对比',
}

const SEVERITIES = ['low', 'medium', 'high', 'critical']
const SEV_LABELS = { low: '低', medium: '中', high: '高', critical: '紧急' }

function emptyForm() {
  return {
    name: '',
    indicator_id: '',
    rule_type: 'threshold',
    condition: '{"op":"<","value":0}',
    severity: 'medium',
    alert_type: 'analytics_rule',
    description: '',
    is_active: true,
  }
}

/**
 * 研判规则配置页
 * 路由：/statistics-analysis/rules
 */
export default function AnalyticsRules() {
  const [rules, setRules] = useState([])
  const [indicators, setIndicators] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null) // null | 'new' | rule对象
  const [form, setForm] = useState(emptyForm())
  const [saving, setSaving] = useState(false)

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const [ruleList, indList] = await Promise.all([
        adminApi('/rules'),
        api('/indicators'),
      ])
      setRules(ruleList)
      setIndicators(indList)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  const openNew = () => {
    setForm(emptyForm())
    setEditing('new')
  }
  const openEdit = (rule) => {
    setForm({
      ...rule,
      indicator_id: rule.indicator_id,
      condition: JSON.stringify(rule.condition || {}, null, 2),
      is_active: rule.is_active,
    })
    setEditing(rule.id)
  }
  const close = () => setEditing(null)

  const save = async () => {
    setSaving(true)
    try {
      const body = {
        name: form.name,
        indicator_id: Number(form.indicator_id),
        rule_type: form.rule_type,
        condition: JSON.parse(form.condition),
        severity: form.severity,
        alert_type: form.alert_type,
        description: form.description,
        is_active: form.is_active,
      }
      if (editing === 'new') {
        await adminApi('/rules', { method: 'POST', body: JSON.stringify(body) })
      } else {
        await adminApi(`/rules/${editing}`, { method: 'PUT', body: JSON.stringify(body) })
      }
      close()
      loadAll()
    } catch (e) {
      alert(`保存失败：${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  const toggle = async (rule) => {
    try {
      await adminApi(`/rules/${rule.id}`, {
        method: 'PUT',
        body: JSON.stringify({ is_active: !rule.is_active }),
      })
      loadAll()
    } catch (e) { alert(e.message) }
  }

  const remove = async (rule) => {
    if (!confirm(`确认删除规则「${rule.name}」？`)) return
    try {
      await adminApi(`/rules/${rule.id}`, { method: 'DELETE' })
      loadAll()
    } catch (e) { alert(e.message) }
  }

  return (
    <div className="analytics-rules-page">
      <div className="analytics-page-header">
        <h2>研判规则配置</h2>
        <div className="tabs">
          <Link className="tab" to="/statistics-analysis">仪表盘</Link>
          <Link className="tab active" to="/statistics-analysis/rules">研判规则</Link>
          <Link className="tab" to="/statistics-analysis/reports">报告中心</Link>
        </div>
      </div>

      <div className="analytics-body">
        <div className="analytics-panel">
          <h3>
            规则列表
            <div className="panel-tools">
              <button className="a-btn" onClick={openNew}>+ 新建规则</button>
            </div>
          </h3>
          {error && <div className="a-empty" style={{ color: 'var(--sub-danger)' }}>加载失败：{error}</div>}
          {loading ? <div className="a-empty">加载中…</div> : (
            <table className="a-table">
              <thead>
                <tr>
                  <th>名称</th><th>指标</th><th>类型</th><th>严重度</th>
                  <th>状态</th><th>说明</th><th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id}>
                    <td>{r.name}</td>
                    <td>{r.indicator_code || r.indicator_id}</td>
                    <td>{RULE_TYPES[r.rule_type] || r.rule_type}</td>
                    <td><span className={`sev-badge sev-${r.severity}`}>{SEV_LABELS[r.severity]}</span></td>
                    <td>
                      <span style={{ color: r.is_active ? 'var(--sub-success)' : 'var(--sub-muted)' }}>
                        {r.is_active ? '启用' : '停用'}
                      </span>
                    </td>
                    <td style={{ color: 'var(--sub-muted)', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.description || '——'}</td>
                    <td>
                      <button className="a-btn ghost" style={{ marginRight: 6 }} onClick={() => openEdit(r)}>编辑</button>
                      <button className="a-btn ghost" style={{ marginRight: 6 }} onClick={() => toggle(r)}>{r.is_active ? '停用' : '启用'}</button>
                      <button className="a-btn danger" onClick={() => remove(r)}>删除</button>
                    </td>
                  </tr>
                ))}
                {!rules.length && (
                  <tr><td colSpan={7}><div className="a-empty">暂无规则，点击右上「新建规则」开始</div></td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* 指标参考 */}
        <div className="analytics-panel">
          <h3>可用指标</h3>
          <table className="a-table">
            <thead><tr><th>编码</th><th>名称</th><th>类别</th><th>单位</th><th>粒度</th></tr></thead>
            <tbody>
              {indicators.map((i) => (
                <tr key={i.id}>
                  <td><code style={{ color: 'var(--sub-cyan)' }}>{i.code}</code></td>
                  <td>{i.name}</td>
                  <td>{CATEGORY_LABELS[i.category] || i.category}</td>
                  <td>{i.unit || '——'}</td>
                  <td>{i.granularity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 编辑模态 */}
      {editing !== null && (
        <div className="a-modal-mask" onClick={close}>
          <div className="a-modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editing === 'new' ? '新建研判规则' : '编辑规则'}</h3>

            <div className="a-form-row">
              <label>规则名称 *</label>
              <input className="a-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="例如：低电量预警" />
            </div>

            <div className="a-form-row">
              <label>关联指标 *</label>
              <select className="a-select" value={form.indicator_id} onChange={(e) => setForm({ ...form, indicator_id: e.target.value })}>
                <option value="">请选择…</option>
                {indicators.map((i) => (
                  <option key={i.id} value={i.id}>{i.name} ({i.code})</option>
                ))}
              </select>
            </div>

            <div className="a-form-row">
              <label>规则类型</label>
              <select className="a-select" value={form.rule_type} onChange={(e) => setForm({ ...form, rule_type: e.target.value })}>
                {Object.entries(RULE_TYPES).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>

            <div className="a-form-row">
              <label>触发条件（JSON）</label>
              <textarea
                className="a-textarea"
                value={form.condition}
                onChange={(e) => setForm({ ...form, condition: e.target.value })}
                placeholder='{"op":"<","value":0}'
              />
              <small style={{ color: 'var(--sub-muted)' }}>
                threshold: op + value + window_days（天）；
                zscore: z_threshold + window_days；
                consecutive: op + value + consecutive_days；
                ratio: drop_pct / rise_pct + window_days
              </small>
            </div>

            <div className="a-form-row">
              <label>告警严重度</label>
              <select className="a-select" value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
                {SEVERITIES.map((s) => <option key={s} value={s}>{SEV_LABELS[s]}</option>)}
              </select>
            </div>

            <div className="a-form-row">
              <label>告警类型标识</label>
              <input className="a-input" value={form.alert_type} onChange={(e) => setForm({ ...form, alert_type: e.target.value })} placeholder="analytics_rule" />
            </div>

            <div className="a-form-row">
              <label>说明</label>
              <textarea className="a-textarea" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>

            <div className="a-form-row">
              <label>
                <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} style={{ marginRight: 6 }} />
                启用此规则
              </label>
            </div>

            <div className="a-form-actions">
              <button className="a-btn ghost" onClick={close}>取消</button>
              <button className="a-btn" onClick={save} disabled={saving || !form.name || !form.indicator_id}>
                {saving ? '保存中…' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
