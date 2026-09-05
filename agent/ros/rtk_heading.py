"""RTK-only world-yaw alignment. Never rotate body-frame gyro/acceleration."""
import json
import math
import os
import time
import copy
from pathlib import Path

ALIGNED_TOPIC = '/rtk/imu_aligned'
_offset = None
_last_received = 0.0
_error = 'RTK航向尚未标定'


def heading_status():
    return {'ready': _offset is not None and time.monotonic()-_last_received < 1.0,
            'offsetRad': _offset, 'error': _error, 'topic': ALIGNED_TOPIC}


def require_heading():
    if not heading_status()['ready']:
        raise RuntimeError('RTK航向未就绪: ' + (_error or 'IMU数据过期'))


def install_heading(raw_topic):
    import rospy
    from sensor_msgs.msg import Imu
    global _offset, _error
    try:
        _offset = load_alignment(os.environ.get('DWC_RTK_HEADING_FILE',
                                                 str(Path(__file__).resolve().parent / 'rtk' / 'rtk-heading.json')),
                                 Path('/proc/sys/kernel/random/boot_id').read_text().strip())
        _error = ''
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _offset = None
        _error = str(exc)
        rospy.logwarn('RTK heading alignment unavailable: %s', _error)
    publisher = rospy.Publisher(ALIGNED_TOPIC, Imu, queue_size=1)

    def receive(msg):
        global _last_received, _error
        if _offset is None:
            return
        try:
            if msg.orientation_covariance[0] == -1:
                raise ValueError('IMU orientation unavailable')
            q = msg.orientation
            values = rotate_world_yaw((q.x, q.y, q.z, q.w), _offset)
            output = copy.deepcopy(msg)
            output.orientation.x, output.orientation.y, output.orientation.z, output.orientation.w = values
            publisher.publish(output)
            _last_received = time.monotonic()
            _error = ''
        except ValueError as exc:
            _last_received = 0.0
            _error = str(exc)

    return rospy.Subscriber(raw_topic, Imu, receive, queue_size=1)


def load_alignment(path, boot_id):
    data = json.loads(Path(path).read_text())
    if not data.get('persistent', False) and data.get('bootId') != boot_id:
        raise ValueError('航向标定不属于本次开机，请重新标定')
    offset = float(data['offsetRad'])
    if not math.isfinite(offset) or abs(offset) > math.pi:
        raise ValueError('无效的航向标定偏置')
    return offset


def rotate_world_yaw(q, offset):
    x, y, z, w = q
    if not all(math.isfinite(v) for v in (*q, offset)):
        raise ValueError('non-finite IMU orientation')
    norm = math.sqrt(x*x+y*y+z*z+w*w)
    if norm < 1e-9:
        raise ValueError('zero IMU quaternion')
    s, c = math.sin(offset/2), math.cos(offset/2)
    return ((c*x-s*y)/norm, (s*x+c*y)/norm,
            (c*z+s*w)/norm, (c*w-s*z)/norm)
