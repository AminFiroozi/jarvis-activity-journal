import unittest

from src.analysis.report_render import (
    NARRATIVE_MARKER,
    daily_narrative_text,
    read_input_stamp,
    render_report,
    render_sections,
    strip_input_stamp,
    upsert_daily_narrative,
    with_input_stamp,
)

NARRATIVE = {
    "summary": "Worked on the pipeline.",
    "on_screen": ["Kibana dashboard kassa-log", "Terminal running pytest"],
    "timeline": [{"time": "09:15", "activity": "Started coding"}],
    "patterns": ["Steady focus"],
    "next_actions": ["Write tests"],
}


class RenderTests(unittest.TestCase):
    def test_sections_appear_in_the_shared_order(self):
        text = render_report("Hourly journal — 2026-09-26 09:00", NARRATIVE)

        self.assertTrue(text.startswith("# Hourly journal — 2026-09-26 09:00\n\nWorked on the pipeline.\n"))
        order = [text.index(heading) for heading in ("### Timeline", "### Patterns")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("Next actions", text)
        self.assertNotIn("Write tests", text)
        self.assertNotIn("On screen", text)
        self.assertNotIn("Kibana dashboard kassa-log", text)
        self.assertIn("- 09:15 — Started coding", text)

    def test_no_confidence_line_and_no_legacy_sections(self):
        text = render_report("T", {**NARRATIVE, "confidence": 0.9, "accomplishments": ["x"], "blockers": ["y"]})

        self.assertNotIn("confidence", text.lower())
        self.assertNotIn("Accomplishments", text)
        self.assertNotIn("Blockers", text)
        self.assertNotIn("Next actions", text)

    def test_empty_sections_are_omitted(self):
        text = render_report("T", {"summary": "Quiet."})

        self.assertNotIn("###", text)

    def test_bare_string_sections_and_string_timeline_entries_are_tolerated(self):
        text = render_report("T", {"summary": "s", "on_screen": "One screen", "timeline": ["10:00 something"], "patterns": None})

        self.assertNotIn("One screen", text)
        self.assertIn("- 10:00 something", text)
        self.assertNotIn("### Patterns", text)


    def test_null_time_or_activity_never_renders_as_none(self):
        text = render_report("T", {"summary": "s", "timeline": [{"time": None, "activity": "did x"}, {"time": "10:00", "activity": None}]})

        self.assertIn("- did x", text)
        self.assertIn("- 10:00", text)
        self.assertNotIn("None", text)


class DailyTests(unittest.TestCase):
    def test_upsert_keeps_the_scaffold_and_replaces_the_previous_narrative(self):
        scaffold = "# Automatic Activity Journal — 2026-09-26\n\n## Applications\n\n- Code\n"
        first = upsert_daily_narrative(scaffold, {"summary": "First."})
        second = upsert_daily_narrative(first, NARRATIVE)

        self.assertIn("## Applications", second)
        self.assertEqual(second.count(NARRATIVE_MARKER), 1)
        self.assertIn("Worked on the pipeline.", second)
        self.assertNotIn("First.", second)

    def test_daily_narrative_text_returns_body_without_marker_or_stamp(self):
        markdown = with_input_stamp(upsert_daily_narrative("# D\n", NARRATIVE), "abc123")

        body = daily_narrative_text(markdown)

        self.assertTrue(body.startswith("Worked on the pipeline."))
        self.assertNotIn(NARRATIVE_MARKER, body)
        self.assertNotIn("<!--", body)

    def test_daily_without_marker_has_no_narrative(self):
        self.assertIsNone(daily_narrative_text("# Automatic Activity Journal — 2026-09-26\n"))


class StampTests(unittest.TestCase):
    def test_stamp_round_trip(self):
        stamped = with_input_stamp("# T\n\nBody.\n", "deadbeef0123")

        self.assertEqual(read_input_stamp(stamped), "deadbeef0123")
        self.assertEqual(strip_input_stamp(stamped), "# T\n\nBody.\n")

    def test_restamping_replaces_the_old_stamp(self):
        once = with_input_stamp("# T\n", "aaaa")
        twice = with_input_stamp(once, "bbbb")

        self.assertEqual(read_input_stamp(twice), "bbbb")
        self.assertEqual(twice.count("<!--"), 1)

    def test_no_stamp_reads_as_none(self):
        self.assertIsNone(read_input_stamp("# T\n"))


if __name__ == "__main__":
    unittest.main()
