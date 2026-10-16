"""Identity and capability prompt checks without running models."""
from pathlib import Path
import os
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("SPEAKRAIL_TOKENIZER_DIR", str(ROOT / "mac/tokenizer"))
sys.path.insert(0, str(ROOT / "app"))
from session import MicroCfg, MicroSession


class AstraTests(unittest.TestCase):
    def prompt(self, persona="astra", search="off", rules=""):
        session = MicroSession.__new__(MicroSession)
        session.m = MicroCfg(persona=persona, tools=False)
        session.cfg = SimpleNamespace(search=search)
        session.user_rules = rules
        return session._system_text()

    def test_trial_identity_and_capabilities(self):
        text = self.prompt()
        self.assertTrue(text.startswith("You are Astra,"))
        self.assertNotIn("Nova", text)
        self.assertNotIn("You can search the web", text)
        self.assertIn("Web search is unavailable", text)

    def test_reset_rules_preserve_identity(self):
        self.assertTrue(self.prompt(rules="Be brief").startswith("You are Astra,"))

    def test_existing_persona_still_available(self):
        text = self.prompt(persona="nova", search="brave")
        self.assertTrue(text.startswith("You are Nova,"))
        self.assertIn("You can search the web", text)


class ConversationOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_undeclared_tool_calls_are_also_blocked(self):
        session = MicroSession.__new__(MicroSession)
        session.m = MicroCfg(persona="astra", tools=False)
        session.cfg = SimpleNamespace(search="off")
        session.claude = session.frontier = None
        session._line = lambda message: None
        reply = SimpleNamespace(turn=SimpleNamespace(id=0))
        for name in ("web_search", "record_note", "reset_chat", "claude_code", "ask_frontier"):
            with self.subTest(name=name):
                self.assertEqual(await session._run_tool(reply, name, {}), {"status": "unavailable"})


if __name__ == "__main__":
    unittest.main()
