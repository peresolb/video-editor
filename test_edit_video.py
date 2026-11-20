"""Unit tests for the timeline logic in edit_video."""

import unittest

from edit_video import ConfigError, build_filter, build_segments, parse_time


class ParseTimeTest(unittest.TestCase):
    def test_formats(self) -> None:
        self.assertEqual(parse_time(95, 100), 95.0)
        self.assertEqual(parse_time("1:35", 100), 95.0)
        self.assertEqual(parse_time("0:01:35.5", 100), 95.5)
        self.assertEqual(parse_time("end", 100), 100.0)
        self.assertEqual(parse_time("start", 100), 0.0)

    def test_invalid(self) -> None:
        with self.assertRaises(ConfigError):
            parse_time("soon", 100)


class BuildSegmentsTest(unittest.TestCase):
    def test_no_edits_gives_one_segment(self) -> None:
        segments = build_segments([], 100)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].duration, 100)

    def test_speed_and_pause(self) -> None:
        edits = [
            {"action": "pause", "at": 80, "seconds": 30},
            {"action": "speed", "from": 20, "to": 60, "factor": 20},
        ]
        segments = build_segments(edits, 100)
        durations = [s.duration for s in segments]
        self.assertEqual(durations, [20, 2, 20, 30, 20])

    def test_pause_inside_speed_interval(self) -> None:
        edits = [
            {"action": "speed", "from": 0, "to": 40, "factor": 10},
            {"action": "pause", "at": 20, "seconds": 5},
        ]
        segments = build_segments(edits, 100)
        self.assertEqual([s.duration for s in segments], [2, 5, 2, 60])
        self.assertEqual([s.factor for s in segments], [10, 1, 10, 1])

    def test_pause_at_start_and_end(self) -> None:
        edits = [
            {"action": "pause", "at": "start", "seconds": 3},
            {"action": "pause", "at": "end", "seconds": 4},
        ]
        segments = build_segments(edits, 100)
        self.assertEqual([s.duration for s in segments], [3, 100, 4])

    def test_overlap_is_an_error(self) -> None:
        edits = [
            {"action": "speed", "from": 0, "to": 40, "factor": 10},
            {"action": "speed", "from": 30, "to": 50, "factor": 10},
        ]
        with self.assertRaises(ConfigError):
            build_segments(edits, 100)

    def test_cut_removes_the_interval(self) -> None:
        edits = [
            {"action": "cut", "from": 20, "to": 60},
            {"action": "pause", "at": 60, "seconds": 5},
        ]
        segments = build_segments(edits, 100)
        self.assertEqual([s.duration for s in segments], [20, 0, 5, 40])
        self.assertEqual([s.cut for s in segments], [False, True, False, False])

    def test_cut_that_overlaps_speed_is_an_error(self) -> None:
        edits = [
            {"action": "speed", "from": 0, "to": 40, "factor": 10},
            {"action": "cut", "from": 30, "to": 50},
        ]
        with self.assertRaises(ConfigError):
            build_segments(edits, 100)

    def test_pause_inside_cut_is_an_error(self) -> None:
        edits = [
            {"action": "cut", "from": 20, "to": 60},
            {"action": "pause", "at": 30, "seconds": 5},
        ]
        with self.assertRaises(ConfigError):
            build_segments(edits, 100)

    def test_missing_field_is_an_error(self) -> None:
        with self.assertRaises(ConfigError):
            build_segments([{"action": "pause", "at": 5}], 100)


class BuildFilterTest(unittest.TestCase):
    def test_audio_is_silent_in_changed_segments(self) -> None:
        edits = [{"action": "speed", "from": 20, "to": 60, "factor": 20}]
        graph = build_filter(build_segments(edits, 100), 30, 100, has_audio=True)
        self.assertIn("asplit=2", graph)
        self.assertEqual(graph.count("anullsrc"), 1)
        self.assertIn("concat=n=3:v=1:a=1", graph)


if __name__ == "__main__":
    unittest.main()
