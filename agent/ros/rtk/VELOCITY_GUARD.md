# RTK automatic velocity guard

The RTK launch remaps move_base output to `/rtk/nav_cmd_vel`. The existing
robot control Agent subscribes and publishes guarded velocities to `/cmd_vel`.
Deploy the launch, Agent and `rtk_velocity_guard.py` together. No extra ROS
executable or package is required. Indoor navigation launch is unchanged.

Current limits are 0.40 m/s forward, 0.15 m/s backward, angular
speed at most `abs(v)/1.78`, capped at 0.22472 rad/s, and angular change rate
0.4 rad/s². These are bounds, not an anti-reversing controller. A sudden speed
reduction prioritizes curvature over slew. No low-pass filter is added.

The guard is armed on an explicit RTK goal; successive waypoints preserve its
state. Cancel, hard stop and manual takeover disable it. Stop publication and
automatic callbacks share a lock, so queued automatic callbacks cannot publish
motion after a stop until rearmed. Planner zero is sent immediately and resets
slew state. A moving stream gap over 0.5 s stops and disables automatic output;
the Agent's wall-clock watchdog checks every 50 ms. First-plan computation is
allowed to take longer because no motion has yet been emitted. This is a
software zero-command guarantee, not a claim of zero physical braking distance.

The existing RTK quality and route-deviation protections are unchanged.

## Recorded replay, 2026-09-05

Fixture `tests/fixtures/rtk_sway_commands.json` contains 798 `/cmd_vel` records
from `/tmp/rtk-sway-1788598451/drive.bag`, filtered to Unix time
1788598487.32–1788598587.58 (automatic route only; excludes manual driving).
It contains timestamps and velocities only, no location data.

Replay leaves linear speed and all zeros unchanged. Maximum absolute angular
speed drops from 0.21287 to 0.11236 rad/s. Angular total variation drops from
21.7452 to 18.1100 rad/s (16.7%). Sign changes outside a ±0.03 rad/s deadband
only drop from 77 to 75. The largest input gap is 0.2624 s, below the watchdog.
Therefore replay demonstrates bounded commands, not solved oscillation.
The earlier measured command-to-IMU peak correlation lag was about 0.475 s;
additional smoothing must be assessed for added closed-loop delay outdoors.

Run tests from repository root with `PYTHONPATH=agent/ros` and
`python -m unittest discover -s agent/ros/tests -p 'test_rtk*.py'`.
After deployment, verify the raw-topic subscriber, final `/cmd_vel` publisher,
idle zero state and stop behavior before a user-driven outdoor validation.
Capture raw command, final command, IMU, odometry and route error together.
