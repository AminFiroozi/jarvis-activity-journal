import unittest

from src.analysis.sessionize import detect_sessions


def event(event_id, minute, **values):
    return {
        "id": event_id,
        "observedAt": f"2026-08-23T10:{minute:02d}:00+00:00",
        **values,
    }


class SessionizeTests(unittest.TestCase):
    def test_groups_adjacent_compatible_events_and_preserves_source_ids(self):
        sessions = detect_sessions(
            [
                event("e2", 8, source="foreground-window", process="Code", project="jarvis"),
                event("e1", 0, source="foreground-window", process="Code", project="jarvis"),
            ]
        )

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["startAt"], "2026-08-23T10:00:00+00:00")
        self.assertEqual(sessions[0]["endAt"], "2026-08-23T10:08:00+00:00")
        self.assertEqual(sessions[0]["eventIds"], ["e1", "e2"])
        self.assertEqual(sessions[0]["classification"], "coding")
        self.assertGreater(sessions[0]["confidence"], 0)

    def test_gap_of_fifteen_minutes_starts_a_new_session(self):
        sessions = detect_sessions(
            [
                event("e1", 0, process="Code"),
                event("e2", 15, process="Code"),
            ]
        )

        self.assertEqual(len(sessions), 2)

    def test_idle_event_splits_active_work_and_is_classified_idle(self):
        sessions = detect_sessions(
            [
                event("e1", 0, process="Code", active=True),
                event("e2", 5, process="Code", active=False, idleSeconds=600),
                event("e3", 8, process="Code", active=True),
            ]
        )

        self.assertEqual([session["classification"] for session in sessions], ["coding", "idle", "coding"])
        self.assertEqual(sessions[1]["eventIds"], ["e2"])

    def test_different_projects_split_even_when_application_is_the_same(self):
        sessions = detect_sessions(
            [
                event("e1", 0, process="Code", project="alpha"),
                event("e2", 4, process="Code", project="beta"),
            ]
        )

        self.assertEqual(len(sessions), 2)

    def test_ide_and_integrated_terminal_stay_together_for_same_project(self):
        sessions = detect_sessions(
            [
                event("e1", 0, application="Visual Studio Code", projectPath="jarvis"),
                event("e2", 3, application="PowerShell", projectPath="jarvis"),
            ]
        )

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["classification"], "coding")

    def test_different_activity_classes_split_when_context_is_incompatible(self):
        sessions = detect_sessions(
            [
                event("e1", 0, application="Visual Studio Code", project="jarvis"),
                event("e2", 3, application="Chrome", project="jarvis"),
            ]
        )

        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[1]["classification"], "browsing")

    def test_classifies_supported_activity_types_from_explicit_evidence(self):
        cases = {
            "coding": {"activity_type": "coding"},
            "browsing": {"activity_type": "browsing"},
            "communication": {"activity_type": "chatting"},
            "terminal": {"application": "PowerShell"},
            "meeting": {"activity_type": "meeting"},
        }

        for expected, evidence in cases.items():
            with self.subTest(expected=expected):
                result = detect_sessions([event("e1", 0, **evidence)])[0]
                self.assertEqual(result["classification"], expected)

    def test_uses_nested_visual_analysis_evidence(self):
        sessions = detect_sessions(
            [event("e1", 0, source="screenshot-vision", analysis={"activity_type": "browsing"})]
        )

        self.assertEqual(sessions[0]["classification"], "browsing")

    def test_mixed_is_used_for_unrelated_evidence_that_can_share_a_session(self):
        sessions = detect_sessions(
            [
                event("e1", 0, source="activity", process="Workspace", activity_type="coding"),
                event("e2", 3, source="activity", process="Workspace", activity_type="meeting"),
            ]
        )

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["classification"], "mixed")

    def test_empty_input_is_empty_and_missing_ids_use_stable_fallback(self):
        self.assertEqual(detect_sessions([]), [])
        sessions = detect_sessions([event("", 0, process="Code")])
        self.assertEqual(sessions[0]["eventIds"], ["event-1"])


if __name__ == "__main__":
    unittest.main()
