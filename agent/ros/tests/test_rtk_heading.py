import json
import math
import tempfile
import unittest
from pathlib import Path
from rtk_heading import load_alignment, rotate_world_yaw


class HeadingTests(unittest.TestCase):
    def test_recorded_course_matches_after_offset(self):
        for course, raw in [(166.6,-22.5),(162.3,-21.4),(154.5,-31.3),(145.4,-41.7),(135.5,-51.6)]:
            y=math.radians(raw)
            x,b,z,w=rotate_world_yaw((0,0,math.sin(y/2),math.cos(y/2)),math.radians(-173.4))
            corrected=math.degrees(math.atan2(2*w*z,1-2*z*z))
            error=abs((corrected-course+180)%360-180)
            self.assertLess(error,4)

    def test_invalid_quaternion(self):
        for q in [(0,0,0,0),(0,0,float('nan'),1)]:
            with self.assertRaises(ValueError):rotate_world_yaw(q,0)

    def test_calibration_does_not_survive_boot_change(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'heading.json';p.write_text(json.dumps({'bootId':'old','offsetRad':1.0}))
            self.assertEqual(load_alignment(p,'old'),1.0)

    def test_persistent_baseline_survives_boot_change(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'heading.json';p.write_text(json.dumps({'persistent':True,'bootId':'old','offsetRad':1.0}))
            self.assertEqual(load_alignment(p,'new'),1.0)

    def test_identity_preserves_roll_pitch(self):
        q=(.1,.2,.3,.9);n=math.sqrt(sum(v*v for v in q))
        for a,b in zip(rotate_world_yaw(q,0),q):self.assertAlmostEqual(a,b/n)
