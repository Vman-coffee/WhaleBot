"""QQ-only adapter and bounded scheduler; no synthetic incoming chat events."""
import asyncio
import contextvars
import json
import uuid
from datetime import datetime
from pathlib import Path
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.star.session_llm_manager import SessionServiceManager
from astrbot.core.star.session_plugin_manager import SessionPluginManager
from .autonomy import TZ, Ledger, evening_slot, deliver, share_text
from .engine import ModelPort, make_reader, execute
from .policy import BV

NAME='astrbot_plugin_bili_shadow'
LEGACY='astrbot_plugin_bilibili_ai_bot'

class ProactiveMixin:
    def start_proactive(self):
        self.ledger=Ledger(self.store)
        self.route_path=self.data_dir/'qq_delivery.json'
        self.route=json.loads(self.route_path.read_text()) if self.route_path.exists() else {}
        self.scheduler=asyncio.create_task(self.schedule_loop(),context=contextvars.Context())

    def save_route(self):
        temp=self.route_path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.route),encoding='utf-8')
        temp.replace(self.route_path)

    async def route_allowed(self):
        r=self.route
        try:
            if self._closing or not self.config.get('enabled') or not self.guards_valid(): return False
            old=self.context.get_registered_star(LEGACY)
            if old is not None and getattr(old,'activated',True): return False
            session=MessageSession.from_str(r['umo'])
            if session.message_type.value!='FriendMessage' or session.session_id!=self.config['owner_id']: return False
            if r['owner']!=self.config['owner_id']: return False
            cfg=self.context.get_config(r['umo'])
            if r['owner'] not in [str(x) for x in cfg.get('admins_id',[])]: return False
            if not await SessionServiceManager.is_session_enabled(r['umo']): return False
            if not await SessionPluginManager.is_plugin_enabled_for_session(r['umo'],NAME): return False
            mgr=self.context.conversation_manager
            cid=await mgr.get_curr_conversation_id(r['umo'])
            conv=await mgr.get_conversation(r['umo'],cid) if cid else None
            pid,_,_,_=await self.context.persona_manager.resolve_selected_persona(
                umo=r['umo'],conversation_persona_id=getattr(conv,'persona_id',None),
                platform_name='aiocqhttp',provider_settings=cfg.get('provider_settings',{}))
            if pid!=self.config['persona_id']: return False
            platform=next(p for p in self.context.platform_manager.platform_insts if p.meta().id==session.platform_id)
            if platform.meta().name!='aiocqhttp': return False
            login=await asyncio.wait_for(platform.get_client().api.call_action('get_login_info'),timeout=10)
            return str(login['user_id'])==r['bot']
        except Exception:
            return False

    async def send_qq(self, text):
        if not await self.route_allowed(): return False
        return await self.context.send_message(self.route['umo'],MessageChain([Plain(text)]))

    async def test_delivery(self, event: AstrMessageEvent):
        if not await self.authorized(event):
            yield event.plain_result('请主人在与云梢的QQ私聊中测试。')
            return
        if event.get_platform_name()!='aiocqhttp':
            yield event.plain_result('当前只验收OneBot QQ私聊投递。')
            return
        if self.lock.locked():
            yield event.plain_result('请等当前观看任务完成后再测试投递。')
            return
        if getattr(self,'_delivery_test_pending',False):
            yield event.plain_result('已有投递测试正在进行，请稍候。')
            return
        self.route={'umo':event.unified_msg_origin,'owner':str(event.get_sender_id()),
                    'bot':str(event.get_self_id()),'scope':self.scope(event),
                    'confirmed':False,'test_state':'pending'}
        self.save_route()
        self._delivery_test_pending=True
        task=asyncio.create_task(self.send_test(),context=contextvars.Context())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        yield event.plain_result('已绑定当前主人私聊。稍后会单独主动发送一条标记消息，请收到后发送 /bili分享确认。')

    async def send_test(self):
        try:
            await asyncio.sleep(3)
            state=await deliver(self.ledger,'test:'+uuid.uuid4().hex,self.send_qq,
                '【云梢·QQ主动分享测试】主人，这是通过QQ私聊主动投递接口发出的独立消息，不是B站私信。收到后请发送 /bili分享确认，启用每天20:30–21:00一轮、每轮1条的试运行。')
            self.route['test_state']=state
            self.save_route()
        except Exception as exc:
            self.route['test_state']='unknown'
            self.save_route()
            logger.warning('[BiliShadow] QQ test uncertain (%s); no automatic retry.',type(exc).__name__)
        finally:
            self._delivery_test_pending=False

    async def confirm_delivery(self,event: AstrMessageEvent):
        if not await self.authorized(event) or self.route.get('umo')!=event.unified_msg_origin:
            yield event.plain_result('只能由绑定的主人私聊确认。'); return
        if self.route.get('test_state')!='accepted':
            yield event.plain_result('尚无成功的主动投递记录，请先发送 /bili分享测试。'); return
        self.route['confirmed']=True
        self.save_route()
        self.config['autonomous_enabled']=True
        self.config.save_config()
        yield event.plain_result('已确认QQ主动分享。每天北京时间20:30–21:00最多一轮、每轮1条，持久化去重；仅浏览与QQ分享。发送 /bili浏览暂停 可停用。')

    async def pause_browsing(self,event: AstrMessageEvent):
        if not await self.authorized(event): return
        self.config['autonomous_enabled']=False
        self.config.save_config()
        yield event.plain_result('已暂停自主浏览和主动分享；手动观看与回忆仍可用。')

    async def schedule_loop(self):
        while not self._closing:
            try:
                day=evening_slot(datetime.now(TZ))
                if (day and self.config.get('autonomous_enabled') and self.route.get('confirmed')
                    and not self.lock.locked() and await self.route_allowed()):
                    async with self.lock:
                        if self.ledger.reserve_round(day):
                            await self.browse_round(day)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning('[BiliShadow] Scheduled round stopped (%s).',type(exc).__name__)
            await asyncio.sleep(45)

    async def browse_round(self,day):
        task_id=None
        state='failed'
        scope=self.route['scope']
        try:
            pid=self.config['provider_id']
            provider=await self.context.provider_manager.get_provider_by_id(pid)
            path=Path(__file__).resolve().parents[2]/'config'/(LEGACY+'_config.json')
            reader=make_reader(self.helper,path,ModelPort(provider.text_chat,pid),pid)
            topics=('自然 科普','动物 趣味','天文 科普')
            keyword=topics[datetime.fromisoformat(day).toordinal()%len(topics)]
            found=await asyncio.wait_for(reader.search_bilibili_videos(keyword,ps=5),timeout=45)
            bvid=next((v['bvid'] for v in found if BV.fullmatch(str(v.get('bvid','')))
                       and self.ledger.reserve_video(scope,v['bvid'])),None)
            if not bvid: state='no_new_video'; return
            task_id=self.store.begin(scope,'watch',bvid)
            payload=await asyncio.wait_for(execute(reader,'watch',bvid),timeout=420)
            payload['trigger']='autonomous_evening'
            self.store.finish(task_id,scope,payload)
            task_id=None
            state='analyzed'
            if payload.get('basis') not in ('video_media','subtitles'): state='insufficient_evidence'; return
            if not self.config.get('autonomous_enabled') or evening_slot(datetime.now(TZ))!=day:
                state='saved_outside_window'; return
            state=await deliver(self.ledger,'evening:'+day,self.send_qq,share_text(payload))
        finally:
            if task_id is not None: self.store.fail(task_id,scope)
            self.ledger.finish_round(day,state)
