# RTK world heading alignment

The September 5 run4 bag showed GPS forward travel bearings roughly 173 degrees
away from the IMU quaternion yaw. This is evidence of a world-heading offset for
that run, not proof of a permanent mounting angle or a sensor-wide calibration.

The Agent publishes `/rtk/imu_aligned` for RTK navigation only. It left-multiplies
orientation by a world-Z rotation, preserving timestamps, frame IDs, body-frame
angular velocity and acceleration. Global EKF and navsat consume the same aligned
orientation. Raw `/imu` and local odometry consumers are unchanged. Keep navsat
`yaw_offset` at zero to avoid applying the offset twice.

Before restarting the Agent, create the calibration JSON specified by
`DWC_RTK_HEADING_FILE` (default `/tmp/rtk-heading.json`): `bootId` must match
`/proc/sys/kernel/random/boot_id`, and `offsetRad` must be finite and within pi.
Do not copy a previous boot's calibration. Missing, stale or invalid calibration
blocks RTK navigation startup; manual control remains available.

Estimate offset from fresh Fixed GPS displacement during supervised forward
travel, paired with IMU yaw. Exclude reverse motion, stops, short displacement,
sharp turns and GNSS jumps. Compare on an independent straight segment before
normal navigation. `-173.4 degrees` was a provisional fit to run4 only, with less
than 4 degrees residual on the five fitted windows; this is not an independent
field validation and must not be made a fleet-wide default. Recalibrate after an
IMU reset/reinitialization even if the computer boot ID did not change.

Read `/api/navigation/rtk/status` -> `response.heading` to check readiness and the
applied offset. Deploy `rtk_heading.py` alongside `robot_control_server.py`.
Do not use goal-yaw changes or reverse-speed limits to compensate for misaligned
localization. This correction does not itself forbid reverse planning.
