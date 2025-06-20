# Proactive Chat Feature

The proactive chat feature allows your VTuber to automatically initiate conversations and share updates with users without waiting for user input. This creates a more engaging, live experience where your AI character can:

- Send periodic friendly reminders
- Announce new content from RSS feeds
- Share system alerts or updates
- Respond to custom events in your application

## How It Works

```
           ┌─────────────────────────┐
           │  EventSource (async)    │  ←─ Time ticks, RSS, etc.
           └──────────┬──────────────┘
                      │  `async for evt in source.events(): …`
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  ProactiveChatManager                                          │
│  • fan-in from many sources                                    │
│  • *rule based*  : cron / every X minutes                      │
│  • *LLM based*   : "Should I ping the user about this?"        │
│  • emits `proactive_message`                                   │
└──────────┬─────────────────────────────────────────────────────┘
           │
           ▼
   WebSocketHandler.broadcast_to_group(...)
           │
           ▼
      Discord / Telegram bot receives
```

## Event Sources

### 1. Time-based Events (`time_source`)

Generates periodic events at specified intervals:

```python
from open_llm_vtuber.event_sources import time_source

# Send message every 5 minutes
time_source(interval_min=5)
```

### 2. RSS Feed Events (`rss_source`)

Monitors RSS feeds and generates events for new entries:

```python
from open_llm_vtuber.event_sources import rss_source

# Monitor an RSS feed every 2 minutes
rss_source("https://example.com/feed.xml", poll_sec=120)
```

### 3. Custom Message Events (`message_source`)

Allows your application to inject custom events:

```python
from open_llm_vtuber.event_sources import message_source
import asyncio

# Create a queue for custom events
event_queue = asyncio.Queue()

# Add the source
message_source(event_queue)

# Later, inject a custom event
await event_queue.put({
    "text": "A new user just joined!",
    "user_id": "12345"
})
```

## Decision Making

The ProactiveChatManager decides whether to send messages using two methods:

### Rule-based (Default)
- **Time events**: Always send the configured rule text
- **RSS events**: Send if title contains keywords like "new", "update", "release", "announced", "episode"
- **Custom events**: Never send by default

### LLM-based (Optional)
If you provide an LLM configuration, the system will ask the LLM whether each event warrants a user notification:

```python
llm_config = {
    "llm_provider": "openai_compatible_llm",
    "model": "gpt-4o-mini",
    "base_url": "https://api.openai.com/v1",
    "llm_api_key": "your-api-key"
}
```

## Configuration

The proactive chat feature is automatically initialized when the WebSocket server starts. You can customize it by modifying the `_init_proactive_chat()` method in `websocket_handler.py`:

```python
# Enable/disable proactive chat
enabled=True

# Change the time interval
time_source(interval_min=10)  # Every 10 minutes

# Add RSS feeds
rss_source("https://your-rss-feed.com/feed.xml", poll_sec=300)

# Customize the friendly message
rule_text="🌟 Hi there! Your VTuber friend is thinking of you!"
```

## Message Format

Proactive messages are sent with this structure:

```json
{
    "type": "proactive_message",
    "text": "📢 New update: Episode 10 released!",
    "source": "rss",
    "event_data": {
        "title": "Episode 10 released!",
        "link": "https://example.com/episode10",
        "summary": "...",
        "published": "2024-01-01T00:00:00Z"
    }
}
```

## Integration with Bots

The existing Discord and Telegram bots automatically handle proactive messages through the WebSocket broadcast system. No additional bot code is needed!

When a proactive message is generated:
1. WebSocketHandler broadcasts it to all connected clients
2. Bot clients receive the message via WebSocket
3. Bots forward the message to their respective platforms

## Testing

Run the comprehensive test suite:

```bash
uv run pytest tests/test_proactive.py -v
```

Or run the interactive demo:

```bash
uv run python examples/proactive_chat_demo.py
```

## Examples

### Basic Setup

```python
from open_llm_vtuber.proactive_manager import ProactiveChatManager
from open_llm_vtuber.event_sources import time_source

async def my_broadcast_handler(message: dict):
    print(f"Proactive message: {message['text']}")

manager = ProactiveChatManager(
    websocket_broadcast=my_broadcast_handler,
    rule_text="Hello from your AI friend!"
)

# Start with time-based events only
await manager.start_detached(
    time_source(interval_min=5)
)
```

### Advanced Setup with LLM

```python
# Include LLM for intelligent decisions
llm_config = {
    "llm_provider": "openai_compatible_llm",
    "model": "gpt-4o-mini",
    "base_url": "https://api.openai.com/v1",
    "llm_api_key": "your-key"
}

manager = ProactiveChatManager(
    websocket_broadcast=my_broadcast_handler,
    llm_cfg=llm_config,
    rule_text="🌟 Your AI companion is here!"
)

# Start with multiple event sources
await manager.start_detached(
    time_source(interval_min=10),
    rss_source("https://news.example.com/feed.xml"),
    message_source(custom_event_queue)
)
```

### Custom Event Source

Create your own event source for specific application needs:

```python
async def database_events():
    """Monitor database for new user registrations"""
    while True:
        # Check database for new users
        new_users = await check_new_users()
        for user in new_users:
            yield {
                "type": "user_registration",
                "payload": {
                    "username": user.name,
                    "join_date": user.created_at.isoformat()
                }
            }
        await asyncio.sleep(60)  # Check every minute
```

## Best Practices

1. **Frequency**: Don't set time intervals too short (< 5 minutes) to avoid spamming users
2. **RSS Feeds**: Use reputable feeds with consistent update patterns
3. **LLM Decision**: Enable LLM-based decisions for better content filtering
4. **Error Handling**: The system gracefully handles RSS feed failures and LLM errors
5. **Performance**: Event sources run in separate async tasks for optimal performance

## Troubleshooting

### Common Issues

**"No clients connected for proactive message"**
- This is normal when no users are online. Messages are only sent to connected clients.

**RSS feed not working**
- Check the feed URL is accessible
- Verify the feed format is valid XML
- Check network connectivity

**LLM not making decisions**
- Verify LLM configuration is correct
- Check API keys and endpoints
- System falls back to rule-based decisions if LLM fails

### Debug Mode

Enable debug logging to see detailed event processing:

```python
import logging
logging.getLogger("open_llm_vtuber.proactive_manager").setLevel(logging.DEBUG)
```

## Future Enhancements

Potential additions to the proactive chat system:

- Database event sources
- Webhook event sources  
- Social media monitoring
- System health monitoring
- User preference-based filtering
- Advanced scheduling (specific times/days)

## API Reference

### ProactiveChatManager

```python
class ProactiveChatManager:
    def __init__(
        self,
        websocket_broadcast: Callable[[dict], Awaitable[None]],
        llm_cfg: Optional[dict] = None,
        rule_text: str = "Default message",
        enabled: bool = True,
    )
    
    async def run(self, sources: Iterable[AsyncIterator[Event]])
    async def start_detached(self, *sources) -> asyncio.Task
    async def stop(self)
    def enable(self)
    def disable(self)
    
    @property
    def is_enabled(self) -> bool
    
    @property  
    def is_running(self) -> bool
```

### Event Sources

```python
async def time_source(interval_min: int = 5) -> AsyncIterator[Event]
async def rss_source(url: str, poll_sec: int = 120) -> AsyncIterator[Event]  
async def message_source(message_queue: asyncio.Queue) -> AsyncIterator[Event]
```

---

*This feature makes your VTuber more engaging by creating the feeling of a living, breathing character that stays connected with users even when they're not actively chatting!* 🌟 