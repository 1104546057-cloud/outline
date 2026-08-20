/* eslint-disable react/prop-types */
import './ui.css'

/**
 * 通用面板容器
 *
 * 用法：
 * <Panel title="设备列表" code="DEVICE LIST" meta="12 台" onMetaClick={...}>
 *   内容...
 * </Panel>
 */
export default function Panel({ title, code, meta, onMetaClick, actions, className = '', children }) {
  return (
    <section className={`ui-panel ${className}`}>
      {(title || code || meta || actions) && (
        <header className="ui-panel-heading">
          <div className="ui-panel-heading-left">
            <span className="ui-panel-title-mark" />
            {title && <h2>{title}</h2>}
            {code && <small className="ui-panel-code">{code}</small>}
          </div>
          <div className="ui-panel-heading-right">
            {actions}
            {meta && (
              <span
                className={`ui-panel-meta${onMetaClick ? ' ui-panel-meta-clickable' : ''}`}
                onClick={onMetaClick}
                role={onMetaClick ? 'button' : undefined}
                tabIndex={onMetaClick ? 0 : undefined}
                onKeyDown={onMetaClick ? e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onMetaClick() } } : undefined}
              >
                {meta}
              </span>
            )}
          </div>
        </header>
      )}
      <div className="ui-panel-content">{children}</div>
    </section>
  )
}
