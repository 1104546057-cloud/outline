/* eslint-disable react/prop-types */
import styles from './RobotDirectionPad.module.css'
import themeStyles from '../../styles/SubpageTheme.module.css'
import { bindStyles } from '../../utils/bindStyles.js'
import { ROBOT_DIRECTIONS } from '../robotDirectionPadConfig'

const cx = bindStyles(styles, themeStyles)

export default function RobotDirectionPad({
  activeDirection,
  movementDisabled,
  stopDisabled,
  onStart,
  onStop,
  onEmergencyStop,
  className = '',
}) {
  return (
    <div className={cx(`cockpit-direction-grid ${className}`.trim())}>
      {ROBOT_DIRECTIONS.map(direction => direction.key === 'stop' ? (
        <button
          key={direction.key}
          type="button"
          className={cx('stop')}
          onClick={onEmergencyStop}
          disabled={stopDisabled}
          title={direction.label}
        >
          <span>{direction.icon}</span><small>{direction.label}</small>
        </button>
      ) : (
        <button
          key={direction.key}
          type="button"
          className={cx(activeDirection === direction.key ? 'active' : '')}
          onPointerDown={() => onStart(direction.key)}
          onPointerUp={onStop}
          onPointerCancel={onStop}
          onPointerLeave={onStop}
          disabled={movementDisabled}
          title={direction.label}
        >
          <span>{direction.icon}</span><small>{direction.label}</small>
        </button>
      ))}
    </div>
  )
}
