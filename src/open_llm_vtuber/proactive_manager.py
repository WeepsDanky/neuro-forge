# src/open_llm_vtuber/proactive_manager.py
import asyncio
import json
from typing import Iterable, Awaitable, AsyncIterator, Dict, Callable, Optional
from loguru import logger
from .agent.stateless_llm_factory import LLMFactory
from .event_sources import Event


class ProactiveChatManager:
    """Fan-in events from many sources and decide whether to ping the user."""

    def __init__(
        self,
        websocket_broadcast: Callable[[dict], Awaitable[None]],
        llm_cfg: Optional[dict] = None,
        rule_text: str = "Send a short friendly reminder every 5 minutes.",
        enabled: bool = True,
    ):
        """
        Initialize the proactive chat manager
        
        Args:
            websocket_broadcast: Function to broadcast messages to connected clients
            llm_cfg: LLM configuration for decision making
            rule_text: Default text for rule-based notifications
            enabled: Whether proactive chat is enabled
        """
        self._broadcast = websocket_broadcast
        self._rule_text = rule_text
        self._enabled = enabled
        self._running = False
        self._tasks = []
        
        # Initialize LLM if config provided
        if llm_cfg:
            try:
                self._llm = LLMFactory.create_llm(**llm_cfg)
                logger.info("ProactiveChatManager: LLM initialized for decision making")
            except Exception as e:
                logger.error(f"ProactiveChatManager: Failed to initialize LLM: {e}")
                self._llm = None
        else:
            self._llm = None
            logger.info("ProactiveChatManager: No LLM config provided, using rule-based only")

    async def _should_notify(self, event: Event) -> bool:
        """
        LLM-based decision on whether to notify users about an event
        
        Args:
            event: The event to evaluate
            
        Returns:
            True if users should be notified, False otherwise
        """
        if not self._llm:
            # Fallback to simple heuristics if no LLM
            if event["type"] == "rss":
                # Notify for RSS events with interesting keywords
                title = event["payload"].get("title", "").lower()
                keywords = ["episode", "new", "update", "release", "announced"]
                return any(keyword in title for keyword in keywords)
            return False

        try:
            messages = [
                {
                    "role": "system", 
                    "content": "You decide if an event needs a user notification. Reply with only YES or NO based on whether the event is interesting enough to notify users about."
                },
                {
                    "role": "user", 
                    "content": f"Event: {json.dumps(event, ensure_ascii=False, indent=2)}"
                }
            ]
            
            response_text = ""
            async for token in self._llm.chat_completion(messages):
                response_text += token.strip()
                
            answer = response_text.strip().upper()
            logger.debug(f"LLM decision for event {event['type']}: {answer}")
            
            return "YES" in answer
            
        except Exception as e:
            logger.error(f"Error in LLM decision making: {e}")
            return False

    async def _generate_proactive_message(self, event: Event) -> str:
        """
        Generate a proactive message based on the event
        
        Args:
            event: The event to generate a message for
            
        Returns:
            Generated message text
        """
        if event["type"] == "tick":
            return self._rule_text
            
        elif event["type"] == "rss":
            title = event["payload"].get("title", "Unknown")
            link = event["payload"].get("link", "")
            return f"📢 New update: {title}" + (f" - {link}" if link else "")
            
        elif event["type"] == "message":
            return event["payload"].get("text", "New message received")
            
        return "Something interesting happened!"

    async def _process_event(self, event: Event):
        """Process a single event and potentially broadcast a message"""
        if not self._enabled:
            return
            
        try:
            logger.debug(f"Processing event: {event['type']}")
            
            # Rule-based processing for tick events
            if event["type"] == "tick":
                message_text = await self._generate_proactive_message(event)
                payload = {
                    "type": "proactive_message", 
                    "text": message_text,
                    "source": "time_based"
                }
                await self._broadcast(payload)
                logger.info(f"Sent time-based proactive message: {message_text}")
                return

            # LLM-based or heuristic decision for other events
            if await self._should_notify(event):
                message_text = await self._generate_proactive_message(event)
                payload = {
                    "type": "proactive_message", 
                    "text": message_text,
                    "source": event["type"],
                    "event_data": event["payload"]
                }
                await self._broadcast(payload)
                logger.info(f"Sent {event['type']}-based proactive message: {message_text}")
            else:
                logger.debug(f"Event {event['type']} did not meet notification criteria")
                
        except Exception as e:
            logger.error(f"Error processing event {event['type']}: {e}")

    async def run(self, sources: Iterable[AsyncIterator[Event]]):
        """
        Main loop that fan-ins events from multiple sources
        
        Args:
            sources: Iterable of async iterators yielding events
        """
        if self._running:
            logger.warning("ProactiveChatManager is already running")
            return
            
        self._running = True
        logger.info("Starting ProactiveChatManager")

        async def fan_in(src: AsyncIterator[Event]):
            """Fan-in function to collect events from a source"""
            try:
                async for evt in src:
                    await queue.put(evt)
            except Exception as e:
                logger.error(f"Error in event source: {e}")

        queue: asyncio.Queue[Event] = asyncio.Queue()
        
        # Spawn one task per source
        self._tasks = [asyncio.create_task(fan_in(s)) for s in sources]
        logger.info(f"Started {len(self._tasks)} event source tasks")

        # Main event processing loop
        try:
            while self._running:
                evt = await queue.get()
                await self._process_event(evt)
                queue.task_done()
        except asyncio.CancelledError:
            logger.info("ProactiveChatManager was cancelled")
        except Exception as e:
            logger.error(f"Error in ProactiveChatManager main loop: {e}")
        finally:
            await self.stop()

    async def start_detached(self, *sources):
        """
        Convenience helper to start the manager in a detached task
        
        Args:
            *sources: Event sources to use
        """
        if sources:
            task = asyncio.create_task(self.run(sources))
            logger.info(f"Started ProactiveChatManager with {len(sources)} sources")
            return task
        else:
            logger.warning("No event sources provided to ProactiveChatManager")

    async def stop(self):
        """Stop the proactive chat manager and clean up tasks"""
        if not self._running:
            return
            
        logger.info("Stopping ProactiveChatManager")
        self._running = False
        
        # Cancel all source tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        self._tasks.clear()
        logger.info("ProactiveChatManager stopped")

    def enable(self):
        """Enable proactive chat"""
        self._enabled = True
        logger.info("Proactive chat enabled")

    def disable(self):
        """Disable proactive chat"""
        self._enabled = False
        logger.info("Proactive chat disabled")

    @property
    def is_enabled(self) -> bool:
        """Check if proactive chat is enabled"""
        return self._enabled

    @property
    def is_running(self) -> bool:
        """Check if the manager is running"""
        return self._running 