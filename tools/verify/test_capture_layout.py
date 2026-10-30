"""Targeted checks for capture/trace ownership boundaries; no hardware access."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from sdr.capture_layout import current, validate


class LayoutTest(unittest.TestCase):
    def test_current_layout_and_capture_end(self):
        layout = current()
        self.assertEqual(layout['slot_bytes'], (layout['capture_end'] + 1) * 4)
        self.assertLessEqual(layout['data_end'], layout['trace_address'])

    def test_8192_overlaps_current_trace(self):
        layout = current()
        with self.assertRaisesRegex(ValueError, 'overlaps RF status trace'):
            validate(layout['data_base'], 8192, layout['slots'], 2047,
                     layout['stream_address'], layout['trace_address'], layout['trace_bytes'])

    def test_wrong_rx_capture_end_rejected(self):
        layout = current()
        with self.assertRaisesRegex(ValueError, 'end address disagree'):
            validate(layout['data_base'], 8192, layout['slots'], layout['capture_end'],
                     layout['stream_address'], layout['trace_address'], layout['trace_bytes'])

    def test_nonoverlap_boundary_and_stream_overlap(self):
        validate(0x1000, 512, 2, 127, 0x1800, 0x1400, 512)
        with self.assertRaisesRegex(ValueError, 'stream ownership state'):
            validate(0x1000, 512, 2, 127, 0x13ff)

    def test_relocated_trace_conflicts_with_enabled_diagnostics(self):
        layout = current()
        args = (layout['data_base'], 8192, layout['slots'], 2047,
                layout['stream_address'], 0x8096e000, 512)
        validate(*args)  # Geometry only; this does not prove the region is free.
        for name, size in [('fast tune trace', 128), ('stream timing trace', 288)]:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                validate(*args, reserved=((name, 0x8096e000, size),))
        # The adjacent optional digital profile does not overlap the 512 B range.
        validate(*args, reserved=(('digital profile', 0x8096e200, 64),))


if __name__ == '__main__':
    unittest.main()
