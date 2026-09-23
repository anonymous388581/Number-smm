import aiohttp
import asyncio
import logging
import os
import time
from config import logger
from database import to_usd

def _smm_server_config(server, name, url, currency):
    return {
        'name': name,
        'url': url,
        'key': os.getenv(f'SMM_SERVER_{server}_KEY', '').strip(),
        'currency': currency
    }


SMM_SERVERS = {
    1: _smm_server_config(1, '𝐕𝐈𝐏 𝐒ᴇʀᴠᴇʀ 1 (𝐅ᴀsᴛ & 𝐈ɴsᴛᴀɴᴛ)', 'https://fathersmm.com/api/v2', 'INR'),
    2: _smm_server_config(2, '𝐁ᴜᴅɢᴇᴛ 𝐒ᴇʀᴠᴇʀ 2 (𝐂ʜᴇᴀᴘᴇsᴛ 𝐑ᴀᴛᴇ)', 'https://best-smm.com/api/v2', 'USD')
}

def _normalize_server(server):
    try:
        server = int(server)
    except (TypeError, ValueError):
        return None
    return server if server in SMM_SERVERS else None


def _get_smm_server(server):
    server = _normalize_server(server)
    if server is None:
        logger.error('SMM server selection is invalid')
        return None
    srv = SMM_SERVERS[server]
    missing = []
    if not srv['key']:
        missing.append(f'SMM_SERVER_{server}_KEY')
    if missing:
        logger.error(
            'SMM server %s is not configured; missing environment variable(s): %s',
            server,
            ', '.join(missing),
        )
        return None
    return srv

_services_cache = {1: None, 2: None}
_cache_time = {1: 0, 2: 0}

PLATFORM_KEYWORDS = {
    'Telegram': ['telegram', 'tg '],
    'Instagram': ['instagram', 'ig '],
    'WhatsApp': ['whatsapp', 'wa '],
    'YouTube': ['youtube', 'yt '],
    'Facebook': ['facebook', 'fb '],
    'TikTok': ['tiktok', 'tik tok'],
    'Twitter/X': ['twitter', 'x -', 'x /']
}

PLATFORM_ICONS = {
    'Telegram': '✈️',
    'Instagram': '📸',
    'WhatsApp': '💬',
    'YouTube': '▶️',
    'Facebook': '📘',
    'TikTok': '🎵',
    'Twitter/X': '🐦',
    'Other Services': '🌐'
}

PLATFORM_PREMIUM_ICONS = {
    'Telegram': 5408995930416362034,
    'Instagram': 5409271925014801629,
    'WhatsApp': 5440627033111557670,
    'YouTube': 5409320020058584473,
    'Facebook': 6154249597532248059,
    'TikTok': 6203982793379154737,
    'Twitter/X': 6129732880529628243,
    'Other Services': 6129399728506412489
}

async def fetch_smm_services(server=1, force_refresh=False):
    global _services_cache, _cache_time
    server = _normalize_server(server)
    if server is None:
        return []
    now = time.time()
    if not force_refresh and _services_cache.get(server) and (now - _cache_time.get(server, 0) < 600):
        return _services_cache[server]
        
    srv = _get_smm_server(server)
    if srv is None:
        return _services_cache.get(server) or []
    params = {
        'key': srv['key'],
        'action': 'services'
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(srv['url'], data=params, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if isinstance(data, list):
                        _services_cache[server] = data
                        _cache_time[server] = now
                        return data
                    logger.error("SMM services returned a non-list response for server %s", server)
                else:
                    logger.error("SMM services request failed for server %s with HTTP status %s", server, resp.status)
    except Exception as ex:
        logger.error("SMM fetch_services error for server %s: %s", server, type(ex).__name__)
        
    return _services_cache.get(server) or []

def detect_platform(category_name):
    c_lower = (category_name or '').lower()
    for plat, keywords in PLATFORM_KEYWORDS.items():
        for kw in keywords:
            if kw in c_lower:
                return plat
    return 'Other Services'

async def get_smm_platforms(server=1):
    services = await fetch_smm_services(server)
    found_platforms = set()
    for s in services:
        cat = s.get('category', '')
        plat = detect_platform(cat)
        found_platforms.add(plat)
    
    # Return in clean sorted order with popular first
    order = ['Telegram', 'Instagram', 'WhatsApp', 'YouTube', 'Facebook', 'TikTok', 'Twitter/X', 'Other Services']
    return [p for p in order if p in found_platforms]

async def get_categories_for_platform(platform, server=1):
    services = await fetch_smm_services(server)
    cats = []
    seen = set()
    for s in services:
        cat = s.get('category', '').strip()
        if not cat or cat in seen:
            continue
        if detect_platform(cat) == platform:
            seen.add(cat)
            # count services
            count = sum(1 for item in services if item.get('category', '').strip() == cat)
            cats.append({'name': cat, 'count': count})
    return cats

async def get_services_for_category(category_name, server=1):
    services = await fetch_smm_services(server)
    return [s for s in services if s.get('category', '').strip() == category_name.strip()]

async def get_smm_service_details(service_id, server=1):
    services = await fetch_smm_services(server)
    for s in services:
        if str(s.get('service')) == str(service_id):
            return s
    return None

def get_service_inr_rate(service, server=1):
    rate_raw = float(service.get('rate', 0) or 0)
    srv = SMM_SERVERS.get(server, SMM_SERVERS[1])
    if srv['currency'] == 'USD':
        # USD to INR conversion (e.g. rate in USD * 90)
        from database import get_usdt_rate
        usd_inr = get_usdt_rate() or 90.0
        return round(rate_raw * usd_inr, 2)
    return round(rate_raw, 2)

async def create_smm_order(service_id, link, quantity, server=1):
    srv = _get_smm_server(server)
    if srv is None:
        return {'error': f'SMM server {server} is not configured.'}
    params = {
        'key': srv['key'],
        'action': 'add',
        'service': str(service_id),
        'link': str(link).strip(),
        'quantity': str(quantity).strip()
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(srv['url'], data=params, timeout=20) as resp:
                data = await resp.json(content_type=None)
                return data
    except Exception as ex:
        logger.error("SMM create_order error for server %s: %s", server, type(ex).__name__)
        return {'error': 'SMM provider request failed.'}

async def get_smm_order_status(order_id, server=1):
    srv = _get_smm_server(server)
    if srv is None:
        return {'error': f'SMM server {server} is not configured.'}
    params = {
        'key': srv['key'],
        'action': 'status',
        'order': str(order_id).strip()
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(srv['url'], data=params, timeout=15) as resp:
                data = await resp.json(content_type=None)
                return data
    except Exception as ex:
        logger.error("SMM get_order_status error for server %s: %s", server, type(ex).__name__)
        return {'error': 'SMM provider request failed.'}
