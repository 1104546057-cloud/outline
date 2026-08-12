/* eslint-disable react/prop-types */
import './ui.css'

/**
 * 页面标题区
 *
 * 用法：
 * <PageHeader title="设备管理" subtitle="共 N 台设备" code="DEVICE MANAGEMENT">
 *   <button className="btn-primary">新建</button>
 * </PageHeader>
 */
export default function PageHeader({ title, subtitle, code = 'SYSTEM MODULE', actions, children }) {
  return (
    <header className="ui-page-header">
      <div className="ui-page-header-left">
        <div className="ui-page-header-text">
          <h1>{title}</h1>
          {code && <small className="ui-page-header-code">{code}</small>}
        </div>
        {subtitle && <p className="ui-page-header-subtitle">{subtitle}</p>}
      </div>
      {(actions || children) && <div className="ui-page-header-actions">{actions || children}</div>}
    </header>
  )
}
