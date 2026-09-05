"""RTK-only velocity bounds. Stop and output publication share one lock."""
import math
import threading
import time


RAW_TOPIC = "/rtk/nav_cmd_vel"


class RtkVelocityGuard:
    def __init__(self, publish, clock=time.monotonic):
        self.publish = publish
        self.clock = clock
        self.lock = threading.RLock()
        self.enabled = False
        self.last_time = None
        self.angular = 0.0
        self.timeout = 0.5
        self.angular_rate = 0.4
        self.radius = 1.78

    def arm(self):
        with self.lock:
            if not self.enabled:
                self.angular = 0.0
                self.last_time = None
                self.enabled = True

    def stop(self):
        with self.lock:
            self.enabled = False
            self.angular = 0.0
            self.last_time = None
            self.publish(0.0, 0.0)

    def check_timeout(self):
        with self.lock:
            if (self.enabled and self.last_time is not None
                    and self.clock() - self.last_time > self.timeout):
                self.stop()

    def command(self, linear, angular):
        with self.lock:
            if not self.enabled:
                return
            now = self.clock()
            if (not all(math.isfinite(x) for x in (linear, angular))
                    or (self.last_time is not None and now - self.last_time > self.timeout)):
                self.stop()
                return
            elapsed = 0.125 if self.last_time is None else max(0.0, min(now - self.last_time, 0.125))
            self.last_time = now
            # A stationary Ackermann vehicle cannot execute a yaw-rate command.
            # Planner zeros bypass smoothing but do not cancel an active goal.
            if linear == 0.0:
                self.angular = 0.0
                self.publish(0.0, 0.0)
                return
            linear = max(-0.08, min(0.20, linear))
            bound = min(0.11236, abs(linear) / self.radius)
            target = max(-bound, min(bound, angular))
            delta = self.angular_rate * elapsed
            output = max(self.angular - delta, min(self.angular + delta, target))
            # Curvature safety takes priority when forward speed drops abruptly.
            self.angular = max(-bound, min(bound, output))
            self.publish(linear, self.angular)
