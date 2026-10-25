import unittest
from unittest.mock import patch

from core.local_router import handle_local_request


class LocalRequestTests(unittest.TestCase):
    def test_time_is_local_and_spoken_concisely(self):
        with patch("core.local_router.datetime") as clock:
            clock.now.return_value.astimezone.return_value.strftime.side_effect = [
                "03:07 PM", "Sunday, October", "25"
            ]
            result = handle_local_request("What time is it?")
        self.assertIsNotNone(result)
        self.assertEqual(result.text, "It's 3:07 PM.")

    def test_wake_word_prefix_does_not_force_a_model_request(self):
        with patch("core.local_router.datetime") as clock:
            clock.now.return_value.astimezone.return_value.strftime.return_value = "03:07 PM"
            result = handle_local_request("Hey Jarvis, what time is it?")
        self.assertEqual(result.text, "It's 3:07 PM.")

    def test_date_is_local(self):
        with patch("core.local_router.datetime") as clock:
            clock.now.return_value.astimezone.return_value.strftime.side_effect = [
                "25", "Sunday, October"
            ]
            result = handle_local_request("what's today's date")
        self.assertIsNotNone(result)
        self.assertEqual(result.text, "It's Sunday, October 25.")

    def test_known_app_alias_uses_existing_local_launcher(self):
        with patch("actions.open_app.open_app", return_value="Opened Spotify.") as launch:
            result = handle_local_request("launch Spotify")
        self.assertEqual(result.text, "Opened Spotify.")
        launch.assert_called_once_with({"app_name": "spotify"})

    def test_email_opens_inbox_without_model(self):
        with patch("core.local_router._open_url", return_value=True) as open_url:
            result = handle_local_request("Check my emails")
        self.assertEqual(result.text, "Opening Gmail.")
        open_url.assert_called_once_with("https://mail.google.com/")

    def test_common_and_explicit_websites_open_directly(self):
        with patch("core.local_router._open_url", return_value=True) as open_url:
            common = handle_local_request("open Wikipedia")
            explicit = handle_local_request("go to https://example.org/docs")
        self.assertEqual(common.text, "Opening www.wikipedia.org.")
        self.assertEqual(explicit.text, "Opening example.org.")
        self.assertEqual(open_url.call_count, 2)

    def test_document_open_is_local_and_asks_when_ambiguous(self):
        from pathlib import Path
        with patch("core.local_router._find_document", return_value=([Path("/docs/plan.pdf")], False)), \
             patch("core.local_router._launch_file", return_value=True):
            result = handle_local_request("open plan.pdf")
        self.assertEqual(result.text, "Opening plan.pdf.")

        with patch("core.local_router._find_document", return_value=(
            [Path("/docs/plan.pdf"), Path("/downloads/plan.pdf")], False
        )):
            result = handle_local_request("open plan.pdf")
        self.assertIn("Which one should I open?", result.text)

    def test_open_document_without_name_asks_one_specific_question(self):
        result = handle_local_request("open my document")
        self.assertEqual(result.text, "Which document should I open?")

    def test_unknown_question_is_left_for_gemini(self):
        self.assertIsNone(handle_local_request("Why is the sky blue?"))


if __name__ == "__main__":
    unittest.main()
