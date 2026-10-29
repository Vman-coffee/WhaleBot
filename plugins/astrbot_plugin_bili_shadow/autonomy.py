"""Bounded evening browsing and a separate QQ delivery ledger. No Bili writes."""
import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')

def evening_slot(now):
    local = now.astimezone(TZ)
    return local.date().isoformat() if (local.hour == 20 and local.minute >= 30) else None

class Ledger:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS auto_rounds(day TEXT PRIMARY KEY, state TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS auto_seen(scope TEXT, bvid TEXT, PRIMARY KEY(scope,bvid))')
            db.execute('CREATE TABLE IF NOT EXISTS delivery(key TEXT PRIMARY KEY, state TEXT NOT NULL)')
            db.execute("UPDATE auto_rounds SET state='interrupted' WHERE state='running'")
            db.execute("UPDATE delivery SET state='unknown' WHERE state='sending'")
    def reserve_round(self, day):
        with self.store.connect() as db:
            return db.execute("INSERT OR IGNORE INTO auto_rounds VALUES(?,'running')",(day,)).rowcount == 1
    def finish_round(self, day, state):
        with self.store.connect() as db:
            db.execute('UPDATE auto_rounds SET state=? WHERE day=?',(state,day))
    def reserve_video(self, scope, bvid):
        with self.store.connect() as db:
            # Also deduplicate videos already watched manually.
            old=db.execute("SELECT 1 FROM tasks WHERE scope=? AND operation='watch' AND target=?",(scope,bvid)).fetchone()
            if old: return False
            return db.execute('INSERT OR IGNORE INTO auto_seen VALUES(?,?)',(scope,bvid)).rowcount == 1
    def reserve_delivery(self, key):
        with self.store.connect() as db:
            return db.execute("INSERT OR IGNORE INTO delivery VALUES(?,'sending')",(key,)).rowcount == 1
    def delivery_state(self, key, state):
        with self.store.connect() as db:
            db.execute('UPDATE delivery SET state=? WHERE key=?',(state,key))

async def deliver(ledger, key, sender, message):
    if not ledger.reserve_delivery(key): return 'duplicate'
    try:
        accepted=await asyncio.wait_for(sender(message),timeout=25)
        state='accepted' if accepted else 'unavailable'
        ledger.delivery_state(key,state)
        return state
    except BaseException:
        # Timeout/disconnect can happen after sending: never retry automatically.
        ledger.delivery_state(key,'unknown')
        raise

def share_text(payload):
    return ('主人，云梢今晚看了一条B站视频，来和你分享一下。\n'
            + str(payload.get('title',''))[:100] + '\n'
            + str(payload.get('summary',''))[:650] + '\n'
            + 'https://www.bilibili.com/video/' + payload['bvid'] + '\n'
            + '这次依据有限抽帧与可用字幕，没有完整音频；未覆盖部分不能确认。')
