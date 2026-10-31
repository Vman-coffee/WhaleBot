"""Optional real read-only media test; not a QQ caller or end-to-end authorization test."""
import asyncio
import json
import tempfile
import sys
import time
from pathlib import Path
from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
from astrbot_plugin_bili_shadow.engine import load_helpers, make_reader, ModelPort, execute

async def main():
    data=Path('/AstrBot/data')
    cfg=json.loads((data/'cmd_config.json').read_text(encoding='utf-8-sig'))
    shadow=json.loads(Path('/tmp/bili-shadow-config.json').read_text(encoding='utf-8-sig'))
    pid=shadow['provider_id']
    model=next(p for p in cfg['provider'] if p['id']==pid)
    source=next(p for p in cfg['provider_sources'] if p['id']==model['provider_source_id'])
    provider=ProviderOpenAIOfficial({**source,**model}, cfg.get('provider_settings',{}))
    try:
        with tempfile.TemporaryDirectory(prefix='shadow-probe-') as temp:
            cls=load_helpers(data/'plugins/astrbot_plugin_bilibili_ai_bot',temp)
            reader=make_reader(cls,data/'config/astrbot_plugin_bilibili_ai_bot_config.json',ModelPort(provider.text_chat,pid),pid)
            operation='search_watch' if len(sys.argv)>1 else 'watch'
            target=sys.argv[1] if len(sys.argv)>1 else 'BV11K421t7Xg'
            started=time.monotonic()
            result=await asyncio.wait_for(execute(reader,operation,target),timeout=105)
            print('elapsed_seconds',round(time.monotonic()-started,2))
            print(json.dumps(result,ensure_ascii=False))
            items=result['items'] if operation=='search_watch' else [result]
            assert any(item.get('basis')=='video_media' for item in items), 'visual path not verified'
    finally:
        await provider.client.close()

if __name__=='__main__': asyncio.run(main())
