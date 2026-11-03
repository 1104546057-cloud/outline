import styles from './PlaceholderPage.module.css'
import themeStyles from '../../styles/SubpageTheme.module.css'
import { bindStyles } from '../../utils/bindStyles.js'

const cx = bindStyles(styles, themeStyles)

/**
 * 占位页面 - 尚未开发的功能模块统一使用
 */
function PlaceholderPage({ title, description, icon }) {
  return (
    <div className={cx('placeholder-page')}>
      <div className={cx('placeholder-content')}>
        <div className={cx('placeholder-icon')}>{icon || '🚧'}</div>
        <h2>{title || '功能开发中'}</h2>
        <p>{description || '该功能模块正在开发中，敬请期待...'}</p>
        <div className={cx('placeholder-progress')}>
          <div className={cx('progress-bar')}>
            <div className={cx('progress-fill')}></div>
          </div>
          <span className={cx('progress-text')}>开发进度 0%</span>
        </div>
      </div>
    </div>
  )
}

export default PlaceholderPage
