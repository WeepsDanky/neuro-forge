#!/usr/bin/env python3
"""
Proactive Chat Feature Demo

This script demonstrates the new proactive chat feature for open-llm-vtuber.
It shows how the system can automatically generate messages based on:
1. Time-based events (periodic reminders)
2. RSS feed updates
3. Custom events

Run this script to see the proactive chat system in action!
"""

import asyncio
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from open_llm_vtuber.proactive_manager import ProactiveChatManager
from open_llm_vtuber.event_sources import time_source, rss_source, Event


class DemoLLM:
    """Demo LLM that makes decisions based on simple heuristics"""
    
    async def chat_completion(self, messages, system=None):
        content = messages[-1]["content"]
        
        # Simulate LLM decision making
        if any(keyword in content.lower() for keyword in ["new", "release", "update", "announced"]):
            yield "YES"
        else:
            yield "NO"


async def demo_broadcast_handler(message: dict):
    """Demo handler that prints proactive messages to console"""
    msg_type = message.get("type", "unknown")
    source = message.get("source", "unknown")
    text = message.get("text", "")
    
    print(f"\n🔔 PROACTIVE MESSAGE ({source}):")
    print(f"   Type: {msg_type}")
    print(f"   Text: {text}")
    
    if message.get("event_data"):
        print(f"   Event Data: {message['event_data']}")
    
    print("-" * 50)


async def create_demo_rss_source():
    """Create a demo RSS source that simulates real RSS updates"""
    demo_entries = [
        {"title": "New anime episode released!", "link": "https://example.com/ep1"},
        {"title": "Server maintenance scheduled", "link": "https://example.com/maintenance"},
        {"title": "Game update 2.0 announced", "link": "https://example.com/update"},
        {"title": "Daily weather report", "link": "https://example.com/weather"},
    ]
    
    for i, entry in enumerate(demo_entries):
        await asyncio.sleep(3)  # Simulate RSS polling interval
        yield {
            "type": "rss",
            "payload": {
                "title": entry["title"],
                "link": entry["link"],
                "summary": f"Demo RSS entry #{i+1}",
                "published": "2024-01-01T00:00:00Z"
            }
        }


async def create_demo_custom_events():
    """Create custom events to demonstrate flexibility"""
    await asyncio.sleep(5)
    yield {
        "type": "message",
        "payload": {
            "text": "A user just joined the chat!",
            "user": "demo_user"
        }
    }
    
    await asyncio.sleep(7)
    yield {
        "type": "message", 
        "payload": {
            "text": "System performance alert detected",
            "severity": "warning"
        }
    }


async def main():
    """Main demo function"""
    print("🌟 Open LLM VTuber - Proactive Chat Demo")
    print("=" * 50)
    print("This demo shows how the proactive chat feature works.")
    print("The system will generate messages based on:")
    print("• ⏰ Time-based events (every 15 seconds)")
    print("• 📰 RSS feed updates (simulated)")
    print("• 💬 Custom events")
    print("\nPress Ctrl+C to stop the demo.\n")
    
    # Configure the proactive chat manager
    llm_config = {
        "llm_provider": "demo"  # Demo config
    }
    
    manager = ProactiveChatManager(
        websocket_broadcast=demo_broadcast_handler,
        llm_cfg=llm_config,
        rule_text="🌟 Hello! This is a friendly reminder from your VTuber assistant!",
        enabled=True
    )
    
    # Replace with demo LLM
    manager._llm = DemoLLM()
    
    print("🚀 Starting proactive chat manager...")
    
    try:
        # Start the manager with multiple event sources
        await manager.run([
            time_source(interval_min=0.25),  # Every 15 seconds for demo
            create_demo_rss_source(),
            create_demo_custom_events(),
        ])
    except KeyboardInterrupt:
        print("\n\n⏹️ Demo stopped by user")
    except Exception as e:
        print(f"\n❌ Demo error: {e}")
    finally:
        await manager.stop()
        print("✅ Proactive chat manager stopped")


if __name__ == "__main__":
    print("Running proactive chat demo...")
    print("Note: In a real application, these messages would be sent to")
    print("Discord, Telegram, or the web interface automatically!\n")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n�� Demo finished!") 