"""Check public launcher defaults without loading models."""
import unittest
from unittest.mock import AsyncMock, Mock, patch

import local_stack


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
        return calls[0].args[1]

    async def test_astra_default_keeps_local_tools_but_disables_background_notes(self):
        command = await self.launch()
        self.assertEqual(command[command.index('--persona') + 1], 'astra')
        self.assertIn('--no-notes', command)
        self.assertNotIn('--no-tools', command)
        self.assertNotIn('--claude', command)
        self.assertEqual(command[command.index('--search') + 1], 'off')

    async def test_nova_remains_available(self):
        command = await self.launch(persona='nova')
        self.assertEqual(command[command.index('--persona') + 1], 'nova')

    async def test_conversation_only_disables_tools(self):
        self.assertIn('--no-tools', await self.launch(conversation_only=True))


if __name__ == '__main__':
    unittest.main()
