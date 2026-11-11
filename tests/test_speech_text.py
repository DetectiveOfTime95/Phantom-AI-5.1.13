import unittest

from actions.speech_text import clean_for_speech


class SpeechTextTests(unittest.TestCase):
    def test_removes_asterisks_but_keeps_words(self):
        self.assertEqual(clean_for_speech("**Hello, sir.** Use *bold* formatting."), "Hello, sir. Use bold formatting.")

    def test_removes_emoji(self):
        self.assertEqual(clean_for_speech("System ready 🚀 ✅. Hello 👋"), "System ready. Hello")

    def test_keeps_link_label_and_removes_url(self):
        self.assertEqual(clean_for_speech("Visit [Phantom Softworks](https://example.com) now."), "Visit Phantom Softworks now.")

    def test_strips_heading_and_bullet_markers(self):
        self.assertEqual(clean_for_speech("# Status\n- All systems ready\n* Voice online"), "Status. All systems ready. Voice online")

    def test_multiplication_is_spoken_naturally(self):
        self.assertEqual(clean_for_speech("4 * 5 = 20"), "4 times 5 = 20")

    def test_code_block_is_not_read_as_punctuation(self):
        self.assertEqual(clean_for_speech("Run this:\n```js\nconst x = 1;\n```"), "Run this. Code is displayed on screen.")

    def test_empty_and_emoji_only(self):
        self.assertEqual(clean_for_speech("   "), "")
        self.assertEqual(clean_for_speech("🚀✅"), "")


if __name__ == "__main__":
    unittest.main()
