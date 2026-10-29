"""Yunshao dispatches bounded public tasks; private reports never enter groups."""
import asyncio
import hashlib
import json
import re
from pathlib import Path
from pydantic import Field
from pydantic.dataclasses import dataclass
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.message import TextPart
from astrbot.core.star.session_llm_manager import SessionServiceManager
from astrbot.core.star.session_plugin_manager import SessionPluginManager
from .policy import FLAG, MARKER, TOOLS, owner_private, task_target, report_block
from .store import Store
from .engine import ModelPort, load_helpers, make_reader, execute

NAME = 'astrbot_plugin_bili_shadow'
LEGACY = 'astrbot_plugin_bilibili_ai_bot'

class BiliShadow(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.data_dir = Path(StarTools.get_data_dir(NAME))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.data_dir / 'shadow.sqlite3')
        self.lock = asyncio.Lock()
        self.helper = None
        self._tasks = set()
        self._closing = False
        self.context.add_llm_tools(*self.create_tools())

    async def initialize(self):
        if not self.guards_valid():
            raise RuntimeError('Shadow memory integrations missing or changed; review installation')
        source = Path(__file__).resolve().parent.parent / LEGACY
        self.helper = load_helpers(source, self.data_dir)
        logger.info('[BiliShadow] Ready: owner private chat only; separate reports; no social writes.')

    def guards_valid(self):
        try:
            root = Path(__file__).resolve().parent
            hashes = json.loads((root / 'memory-guards.json').read_text())
            return len(hashes) == 3 and all(
                hashlib.sha256((root.parent / name).read_bytes()).hexdigest() == digest
                for name, digest in hashes.items())
        except Exception:
            return False

    async def authorized(self, event):
        if self._closing or not owner_private(event, self.config):
            return False
        try:
            if not self.guards_valid():
                return False
            # Fail closed if the original general-purpose entry points are re-enabled.
            old = self.context.get_registered_star(LEGACY)
            if old is not None and getattr(old, 'activated', True):
                return False
            umo = event.unified_msg_origin
            if not await SessionServiceManager.is_session_enabled(umo):
                return False
            if not await SessionPluginManager.is_plugin_enabled_for_session(umo, NAME):
                return False
            manager = self.context.conversation_manager
            cid = await manager.get_curr_conversation_id(umo)
            conversation = await manager.get_conversation(umo, cid) if cid else None
            pid, _, _, _ = await self.context.persona_manager.resolve_selected_persona(
                umo=umo, conversation_persona_id=getattr(conversation, 'persona_id', None),
                platform_name=event.get_platform_name(),
                provider_settings=self.context.get_config(umo).get('provider_settings', {}))
            return pid == self.config.get('persona_id')
        except Exception:
            return False

    @staticmethod
    def scope(event):
        # Stable owner+bot namespace, separate across bot accounts; no clear QQ ID in reports.
        raw = f'{event.get_platform_name()}:{event.get_self_id()}:{event.get_sender_id()}'
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def mark_report(event):
        event.set_extra(FLAG, True)
        toolset = event.get_extra('_bili_shadow_toolset')
        if toolset is not None:
            toolset.remove_tool('memorize_long_term_memory')

    async def run_task(self, event, operation, target):
        if not await self.authorized(event):
            return 'B站分身仅在主人与云梢的私聊中可用；当前会话未获授权。'
        try:
            target = task_target(operation, target, event.message_str)
        except ValueError as exc:
            return str(exc)
        if self.lock.locked():
            return '分身正在处理一项观看任务，请等本次报告完成后再交代。'
        self.mark_report(event)
        scope = self.scope(event)
        task_id = self.store.begin(scope, operation, target)
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            async with self.lock:
                provider_id = self.config['provider_id']
                provider = await self.context.provider_manager.get_provider_by_id(provider_id)
                if provider is None or self.helper is None:
                    raise RuntimeError('reader unavailable')
                path = Path(__file__).resolve().parents[2] / 'config' / (LEGACY + '_config.json')
                reader = make_reader(self.helper, path, ModelPort(provider.text_chat, provider_id), provider_id)
                payload = await asyncio.wait_for(execute(reader, operation, target), timeout=420)
                self.store.finish(task_id, scope, payload)
                return report_block(self.store.recent(scope, 1))
        except asyncio.CancelledError:
            self.store.fail(task_id, scope)
            raise
        except Exception as exc:
            self.store.fail(task_id, scope)
            logger.warning('[BiliShadow] Task failed (%s); no private transcript stored.', type(exc).__name__)
            return '分身本次任务未完成，不能声称已经看过。请稍后重试。'
        finally:
            self._tasks.discard(task)

    async def get_reports(self, event):
        if not await self.authorized(event):
            return '当前会话无权读取分身报告。'
        self.mark_report(event)
        rows = self.store.recent(self.scope(event), 3)
        return report_block(rows) if rows else '分身尚无独立记录；未导入旧插件的共享观看缓存。'

    @filter.on_llm_request(priority=-100)
    async def inject_reports(self, event: AstrMessageEvent, req):
        parts = getattr(req, 'extra_user_content_parts', None)
        if not isinstance(parts, list):
            return
        parts[:] = [p for p in parts if not getattr(p, 'text', '').startswith(MARKER)]
        allowed = await self.authorized(event)
        toolset = getattr(req, 'func_tool', None)
        if toolset is not None:
            # Never mutate a shared global tool registry.
            from astrbot.core.agent.tool import ToolSet
            toolset = ToolSet(list(toolset.tools))
            req.func_tool = toolset
            if not allowed:
                for name in TOOLS:
                    toolset.remove_tool(name)
            else:
                event.set_extra('_bili_shadow_toolset', toolset)
        if not allowed:
            return
        text = event.message_str or ''
        if re.search(r'B站|bilibili|BV[0-9A-Za-z]{10}|分身|刷视频|观看报告', text, re.I):
            self.mark_report(event)
            rows = self.store.recent(self.scope(event), 3)
            parts.append(TextPart(text=report_block(rows) + '\n任务只允许明确的BV号或原消息中的公开搜索词。不能转交整段私聊。').mark_as_temp())

    def create_tools(self):
        plugin = self
        @dataclass
        class TaskTool(FunctionTool[AstrAgentContext]):
            name: str = 'yunshao_bili_task'
            description: str = ('云梢向自己的B站协作分身下达只读任务。仅主人私聊可用。'
                                'watch必须用主人本条消息中的BV号；search只用本条消息中的公开主题短语。'
                                '不传私聊背景、理由或个人信息。结果是分身经历，不是用户事实。')
            parameters: dict = Field(default_factory=lambda: {'type':'object', 'properties':{
                'operation':{'type':'string','enum':['watch','search']},
                'target':{'type':'string','description':'本条用户消息中的BV号或2～40字公开搜索词'}},
                'required':['operation','target'], 'additionalProperties':False})
            async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
                event = getattr(getattr(context, 'context', None), 'event', None)
                return await plugin.run_task(event, kwargs.get('operation'), kwargs.get('target'))
        @dataclass
        class ReportTool(FunctionTool[AstrAgentContext]):
            name: str = 'yunshao_bili_report'
            description: str = '云梢读取自己的B站分身最近三份独立报告，用当前会话人格给主人回复。仅主人私聊可用。'
            parameters: dict = Field(default_factory=lambda: {'type':'object','properties':{},'additionalProperties':False})
            async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
                event = getattr(getattr(context, 'context', None), 'event', None)
                return await plugin.get_reports(event)
        return [TaskTool(), ReportTool()]

    async def terminate(self):
        self._closing = True
        pending = [task for task in self._tasks if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
