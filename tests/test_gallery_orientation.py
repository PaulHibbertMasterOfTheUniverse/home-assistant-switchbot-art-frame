"""Actual Pillow gallery pixels, compared with the browser's synthetic markers."""
import ast
import asyncio
import io
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'custom_components/switchbot_frame_control/gallery.py'
tree = ast.parse(SOURCE.read_text())
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'prepare_transport']
gallery = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Gallery')
nodes += [node for node in gallery.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'send']
scope = dict(Image=Image, ImageOps=ImageOps, io=io)
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), scope)

COLOURS = [(240,20,20), (20,240,20), (20,20,240), (240,240,20)]


def artwork():
    image = Image.new('RGB', (60,80))
    for y in range(80):
        for x in range(60):
            image.putpixel((x,y), COLOURS[(0 if y < 40 else 2) + (0 if x < 30 else 1)])
    out = io.BytesIO();image.save(out,'PNG');return out.getvalue()


def corners(raw):
    with Image.open(io.BytesIO(raw)) as image:
        w,h=image.size
        points = [(w//8,h//8),(w*7//8,h//8),(w//8,h*7//8),(w*7//8,h*7//8)]
        result = []
        for point in points:
            rgb=image.getpixel(point)
            result.append(1+min(range(4),key=lambda i:sum(abs(a-b) for a,b in zip(rgb,COLOURS[i]))))
        return image.size,result


class OrientationTests(unittest.TestCase):
    def test_portrait_gallery_false_matches_browser_pixels(self):
        raw=scope['prepare_transport'](artwork(),{'orientation':'portrait','flipped':False},'31.5')
        self.assertEqual(corners(raw),((2560,1440),[2,4,1,3]))

    def test_portrait_gallery_true_matches_browser_exactly_once(self):
        raw=scope['prepare_transport'](artwork(),{'orientation':'portrait','flipped':True},'31.5')
        self.assertEqual(corners(raw),((2560,1440),[3,1,4,2]))

    def test_other_panel_profiles_keep_their_existing_layout(self):
        for size,dimensions in [('7.3',(800,480)),('13.3',(1600,1200))]:
            with self.subTest(size=size):
                raw=scope['prepare_transport'](artwork(),{'orientation':'portrait','flipped':False},size)
                self.assertEqual(corners(raw),(dimensions,[2,4,1,3]))


class GallerySendTests(unittest.IsolatedAsyncioTestCase):
    async def test_automation_send_passes_server_layout_as_race_guard(self):
        layout={'orientation':'portrait','flipped':True}
        manager=NS(data={'layout':layout},config={'panel_size':'31.5'},upload=AsyncMock(return_value={'accepted':True}))

        async def executor(function,*args):return function(*args)

        obj=NS(hass=NS(data={'switchbot_frame_control':NS(select=lambda _:manager)},async_add_executor_job=executor),
               path=lambda _:NS(read_bytes=artwork))
        result=await scope['send'](obj,'synthetic','example_frame')
        self.assertEqual(result,{'accepted':True})
        call=manager.upload.await_args
        self.assertEqual(call.kwargs['expected_layout'],layout)
        self.assertEqual(corners(call.args[0]),((2560,1440),[3,1,4,2]))


if __name__=='__main__':unittest.main()
