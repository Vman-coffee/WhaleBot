"""Optional real read-only media test; not a QQ caller or end-to-end authorization test."""
import asyncio
import json
import tempfile
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
            result=await asyncio.wait_for(execute(reader,'watch','BV11K421t7Xg'),timeout=240)
            print(json.dumps(result,ensure_ascii=False))
            assert result['kind']=='viewing_experience'
            assert result['basis']=='video_media', 'visual path not verified'
    finally:
        await provider.client.close()

if __name__=='__main__': asyncio.run(main())
