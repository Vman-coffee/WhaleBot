"""Exercise installed memory guards without importing or starting those plugins."""
import ast
import __future__
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

ROOT=Path('/AstrBot/data/plugins')
FLAG='_yunshao_bili_shadow_report'

def method(path,name):
    tree=ast.parse((ROOT/path).read_text(encoding='utf-8-sig'))
    node=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
    node.decorator_list=[]
    module=ast.Module(body=[node],type_ignores=[])
    namespace={'_json_result':lambda x:x, 'reset_trace_context':lambda:None}
    exec(compile(module,'<installed guard>', 'exec',flags=__future__.annotations.compiler_flag),namespace)
    return namespace[name]

@unittest.skipUnless((ROOT/'astrbot_plugin_bili_shadow/memory-guards.json').exists(),'post-install checks')
class InstalledGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_reflection_skips_report_but_keeps_regular_chat(self):
        call=method('astrbot_plugin_livingmemory/main.py','handle_memory_reflection')
        handler=NS(handle_memory_reflection=AsyncMock())
        plugin=NS(_ensure_plugin_ready=AsyncMock(return_value=(True,None)),event_handler=handler)
        await call(plugin,NS(get_extra=lambda key,default:True),NS())
        handler.handle_memory_reflection.assert_not_awaited()
        await call(plugin,NS(get_extra=lambda key,default:False),NS())
        handler.handle_memory_reflection.assert_awaited_once()
    async def test_memorize_tool_rejects_report_even_if_model_calls_it(self):
        call=method('astrbot_plugin_livingmemory/core/tools/memory_memorize_tool.py','call')
        plugin=NS(context=object(),memory_engine=object(),memory_processor=object())
        event=NS(get_extra=lambda key,default:True)
        result=await call(plugin,NS(context=NS(event=event)),memory='视频内容不是主人事实')
        self.assertFalse(result['memorized'])
        self.assertIn('shadow',result['error'])
    async def test_self_learning_does_not_capture_report(self):
        call=method('astrbot_plugin_self_learning/main.py','on_bot_message_sent')
        # Missing all normal plugin fields: flagged path must return before accessing them.
        await call(NS(),NS(get_extra=lambda key,default:True))

if __name__=='__main__': unittest.main()
