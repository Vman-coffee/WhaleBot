"""Reuse pinned media helpers, without instantiating BiliBot or its memory/tools."""
import hashlib
import asyncio
import importlib
import json
import sys
import types
from pathlib import Path
from urllib.parse import urlsplit
from .policy import PUBLIC_PERSONA, BV

class ModelPort:
    """Only a model callable crosses this boundary; no AstrBot context or tools."""
    def __init__(self, text_chat, provider_id):
        self._text_chat = text_chat
        self.provider_id = provider_id

    async def llm_generate(self, *, chat_provider_id, prompt, max_tokens=900, system_prompt=''):
        if chat_provider_id != self.provider_id:
            raise ValueError('unexpected provider')
        # No histories, private persona, tools, memory hooks or caller-supplied system.
        return await self._text_chat(prompt=prompt, system_prompt=PUBLIC_PERSONA,
                                     max_tokens=max_tokens, contexts=[], func_tool=None,
                                     request_max_retries=1)

def load_helpers(plugin_dir, data_dir):
    """A separate module namespace prevents touching the original plugin globals."""
    source = Path(plugin_dir)
    manifest = json.loads(Path(__file__).with_name('engine-manifest.json').read_text())
    for name, digest in manifest.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('BiliBot media dependency changed; review before enabling')
    name = '_whalebot_shadow_media_v1'
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(source)]
        sys.modules[name] = package
    cfg = importlib.import_module(name + '.core.config')
    root = Path(data_dir) / 'media'
    root.mkdir(parents=True, exist_ok=True)
    # All helper file constants are confined to a separate media workspace.
    for key, value in list(vars(cfg).items()):
        if isinstance(value, str) and (key.endswith('_FILE') or key.endswith('_DIR')):
            setattr(cfg, key, str(root / Path(value).name))
            if key.endswith('_DIR'):
                Path(getattr(cfg, key)).mkdir(parents=True, exist_ok=True)
    classes = [getattr(importlib.import_module(name + '.core.' + module), cls) for module, cls in (
        ('utils','UtilsMixin'), ('bilibili','BilibiliAPIMixin'), ('llm','LLMMixin'),
        ('video','VideoMixin'), ('vision','VisionMixin'))]
    return type('ReadOnlyMedia', tuple(classes), {})

def make_reader(helper_class, config_path, model_port, provider_id):
    original = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
    # Deliberate allowlist: no OWNER_*, persona, memory, prompts or web-search keys.
    keep = ('SESSDATA','BILI_JCT','DEDE_USER_ID','BUVID3','BUVID4')
    reader = helper_class()
    reader.config = {k:original[k] for k in keep if k in original}
    reader.config.update({'LLM_PROVIDER_ID':provider_id, 'VIDEO_VISION_PROVIDER_ID':provider_id,
                          'VIDEO_VISION_FORMAT':'none', 'VIDEO_VISUAL_ANALYSIS_POLICY':'always',
                          'VIDEO_SEGMENT_MINUTES':1, 'VIDEO_SEGMENT_MAX_COUNT':3,
                          'ENABLE_WEB_SEARCH':False, 'USE_ASTRBOT_PERSONA':False})
    reader.context = model_port
    reader._video_vision_client = reader._image_vision_client = None
    async def deny_write(*args, **kwargs):
        raise PermissionError('shadow media worker is read-only')
    reader._http_post = deny_write
    async def public_get(url, headers=None, params=None, timeout=10, retries=2):
        import aiohttp
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if (parsed.scheme != 'https' or parsed.username or parsed.password
                or parsed.port not in (None, 443)
                or not (host == 'api.bilibili.com' or host.endswith('.hdslb.com'))):
            raise PermissionError('unexpected media API host')
        safe_headers = reader._headers()
        if host != 'api.bilibili.com':
            safe_headers.pop('Cookie', None)
        # Never follow an API redirect with account cookies or trust caller headers.
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=safe_headers, params=params,
                                   timeout=aiohttp.ClientTimeout(total=min(30, timeout)),
                                   allow_redirects=False) as response:
                if response.status != 200:
                    raise RuntimeError('Bilibili read failed with HTTP '+str(response.status))
                return await response.json(content_type=None), response
    reader._http_get = public_get
    return reader

async def execute(reader, operation, target):
    if operation == 'search_watch':
        if hasattr(reader, 'config'):
            reader.config['VIDEO_SEGMENT_MAX_COUNT'] = 1
        found = await asyncio.wait_for(reader.search_bilibili_videos(target, ps=5),timeout=8)
        def duration(video):
            try:
                parts=[int(p) for p in str(video.get('duration','')).split(':')]
                return sum(v * 60**i for i,v in enumerate(reversed(parts)))
            except ValueError:
                return 0
        # The host cancels tools at 120 seconds. Avoid full downloads of long compilations.
        found=sorted((v for v in found if 0 < duration(v) <= 600),key=duration)
        selected = []
        for video in found:
            bvid = str(video.get('bvid', ''))
            if BV.fullmatch(bvid) and bvid not in selected:
                selected.append(bvid)
            if len(selected) == 2:
                break
        results = []
        for bvid in selected:
            try:
                results.append(await asyncio.wait_for(execute(reader, 'watch', bvid), timeout=45))
            except (Exception, asyncio.TimeoutError):
                results.append({'kind':'viewing_failure', 'bvid':bvid,
                                'limitation':'本条在45秒内未完成分析或读取失败，不能声称已经看过；其他已完成结果保留。'})
        return {'kind':'search_and_view', 'keyword':target, 'items':results,
                'limitation':'优先选择10分钟以内的短视频，最多两条、每条最多45秒分析；逐条区分观看依据与失败。没有符合时长条件的结果时请换关键词，不冒充已观看。'}
    if operation == 'search':
        found = await reader.search_bilibili_videos(target, ps=3)
        return {'kind':'search_result', 'items':[
            {k:v[k] for k in ('bvid','title','author','duration') if k in v}
            for v in found], 'limitation':'这是搜索结果，尚未观看。'}
    if operation != 'watch':
        raise ValueError('unsupported operation')
    oid = await reader._get_video_oid(target)
    info = await reader._get_video_info(oid) if oid else None
    if not info:
        return {'kind':'viewing_failure', 'bvid':target, 'limitation':'未取得视频信息，未观看。'}
    info['oid'] = oid
    # The inner path has no access to BiliBot/global memories and performs no writes.
    summary = await reader._analyze_video_with_vision_inner(info)
    return {'kind':'viewing_experience', 'bvid':target, 'title':info['title'],
            'basis':info.get('analysis_basis','unknown'), 'summary':str(summary or '')[:1800],
            'diagnostics':info.get('_media_diagnostics', []),
            'limitation':f"最多分析前{getattr(reader, 'config', {}).get('VIDEO_SEGMENT_MAX_COUNT', 3)}分钟的稀疏抽帧，无音频；字幕可能错配。未覆盖部分不可推断。"}
