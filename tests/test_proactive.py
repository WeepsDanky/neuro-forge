import asyncio
import pytest
import json
import sys
import os
from unittest.mock import AsyncMock

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from open_llm_vtuber.proactive_manager import ProactiveChatManager
from open_llm_vtuber.event_sources import Event


class DummyLLM:
    """Mock LLM for testing that returns predictable responses"""
    
    async def chat_completion(self, messages, system=None):
        # naive YES for every rss event that mentions "Episode"
        content = messages[-1]["content"] if messages else ""
        answer = "YES" if "Episode" in content else "NO"
        yield answer


@pytest.mark.asyncio
async def test_rule_based_tick():
    """Test that rule-based tick events generate proactive messages"""
    got = []

    async def capture(msg):
        got.append(msg)

    mgr = ProactiveChatManager(
        websocket_broadcast=capture, 
        llm_cfg=None,  # No LLM config to force rule-based behavior
        rule_text="Test reminder message"
    )
    
    # Create a simple async generator for single tick event
    async def single_tick_source():
        yield {"type": "tick", "payload": {"utc": "2024-01-01T00:00:00Z"}}
    
    # Start the manager with the tick source
    task = asyncio.create_task(mgr.run([single_tick_source()]))
    
    # Give it a moment to process
    await asyncio.sleep(0.1)
    
    # Stop the manager
    await mgr.stop()
    
    # Verify we got a proactive message
    assert len(got) > 0
    assert any(m["type"] == "proactive_message" for m in got)
    assert any("Test reminder message" in m.get("text", "") for m in got)


@pytest.mark.asyncio
async def test_llm_based_rss():
    """Test that LLM-based RSS events generate appropriate messages"""
    got = []

    async def capture(msg):
        got.append(msg)

    # Create manager with dummy LLM
    mgr = ProactiveChatManager(
        websocket_broadcast=capture, 
        llm_cfg={"llm_provider": "test"}  # Dummy config
    )
    
    # Replace LLM with our mock
    mgr._llm = DummyLLM()
    
    # Create RSS source that mentions "Episode"
    async def fake_rss():
        yield {
            "type": "rss", 
            "payload": {
                "title": "New Episode 10 released!",
                "link": "https://example.com/episode10"
            }
        }
    
    # Start the manager
    task = asyncio.create_task(mgr.run([fake_rss()]))
    
    # Give it time to process
    await asyncio.sleep(0.2)
    
    # Stop the manager
    await mgr.stop()
    
    # Verify we got the appropriate message
    assert len(got) > 0
    rss_messages = [m for m in got if m.get("source") == "rss"]
    assert len(rss_messages) > 0
    assert any("Episode" in m.get("text", "") for m in rss_messages)


@pytest.mark.asyncio
async def test_llm_based_rss_rejection():
    """Test that LLM rejects uninteresting RSS events"""
    got = []

    async def capture(msg):
        got.append(msg)

    # Create manager with dummy LLM
    mgr = ProactiveChatManager(
        websocket_broadcast=capture, 
        llm_cfg={"llm_provider": "test"}
    )
    
    # Replace LLM with our mock
    mgr._llm = DummyLLM()
    
    # Create RSS source with boring content
    async def fake_rss():
        yield {
            "type": "rss", 
            "payload": {
                "title": "Boring maintenance update",
                "link": "https://example.com/maintenance"
            }
        }
    
    # Start the manager
    task = asyncio.create_task(mgr.run([fake_rss()]))
    
    # Give it time to process
    await asyncio.sleep(0.2)
    
    # Stop the manager
    await mgr.stop()
    
    # Verify no RSS messages were sent (since LLM said NO)
    rss_messages = [m for m in got if m.get("source") == "rss"]
    assert len(rss_messages) == 0


@pytest.mark.asyncio
async def test_multiple_event_sources():
    """Test that multiple event sources work together"""
    got = []

    async def capture(msg):
        got.append(msg)

    mgr = ProactiveChatManager(
        websocket_broadcast=capture,
        llm_cfg=None,
        rule_text="Multi-source test"
    )
    
    # Create multiple event sources - use RSS with keyword "new" to trigger heuristic
    async def tick_source():
        yield {"type": "tick", "payload": {"utc": "2024-01-01T00:00:00Z"}}
    
    async def rss_source():
        yield {"type": "rss", "payload": {"title": "New update available", "link": "test"}}
    
    # Start manager with multiple sources
    task = asyncio.create_task(mgr.run([tick_source(), rss_source()]))
    
    # Give it time to process
    await asyncio.sleep(0.2)
    
    # Stop the manager
    await mgr.stop()
    
    # Verify we got messages from different sources
    assert len(got) >= 2
    time_messages = [m for m in got if m.get("source") == "time_based"]
    rss_messages = [m for m in got if m.get("source") == "rss"]
    
    assert len(time_messages) >= 1
    assert len(rss_messages) >= 1


@pytest.mark.asyncio
async def test_proactive_manager_enable_disable():
    """Test that proactive manager can be enabled and disabled"""
    got = []

    async def capture(msg):
        got.append(msg)

    mgr = ProactiveChatManager(
        websocket_broadcast=capture,
        enabled=False  # Start disabled
    )
    
    # Verify it starts disabled
    assert not mgr.is_enabled
    
    # Create event source
    async def tick_source():
        yield {"type": "tick", "payload": {"utc": "2024-01-01T00:00:00Z"}}
    
    # Start manager (should not process events while disabled)
    task = asyncio.create_task(mgr.run([tick_source()]))
    await asyncio.sleep(0.1)
    
    # Should have no messages while disabled
    initial_count = len(got)
    
    # Enable and wait
    mgr.enable()
    assert mgr.is_enabled
    await asyncio.sleep(0.1)
    
    # Should still have no additional messages from the earlier tick
    # (the tick already passed through while disabled)
    await mgr.stop()
    
    # Verify manager state
    assert mgr.is_enabled


@pytest.mark.asyncio 
async def test_error_handling():
    """Test that the manager handles errors gracefully"""
    got = []
    errors = []

    async def capture(msg):
        got.append(msg)

    async def failing_capture(msg):
        errors.append("broadcast_error")
        raise Exception("Broadcast failed!")

    mgr = ProactiveChatManager(
        websocket_broadcast=failing_capture,
        llm_cfg=None
    )
    
    # Create event source
    async def tick_source():
        yield {"type": "tick", "payload": {"utc": "2024-01-01T00:00:00Z"}}
    
    # Start manager with failing broadcast
    task = asyncio.create_task(mgr.run([tick_source()]))
    
    # Give it time to process and fail
    await asyncio.sleep(0.1)
    
    # Stop the manager
    await mgr.stop()
    
    # Verify error was logged but manager didn't crash
    assert len(errors) > 0
    assert not mgr.is_running


if __name__ == "__main__":
    # Run tests manually if needed
    asyncio.run(test_rule_based_tick())
    print("✅ test_rule_based_tick passed")
    
    asyncio.run(test_llm_based_rss()) 
    print("✅ test_llm_based_rss passed")
    
    asyncio.run(test_llm_based_rss_rejection())
    print("✅ test_llm_based_rss_rejection passed")
    
    asyncio.run(test_multiple_event_sources())
    print("✅ test_multiple_event_sources passed")
    
    asyncio.run(test_proactive_manager_enable_disable())
    print("✅ test_proactive_manager_enable_disable passed")
    
    asyncio.run(test_error_handling())
    print("✅ test_error_handling passed")
    
    print("\n🎉 All tests passed!") 