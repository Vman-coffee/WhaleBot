"""Run inside AstrBot: validate first, back up, then install the local shadow plugin.

Usage: python install-bili-shadow.py --check|--apply
Staging: /tmp/astrbot_plugin_bili_shadow, /tmp/bili-shadow-config.json.
Disable the original BiliBot with the dashboard API before --apply; restart afterwards.
"""
import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

DATA = Path('/AstrBot/data')
STAGED = Path('/tmp/astrbot_plugin_bili_shadow')
NAME = 'astrbot_plugin_bili_shadow'
FLAG = '_yunshao_bili_shadow_report'

# Minimal, idempotent source integrations: preserve normal user-chat memory.
PATCHES = [
    ('astrbot_plugin_livingmemory/main.py',
     '        await self.event_handler.handle_memory_reflection(event, resp)',
     '        # WhaleBot: Bili reports belong to the shadow store, not user facts.\n'
     f'        if event.get_extra("{FLAG}", False):\n            return\n'
     '        await self.event_handler.handle_memory_reflection(event, resp)'),
    ('astrbot_plugin_livingmemory/core/tools/memory_memorize_tool.py',
     '            event = context.context.event\n',
     '            event = context.context.event\n'
     f'            if event.get_extra("{FLAG}", False):\n'
     '                return _json_result({"memorized": False, "error": "Bili report: keep in shadow memory, not user facts"})\n'),
    ('astrbot_plugin_self_learning/main.py',
     '    async def on_bot_message_sent(self, event: AstrMessageEvent, *_args):\n'
     '        """捕获 Bot 发送的消息并存入数据库，用于 fewshot 对话对提取。"""\n'
     '        reset_trace_context()\n',
     '    async def on_bot_message_sent(self, event: AstrMessageEvent, *_args):\n'
     '        """捕获 Bot 发送的消息并存入数据库，用于 fewshot 对话对提取。"""\n'
     '        reset_trace_context()\n'
     f'        if event.get_extra("{FLAG}", False):\n            return\n'
     ),
]

def main(apply):
    config=json.loads(Path('/tmp/bili-shadow-config.json').read_text(encoding='utf-8-sig'))
    core=json.loads((DATA/'cmd_config.json').read_text(encoding='utf-8-sig'))
    if config.get('owner_id') not in [str(x) for x in core.get('admins_id',[])]:
        raise ValueError('owner must be a configured admin')
    if config.get('persona_id') != '专属女仆-云梢':
        raise ValueError('unexpected persona selection')
    if config.get('provider_id') not in [p['id'] for p in core['provider'] if p.get('enable')]:
        raise ValueError('provider must exist and be enabled')
    manifest=json.loads((STAGED/'engine-manifest.json').read_text())
    for relative,digest in manifest.items():
        path=DATA/'plugins/astrbot_plugin_bilibili_ai_bot'/relative
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('media dependency differs: '+relative)
    for path in STAGED.rglob('*.py'):
        compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
    prepared=[]
    for relative,old,new in PATCHES:
        path=DATA/'plugins'/relative
        original=path.read_text(encoding='utf-8-sig')
        if new in original:
            updated=original
        elif original.count(old)==1:
            updated=original.replace(old,new,1)
        else:
            raise ValueError('memory integration needs review: '+relative)
        compile(updated,str(path),'exec')
        prepared.append((path,updated))
    if not apply:
        print('Validated: owner, persona, provider, pinned media helpers, three memory guards, Python syntax.')
        return
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=DATA/'plugin_data'/NAME/'install_backups'/stamp
    backup.mkdir(parents=True)
    dest=DATA/'plugins'/NAME
    config_path=DATA/'config'/(NAME+'_config.json')
    for path,_ in prepared:
        saved=backup/path.relative_to(DATA)
        saved.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,saved)
    if dest.exists():
        shutil.copytree(dest,backup/'previous_shadow_plugin')
    if config_path.exists():
        shutil.copy2(config_path,backup/'previous_shadow_config.json')
    try:
        shutil.copytree(STAGED,dest,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
        config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
        for path,updated in prepared:
            path.write_text(updated,encoding='utf-8')
        hashes={str(path.relative_to(DATA/'plugins')):hashlib.sha256(path.read_bytes()).hexdigest()
                for path,_ in prepared}
        (dest/'memory-guards.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    except Exception:
        for path,_ in prepared:
            shutil.copy2(backup/path.relative_to(DATA),path)
        # Keep the new plugin disabled on an incomplete installation.
        config['enabled']=False
        config_path.write_text(json.dumps(config),encoding='utf-8')
        raise
    print('Installed; original memory sources backed up to '+str(backup))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true')
    mode.add_argument('--apply',action='store_true')
    main(parser.parse_args().apply)
