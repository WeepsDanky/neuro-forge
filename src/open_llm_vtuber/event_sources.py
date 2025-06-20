# src/open_llm_vtuber/event_sources.py
import asyncio
import datetime
import feedparser
import aiohttp
from typing import AsyncIterator, TypedDict, Literal
from loguru import logger


class Event(TypedDict):
    type: Literal["tick", "rss", "message"]
    payload: dict


async def _sleep_to_next(minute_interval: int):
    """Helper to sleep until the next interval boundary"""
    while True:
        now = datetime.datetime.utcnow()
        wait = minute_interval * 60 - (now.second + now.minute % minute_interval * 60)
        await asyncio.sleep(wait or 1)
        yield


async def time_source(interval_min: int = 5) -> AsyncIterator[Event]:
    """
    Generate periodic time-based events
    
    Args:
        interval_min: Interval in minutes between events
        
    Yields:
        Event with type "tick" and current UTC timestamp
    """
    logger.info(f"Starting time source with {interval_min} minute intervals")
    async for _ in _sleep_to_next(interval_min):
        logger.debug(f"Time source tick at {datetime.datetime.utcnow().isoformat()}")
        yield {"type": "tick", "payload": {"utc": datetime.datetime.utcnow().isoformat()}}


async def rss_source(url: str, poll_sec: int = 120) -> AsyncIterator[Event]:
    """
    Generate events from RSS feed updates
    
    Args:
        url: RSS feed URL
        poll_sec: Polling interval in seconds
        
    Yields:
        Event with type "rss" and feed entry data
    """
    logger.info(f"Starting RSS source for {url} with {poll_sec}s intervals")
    seen: set[str] = set()
    
    while True:
        try:
            logger.debug(f"Polling RSS feed: {url}")
            feed = feedparser.parse(url)
            
            for entry in feed.entries:
                if entry.id not in seen:
                    seen.add(entry.id)
                    logger.info(f"New RSS entry: {entry.title}")
                    yield {
                        "type": "rss", 
                        "payload": {
                            "title": entry.title, 
                            "link": entry.link,
                            "summary": getattr(entry, 'summary', ''),
                            "published": getattr(entry, 'published', '')
                        }
                    }
                    
        except Exception as e:
            logger.error(f"Error polling RSS feed {url}: {e}")
            
        await asyncio.sleep(poll_sec)


async def message_source(message_queue: asyncio.Queue) -> AsyncIterator[Event]:
    """
    Generate events from message queue (for custom events)
    
    Args:
        message_queue: AsyncIO queue to receive messages from
        
    Yields:
        Event with type "message" and custom payload
    """
    logger.info("Starting message source")
    while True:
        try:
            message = await message_queue.get()
            logger.debug(f"Message source received: {message}")
            yield {"type": "message", "payload": message}
        except Exception as e:
            logger.error(f"Error in message source: {e}") 