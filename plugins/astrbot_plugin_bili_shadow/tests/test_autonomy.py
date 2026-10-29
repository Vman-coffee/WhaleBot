import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import patch
from types import SimpleNamespace as NS
from astrbot_plugin_bili_shadow.store import Store
from astrbot_plugin_bili_shadow.autonomy import Ledger, TZ, evening_slot, deliver
from astrbot_plugin_bili_shadow.proactive import ProactiveMixin

class AutonomyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'test.db'); self.ledger=Ledger(self.store)
    def test_window_and_daily_cap_survive_restart(self):
        for time,valid in [('20:29',False),('20:30',True),('20:59',True),('21:00',False),('12:30',False)]:
            self.assertEqual(bool(evening_slot(datetime.fromisoformat('2026-10-30T'+time).replace(tzinfo=TZ))),valid)
        self.assertTrue(self.ledger.reserve_round('2026-10-30'))
        self.assertFalse(Ledger(self.store).reserve_round('2026-10-30'))
        self.assertTrue(self.ledger.reserve_round('2026-10-31'))
    def test_dedup_includes_manual_and_failed_attempts(self):
        self.store.begin('owner','watch','BV11K421t7Xg')
        self.assertFalse(self.ledger.reserve_video('owner','BV11K421t7Xg'))
        self.assertTrue(self.ledger.reserve_video('owner','BV1PzxV65Eg5'))
        self.assertFalse(Ledger(self.store).reserve_video('owner','BV1PzxV65Eg5'))
    async def test_delivery_does_not_retry_after_ambiguous_failure(self):
        sender=AsyncMock(side_effect=ConnectionError())
        with self.assertRaises(ConnectionError): await deliver(self.ledger,'day',sender,'report')
        self.assertEqual(await deliver(Ledger(self.store),'day',sender,'report'),'duplicate')
        sender.assert_awaited_once()
        with self.store.connect() as db:
            self.assertEqual(db.execute('select state from delivery').fetchone()[0],'unknown')
    async def test_acceptance_is_not_receipt(self):
        self.assertEqual(await deliver(self.ledger,'day',AsyncMock(return_value=True),'report'),'accepted')
        self.assertEqual(await deliver(self.ledger,'other',AsyncMock(return_value=False),'report'),'unavailable')
    async def test_real_route_checks_group_persona_and_logged_in_bot(self):
        plugin=ProactiveMixin()
        plugin._closing=False; plugin.guards_valid=lambda:True
        plugin.config={'enabled':True,'owner_id':'123','persona_id':'yunshao'}
        plugin.route={'umo':'qq_adapter:FriendMessage:123','owner':'123','bot':'456'}
        login=AsyncMock(return_value={'user_id':456})
        persona=AsyncMock(return_value=('yunshao',None,None,False))
        platform=NS(meta=lambda:NS(id='qq_adapter',name='aiocqhttp'),get_client=lambda:NS(api=NS(call_action=login)))
        plugin.context=NS(get_registered_star=lambda _:NS(activated=False),
            get_config=lambda _: {'admins_id':['123']},
            platform_manager=NS(platform_insts=[platform]),
            conversation_manager=NS(get_curr_conversation_id=AsyncMock(return_value=None)),
            persona_manager=NS(resolve_selected_persona=persona))
        with patch('astrbot_plugin_bili_shadow.proactive.SessionServiceManager.is_session_enabled',AsyncMock(return_value=True)), \
             patch('astrbot_plugin_bili_shadow.proactive.SessionPluginManager.is_plugin_enabled_for_session',AsyncMock(return_value=True)):
            self.assertTrue(await plugin.route_allowed())
            plugin.route['umo']='qq_adapter:GroupMessage:123'
            self.assertFalse(await plugin.route_allowed())
            plugin.route['umo']='qq_adapter:FriendMessage:999'
            self.assertFalse(await plugin.route_allowed())
            plugin.route['umo']='qq_adapter:FriendMessage:123'
            login.return_value={'user_id':999}
            self.assertFalse(await plugin.route_allowed())
            login.return_value={'user_id':456}; persona.return_value=('other',None,None,False)
            self.assertFalse(await plugin.route_allowed())
    async def test_one_round_analyzes_one_and_saves_before_sharing(self):
        plugin=ProactiveMixin(); plugin.store=self.store; plugin.ledger=self.ledger
        plugin.route={'scope':'owner'}; plugin.helper=object()
        plugin.config={'provider_id':'model','autonomous_enabled':True}
        plugin.context=NS(provider_manager=NS(get_provider_by_id=AsyncMock(return_value=NS(text_chat=AsyncMock()))))
        plugin.send_qq=AsyncMock(return_value=True)
        reader=NS(search_bilibili_videos=AsyncMock(return_value=[{'bvid':'BV11K421t7Xg'},{'bvid':'BV1PzxV65Eg5'}]))
        analyze=AsyncMock(return_value={'basis':'video_media','bvid':'BV11K421t7Xg','summary':'public'})
        with patch('astrbot_plugin_bili_shadow.proactive.make_reader',return_value=reader), \
             patch('astrbot_plugin_bili_shadow.proactive.execute',analyze), \
             patch('astrbot_plugin_bili_shadow.proactive.evening_slot',return_value='2026-10-30'):
            self.ledger.reserve_round('2026-10-30')
            await plugin.browse_round('2026-10-30')
        analyze.assert_awaited_once(); plugin.send_qq.assert_awaited_once()
        self.assertEqual(self.store.recent('owner')[0]['report']['trigger'],'autonomous_evening')

if __name__=='__main__': unittest.main()
