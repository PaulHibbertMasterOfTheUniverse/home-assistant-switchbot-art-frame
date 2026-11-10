"""Run installed protocol selection against a fake invoke; no network or credentials."""
import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace


class SelectionTests(unittest.IsolatedAsyncioTestCase):
    async def commands(self, model=None):
        source = Path(__file__).resolve().parents[1] / 'custom_components/switchbot_frame_control/protocol.py'
        tree = ast.parse(source.read_text())
        client = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AppClient')
        method = next(n for n in client.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'show')
        module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
        namespace = {}
        exec(compile(module, str(source), 'exec'), namespace)
        calls = []

        async def invoke(function, params):
            calls.append((function, params))

        obj = SimpleNamespace(invoke=invoke)
        if model is None:
            await namespace['show'](obj, 83)
        else:
            await namespace['show'](obj, 83, model)
        return calls

    async def test_original_direct_selection_without_schedule_write(self):
        self.assertEqual(await self.commands('frame1'), [(9602, {'0': 83})])

    async def test_frame2_unchanged(self):
        self.assertEqual(await self.commands('frame2'),
                         [(9626, {'0': 83, '1': 0, '2': 0}), (9622, {'0': 83})])

    async def test_default_remains_frame2(self):
        self.assertEqual(await self.commands(),
                         [(9626, {'0': 83, '1': 0, '2': 0}), (9622, {'0': 83})])


if __name__ == '__main__':
    unittest.main()
