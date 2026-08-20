/* eslint-disable react/prop-types */
import { ROBOT_DIRECTIONS } from './robotDirectionPadConfig'
import '../styles/DeviceCockpit.css'

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
    <div className={`cockpit-direction-grid ${className}`.trim()}>
      {ROBOT_DIRECTIONS.map(direction => direction.key === 'stop' ? (
        <button
          key={direction.key}
          type="button"
          className="stop"
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
          className={activeDirection === direction.key ? 'active' : ''}
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
