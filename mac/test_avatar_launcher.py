"""Check public launcher defaults without loading models."""
import unittest
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, Mock, patch

import local_stack
import test_speech


class AvatarLauncherTests(unittest.IsolatedAsyncioTestCase):
    async def launch(self, **options):
        services = Mock()
        with patch.object(local_stack, 'start_asr', AsyncMock(return_value=(10001, None))), \
                patch.object(local_stack, 'start_tts', AsyncMock(return_value=(10002, None))), \
                patch.object(local_stack, 'free_port', return_value=10003), \
                patch.object(local_stack, 'ready', AsyncMock()):
            await local_stack.start_stack(services, 0, **options)
        calls = [call for call in services.start.call_args_list if call.args[0] == 'voice-ui']
        self.assertEqual(len(calls), 1)
        self.environment = calls[0].kwargs['extra_env']
        self.private_log = calls[0].kwargs['private_log']
        return calls[0].args[1]

    async def test_astra_default_keeps_local_tools_but_disables_background_notes(self):
        command = await self.launch()
        self.assertEqual(command[command.index('--persona') + 1], 'astra')
        self.assertIn('--no-notes', command)
        self.assertNotIn('--no-tools', command)
        self.assertNotIn('--claude', command)
        self.assertNotIn('--memory-dir', command)
        self.assertEqual(command[command.index('--search') + 1], 'off')

    async def test_nova_remains_available(self):
        command = await self.launch(persona='nova')
        self.assertEqual(command[command.index('--persona') + 1], 'nova')

    async def test_conversation_only_disables_tools(self):
        self.assertIn('--no-tools', await self.launch(conversation_only=True))

    async def test_memory_is_explicit_and_key_is_not_a_command_line_argument(self):
        key = 'synthetic-test-key-not-a-credential'
        command = await self.launch(memory_dir='/tmp/synthetic-memory', memory_key=key)
        self.assertEqual(command[command.index('--memory-dir') + 1], '/tmp/synthetic-memory')
        self.assertNotIn(key, command)
        self.assertEqual(self.environment['SPEAKRAIL_MEMORY_KEY'], key)
        self.assertTrue(self.private_log)

    async def test_memory_launch_log_is_owner_only_even_if_it_already_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'voice-ui.log'
            log.write_text('Old log')
            log.chmod(0o644)
            services = test_speech.Services()
            with patch.object(test_speech, 'ROOT', root), patch.object(test_speech.subprocess, 'Popen'):
                services.start('voice-ui', ['synthetic-process'], private_log=True)
            services.children[0][1].close()
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
