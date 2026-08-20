export const ROBOT_DIRECTIONS = [
  { key: 'forward-left', icon: '↖', label: '左前' },
  { key: 'forward', icon: '↑', label: '前进' },
  { key: 'forward-right', icon: '↗', label: '右前' },
  { key: 'left', icon: '←', label: '左转' },
  { key: 'stop', icon: '■', label: '停止' },
  { key: 'right', icon: '→', label: '右转' },
  { key: 'backward-left', icon: '↙', label: '左后' },
  { key: 'backward', icon: '↓', label: '后退' },
  { key: 'backward-right', icon: '↘', label: '右后' },
]

export const ROBOT_DIRECTION_KEY_MAP = {
  ArrowUp: 'forward', KeyW: 'forward', Numpad8: 'forward',
  ArrowDown: 'backward', KeyS: 'backward', Numpad2: 'backward',
  ArrowLeft: 'left', KeyA: 'left', Numpad4: 'left',
  ArrowRight: 'right', KeyD: 'right', Numpad6: 'right',
  Numpad7: 'forward-left', Numpad9: 'forward-right',
  Numpad1: 'backward-left', Numpad3: 'backward-right',
  Space: 'stop', Numpad5: 'stop',
}

export function getRobotDirectionValues(direction, maxLinear, maxAngular) {
  switch (direction) {
    case 'forward': return { linear: maxLinear, angular: 0 }
    case 'backward': return { linear: -maxLinear, angular: 0 }
    case 'left': return { linear: 0, angular: maxAngular }
    case 'right': return { linear: 0, angular: -maxAngular }
    case 'forward-left': return { linear: maxLinear, angular: maxAngular * .5 }
    case 'forward-right': return { linear: maxLinear, angular: -maxAngular * .5 }
    case 'backward-left': return { linear: -maxLinear, angular: maxAngular * .5 }
    case 'backward-right': return { linear: -maxLinear, angular: -maxAngular * .5 }
    default: return { linear: 0, angular: 0 }
  }
}
