import '../styles/Placeholder.css'

/**
 * 占位页面 - 尚未开发的功能模块统一使用
 */
function PlaceholderPage({ title, description, icon }) {
  return (
    <div className="placeholder-page">
      <div className="placeholder-content">
        <div className="placeholder-icon">{icon || '🚧'}</div>
        <h2>{title || '功能开发中'}</h2>
        <p>{description || '该功能模块正在开发中，敬请期待...'}</p>
        <div className="placeholder-progress">
          <div className="progress-bar">
            <div className="progress-fill"></div>
          </div>
          <span className="progress-text">开发进度 0%</span>
        </div>
      </div>
    </div>
  )
}

export default PlaceholderPage
