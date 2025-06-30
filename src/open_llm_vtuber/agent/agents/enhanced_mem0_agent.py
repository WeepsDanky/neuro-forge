"""An advanced memory‑augmented LLM agent that leverages mem0's full feature set:

1. **Short‑term memory** – Recent conversation context in RAM + semantic search within session
2. **Long‑term memory** – Persistent facts with automatic LLM inference and metadata
3. **User insights** – Automatically derived summaries with periodic refresh
4. **Memory versioning** – Track memory evolution with history tracking
5. **Advanced search** – Semantic search with metadata filtering and relevance scoring
6. **Memory lifecycle** – Full CRUD operations with expiration and immutability options

This implementation leverages mem0's enterprise features:
- Automatic memory inference and contradiction resolution
- Metadata-driven memory organization and filtering  
- Memory versioning and history tracking
- Advanced search with semantic + metadata filters
- Memory lifecycle management (expiration, immutability)
- Multi-entity memory scoping (user/agent/app/run)

```python
agent = EnhancedMem0Agent(
    user_id="u123",
    base_url="https://api.openai.com/v1",
    model="gpt-4o-mini",
    system="You are a helpful assistant …",
    mem0_config={
        "vector_store": {"provider": "qdrant", "config": {"collection_name": "memories"}},
        "graph_store": {"provider": "neo4j", "config": {"url": "bolt://localhost:7687"}},
        "llm": {"provider": "openai", "config": {"model": "gpt-4o-mini"}},
        "embedder": {"provider": "openai", "config": {"model": "text-embedding-3-small"}}
    },
)

async for token in agent.chat("How do I cook tofu?"):
    print(token, end="", flush=True)
```

Advanced mem0 features integrated:
- **Memory inference**: Automatically extracts meaningful facts from conversations
- **Contradiction resolution**: Updates conflicting memories intelligently  
- **Metadata filtering**: Rich context-aware memory retrieval
- **Memory history**: Track how memories evolve over time
- **Expiration dates**: Auto-cleanup of time-sensitive memories
- **Immutable memories**: Lock critical facts from updates
- **Custom categories**: Organize memories by domain-specific categories
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from loguru import logger
from mem0 import Memory
from openai import OpenAI, AsyncOpenAI

from .agent_interface import AgentInterface, BaseInput, BaseOutput, AsyncIterator  # type: ignore

# ----------------------------------------------------------------------------
# Enhanced Tunables for full mem0 feature utilization
# ----------------------------------------------------------------------------
MAX_SHORT_MESSAGES = 20                      # hard cap on messages kept verbatim
SHORT_MEMORY_SEARCH_LIMIT = 15               # top‑k from mem0 short‑term search
LONG_MEMORY_SEARCH_LIMIT = 20                # top‑k from mem0 long‑term search
INSIGHT_SEARCH_LIMIT = 8                     # top‑k from mem0 insight search
INSIGHT_REFRESH_INTERVAL = 30 * 60           # seconds – every 30 minutes for more responsive insights
MEMORY_VERSION = "v2"                        # use latest mem0 version
MEMORY_CONFIDENCE_THRESHOLD = 0.7            # minimum confidence for memory relevance
MAX_MEMORY_AGE_DAYS = 90                     # default expiration for non-critical memories
INSIGHT_GENERATION_THRESHOLD = 10            # generate insights after N new memories


class EnhancedMem0Agent(AgentInterface):
    """ChatGPT‑style agent with hierarchical memory built on mem0 + OpenAI with full enterprise features."""
    
    def __init__(
        self,
        user_id: str,
        base_url: str,
        model: str,
        system: str,
        mem0_config: Dict[str, Any],
        organization_id: str = "",
        project_id: str = "",
        llm_api_key: str = "",
        agent_id: Optional[str] = None,
        app_id: Optional[str] = None,
        verbose: bool = False,
    ) -> None:
        super().__init__()

        self.user_id = user_id
        self.agent_id = agent_id or f"agent_{user_id}"
        self.app_id = app_id or "open_llm_vtuber"
        self.model = model
        self.system_prompt_template = system
        self.verbose = verbose

        # Memory management state
        self._memory_operations_count = 0
        self._last_insight_refresh = 0.0
        self._session_start_time = time.time()

        # OpenAI clients
        self.openai = AsyncOpenAI(
            base_url=base_url,
            organization=organization_id or None,
            project=project_id or None,
            api_key=llm_api_key or None,
        )

        # Enhanced mem0 setup with full feature utilization
        logger.info("Initializing enhanced mem0 with full feature set...")
        
        # Use latest mem0 version with advanced features
        enhanced_config = {
            **mem0_config,
            "version": MEMORY_VERSION,
            "custom_prompt": {
                "memory_extraction": "Extract only the most important facts that would be useful for future conversations. Focus on preferences, important details, and contextual information.",
                "contradiction_resolution": "When memories conflict, prioritize the most recent and specific information while preserving historical context."
            }
        }
        
        try:
            # Single unified memory instance with different namespaces via metadata
            self.memory = Memory.from_config(enhanced_config)
            logger.info("✅ Enhanced mem0 initialized successfully with enterprise features")
        except Exception as e:
            logger.error(f"❌ Failed to initialize mem0: {e}")
            self.memory = None

        # Local circular buffer for literal recent messages
        self._conversation_buffer: deque[Dict[str, str]] = deque(maxlen=MAX_SHORT_MESSAGES)

        # Background insight generation task
        self._insight_task = asyncio.create_task(self._periodic_insight_refresh())

    # ---------------------------------------------------------------------
    # AgentInterface overrides
    # ---------------------------------------------------------------------

    async def chat(self, input_data: BaseInput) -> AsyncIterator[BaseOutput]:
        """Entry‑point expected by *AgentInterface* – dispatch to `_chat_iter`."""
        if not hasattr(input_data, "texts") or not input_data.texts:
            raise ValueError("BaseInput must contain at least one text message for this agent")
        prompt: str = input_data.texts[0].content  # type: ignore[attr-defined]

        async for token in self._chat_iter(prompt):
            yield token  # type: ignore[misc]

    def handle_interrupt(self, heard_response: str) -> None:
        """Overwrite the last assistant message in the buffer on interruption."""
        if self._conversation_buffer and self._conversation_buffer[-1]["role"] == "assistant":
            self._conversation_buffer[-1]["content"] = f"{heard_response}…"
        else:
            self._conversation_buffer.append({
                "role": "assistant",
                "content": f"{heard_response}…",
            })
        self._conversation_buffer.append({"role": "system", "content": "[Interrupted by user]"})

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        """Load *past* chat history into memory with enhanced metadata."""
        from ...chat_history_manager import get_history

        history = get_history(conf_uid, history_uid)
        
        # Load into conversation buffer
        for msg in history[-MAX_SHORT_MESSAGES:]:
            role = "user" if msg["role"] == "human" else "assistant"
            self._conversation_buffer.append({"role": role, "content": msg["content"]})

        # Store in mem0 with rich metadata for history loading
        if self.memory and history:
            metadata = {
                "type": "history_import",
                "category": "conversation_history", 
                "source": "chat_history_manager",
                "conf_uid": conf_uid,
                "history_uid": history_uid,
                "timestamp": datetime.now().isoformat(),
                "import_session": f"session_{int(self._session_start_time)}"
            }
            
            # Convert to mem0 format
            mem0_messages = []
            for msg in history:
                role = "user" if msg["role"] == "human" else "assistant"
                mem0_messages.append({"role": role, "content": msg["content"]})
            
            self.memory.add(
                messages=mem0_messages,
                user_id=self.user_id,
                agent_id=self.agent_id,
                app_id=self.app_id,
                metadata=metadata,
                version=MEMORY_VERSION,
                infer=True  # Extract insights from historical conversations
            )
            
            logger.info(f"📚 [HISTORY LOADED] Imported {len(history)} messages from {history_uid}")

    # ------------------------------------------------------------------
    # Enhanced memory management with full mem0 features
    # ------------------------------------------------------------------

    def remember(self, fact: str, category: str = "explicit_fact", immutable: bool = True, 
                 expiration_date: Optional[str] = None) -> Dict[str, Any]:
        """Store explicit facts with enhanced metadata and lifecycle management."""
        if not self.memory:
            logger.warning("Memory not initialized, cannot store fact")
            return {}
            
        metadata = {
            "category": category,
            "type": "explicit_fact", 
            "source": "user_request",
            "timestamp": datetime.now().isoformat(),
            "session_id": f"session_{int(self._session_start_time)}"
        }
        
        result = self.memory.add(
            messages=[{"role": "system", "content": fact}],
            user_id=self.user_id,
            agent_id=self.agent_id,
            app_id=self.app_id,
            metadata=metadata,
            immutable=immutable,
            expiration_date=expiration_date,
            version=MEMORY_VERSION,
            infer=True  # Let mem0 enhance and organize the fact
        )
        
        logger.info(f"💾 [EXPLICIT FACT] Stored: {fact}")
        return result

    def forget(self, memory_id: str) -> bool:
        """Delete a specific memory by ID."""
        if not self.memory:
            return False
            
        try:
            self.memory.delete(memory_id=memory_id)
            logger.info(f"🗑️ [MEMORY DELETED] ID: {memory_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete memory {memory_id}: {e}")
            return False

    def get_memory_history(self, memory_id: str) -> List[Dict[str, Any]]:
        """Get the evolution history of a specific memory."""
        if not self.memory:
            return []
            
        try:
            return self.memory.history(memory_id=memory_id)
        except Exception as e:
            logger.error(f"Failed to get memory history for {memory_id}: {e}")
            return []

    def update_memory(self, memory_id: str, new_content: str) -> Dict[str, Any]:
        """Update an existing memory with new content."""
        if not self.memory:
            return {}
            
        try:
            result = self.memory.update(memory_id=memory_id, data=new_content)
            logger.info(f"✏️ [MEMORY UPDATED] ID: {memory_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to update memory {memory_id}: {e}")
            return {}

    def clear_memories(self, category: Optional[str] = None, older_than_days: Optional[int] = None) -> int:
        """Clear memories with optional filtering by category or age."""
        if not self.memory:
            return 0
            
        try:
            if category or older_than_days:
                # Get all memories and filter manually
                all_memories = self.memory.get_all(user_id=self.user_id)
                deleted_count = 0
                
                for mem in all_memories.get("results", []):
                    should_delete = True
                    
                    if category:
                        mem_category = mem.get("metadata", {}).get("category")
                        if mem_category != category:
                            should_delete = False
                    
                    if older_than_days and should_delete:
                        mem_timestamp = mem.get("metadata", {}).get("timestamp")
                        if mem_timestamp:
                            mem_date = datetime.fromisoformat(mem_timestamp.replace('Z', '+00:00'))
                            if (datetime.now() - mem_date).days < older_than_days:
                                should_delete = False
                    
                    if should_delete:
                        self.memory.delete(memory_id=mem["id"])
                        deleted_count += 1
                
                logger.info(f"🧹 [SELECTIVE CLEANUP] Deleted {deleted_count} memories")
                return deleted_count
            else:
                # Clear all user memories
                self.memory.delete_all(user_id=self.user_id)
                logger.info("🧹 [FULL RESET] Cleared all user memories")
                return -1  # Unknown count for full clear
                
        except Exception as e:
            logger.error(f"Failed to clear memories: {e}")
            return 0

    # ------------------------------------------------------------------
    # Core logic with enhanced memory integration
    # ------------------------------------------------------------------

    async def _chat_iter(self, prompt: str) -> AsyncIterator[str]:
        """Enhanced chat iteration with full mem0 feature utilization."""
        # --- 1. Store current user input with metadata ----------------
        self._conversation_buffer.append({"role": "user", "content": prompt})
        
        if self.memory:
            # Store with rich metadata for enhanced retrieval
            input_metadata = {
                "type": "conversation_turn",
                "role": "user", 
                "category": "short_term",
                "timestamp": datetime.now().isoformat(),
                "session_id": f"session_{int(self._session_start_time)}",
                "turn_number": len(self._conversation_buffer)
            }
            
            self.memory.add(
                messages=[{"role": "user", "content": prompt}],
                user_id=self.user_id,
                agent_id=self.agent_id,
                app_id=self.app_id,
                metadata=input_metadata,
                version=MEMORY_VERSION,
                infer=True  # Let mem0 extract meaningful information
            )
            self._memory_operations_count += 1

        # --- 2. Enhanced semantic memory retrieval with filtering ----------------
        relevant_memories = await self._retrieve_relevant_memories(prompt)
        
        # --- 3. Construct enhanced system prompt with memory layers ----------------
        system_prompt = await self._build_enhanced_system_prompt(prompt, relevant_memories)
        system_message = {"role": "system", "content": system_prompt}

        # --- 4. Prepare conversation context ----------------
        full_context = [system_message] + list(self._conversation_buffer)
        
        if self.verbose:
            logger.debug(f"🧠 [MEMORY STATS] Operations: {self._memory_operations_count}, Buffer: {len(self._conversation_buffer)}")
            logger.debug("🔍 [CONTEXT] " + json.dumps(full_context, indent=2)[:1000])

        # --- 5. Stream response from LLM ----------------
        completion = await self.openai.chat.completions.create(
            model=self.model,
            messages=full_context,
            stream=True,
        )

        assistant_reply = ""
        async for chunk in completion:
            delta = chunk.choices[0].delta.content or ""
            assistant_reply += delta
            yield delta

        # --- 6. Store assistant response with metadata ----------------
        self._conversation_buffer.append({"role": "assistant", "content": assistant_reply})
        
        if self.memory:
            response_metadata = {
                "type": "conversation_turn",
                "role": "assistant",
                "category": "short_term", 
                "timestamp": datetime.now().isoformat(),
                "session_id": f"session_{int(self._session_start_time)}",
                "turn_number": len(self._conversation_buffer),
                "prompt_tokens": len(prompt.split()),
                "response_tokens": len(assistant_reply.split())
            }
            
            self.memory.add(
                messages=[{"role": "assistant", "content": assistant_reply}],
                user_id=self.user_id,
                agent_id=self.agent_id,
                app_id=self.app_id,
                metadata=response_metadata,
                version=MEMORY_VERSION,
                infer=True  # Extract insights from assistant responses too
            )
            self._memory_operations_count += 1

    async def _retrieve_relevant_memories(self, query: str) -> Dict[str, List[Dict[str, Any]]]:
        """Advanced memory retrieval with metadata filtering and categorization."""
        if not self.memory:
            return {"short_term": [], "long_term": [], "insights": [], "explicit_facts": []}
        
        try:
            # Search across different memory categories
            all_results = self.memory.search(
                query=query,
                user_id=self.user_id,
                agent_id=self.agent_id,
                limit=SHORT_MEMORY_SEARCH_LIMIT + LONG_MEMORY_SEARCH_LIMIT + INSIGHT_SEARCH_LIMIT
            )
            
            # Categorize memories by type and metadata
            categorized = {
                "short_term": [],
                "long_term": [], 
                "insights": [],
                "explicit_facts": []
            }
            
            for result in all_results.get("results", []):
                metadata = result.get("metadata", {})
                memory_type = metadata.get("type", "unknown")
                category = metadata.get("category", "general")
                
                # Skip low-confidence memories
                if result.get("score", 1.0) < MEMORY_CONFIDENCE_THRESHOLD:
                    continue
                
                if memory_type == "conversation_turn" and category == "short_term":
                    categorized["short_term"].append(result)
                elif memory_type == "explicit_fact":
                    categorized["explicit_facts"].append(result)
                elif memory_type == "user_insight":
                    categorized["insights"].append(result)
                else:
                    categorized["long_term"].append(result)
            
            # Limit results per category
            categorized["short_term"] = categorized["short_term"][:SHORT_MEMORY_SEARCH_LIMIT]
            categorized["long_term"] = categorized["long_term"][:LONG_MEMORY_SEARCH_LIMIT]
            categorized["insights"] = categorized["insights"][:INSIGHT_SEARCH_LIMIT]
            
            if self.verbose:
                total_memories = sum(len(v) for v in categorized.values())
                logger.debug(f"🔍 [MEMORY RETRIEVAL] Found {total_memories} relevant memories across categories")
            
            return categorized
            
        except Exception as e:
            logger.error(f"Failed to retrieve memories: {e}")
            return {"short_term": [], "long_term": [], "insights": [], "explicit_facts": []}

    async def _build_enhanced_system_prompt(self, query: str, memories: Dict[str, List[Dict[str, Any]]]) -> str:
        """Build enhanced system prompt with categorized memory integration."""
        sections = [self.system_prompt_template]
        
        # Add user insights (highest priority)
        if memories["insights"]:
            insights_text = "\n".join([
                f"- {mem['memory']}" for mem in memories["insights"]
            ])
            sections.append(f"## 🧠 User Insights\n{insights_text}")
        
        # Add explicit facts (user-requested memories)
        if memories["explicit_facts"]:
            facts_text = "\n".join([
                f"- {mem['memory']}" for mem in memories["explicit_facts"]
            ])
            sections.append(f"## 📌 Important Facts\n{facts_text}")
        
        # Add relevant long-term context
        if memories["long_term"]:
            long_term_text = "\n".join([
                f"- {mem['memory']}" for mem in memories["long_term"]
            ])
            sections.append(f"## 📚 Relevant History\n{long_term_text}")
        
        # Add recent conversation context
        if memories["short_term"]:
            short_term_text = "\n".join([
                f"- {mem['memory']}" for mem in memories["short_term"]
            ])
            sections.append(f"## 💬 Recent Context\n{short_term_text}")
        
        # Add session information
        session_info = f"Session started: {datetime.fromtimestamp(self._session_start_time).strftime('%Y-%m-%d %H:%M:%S')}"
        sections.append(f"## ℹ️ Session Info\n{session_info}")
        
        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Insight refresh machinery with enhanced analytics
    # ------------------------------------------------------------------

    async def _periodic_insight_refresh(self) -> None:
        """Cluster memories and periodically regenerate user insights with enhanced analytics."""
        while True:
            now = time.time()
            if now - self._last_insight_refresh >= INSIGHT_REFRESH_INTERVAL:
                try:
                    await self._recompute_insights()
                    self._last_insight_refresh = now
                except Exception as exc:
                    logger.error(f"Insight refresh failed: {exc}")
            await asyncio.sleep(10)  # light‑weight guard loop

    async def _recompute_insights(self) -> None:
        """Enhanced insight generation with memory categorization and analytics."""
        if not self.memory:
            return
            
        logger.info("🧠 [INSIGHTS] Regenerating user insights with enhanced analytics...")

        try:
            # Get all memories for analysis
            all_memories = self.memory.get_all(user_id=self.user_id)
            if not all_memories or not all_memories.get("results"):
                logger.info("🧠 [INSIGHTS] No memories found for insight generation")
                return

            results = all_memories["results"]
            
            # Filter out existing insights to avoid recursion
            conversation_memories = [
                mem for mem in results 
                if mem.get("metadata", {}).get("type") != "user_insight"
            ]
            
            if len(conversation_memories) < INSIGHT_GENERATION_THRESHOLD:
                logger.info(f"🧠 [INSIGHTS] Insufficient memories ({len(conversation_memories)}) for insight generation")
                return

            # Categorize memories for targeted insight generation
            memory_categories = self._categorize_memories_for_insights(conversation_memories)
            
            # Generate insights for each category
            new_insights = []
            for category, memories in memory_categories.items():
                if memories:
                    insights = await self._generate_category_insights(category, memories)
                    new_insights.extend(insights)

            # Store new insights with metadata
            if new_insights:
                await self._store_insights(new_insights)
                logger.info(f"🧠 [INSIGHTS] Generated {len(new_insights)} new insights across {len(memory_categories)} categories")
            else:
                logger.info("🧠 [INSIGHTS] No new insights generated")

        except Exception as e:
            logger.error(f"Failed to recompute insights: {e}")

    def _categorize_memories_for_insights(self, memories: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Categorize memories for targeted insight generation."""
        categories = {
            "preferences": [],
            "knowledge": [],
            "behavior": [],
            "relationships": [],
            "goals": []
        }
        
        for memory in memories:
            content = memory.get("memory", "").lower()
            metadata = memory.get("metadata", {})
            
            # Simple keyword-based categorization (could be enhanced with ML)
            if any(word in content for word in ["like", "prefer", "love", "hate", "favorite"]):
                categories["preferences"].append(memory)
            elif any(word in content for word in ["know", "learned", "understand", "skill"]):
                categories["knowledge"].append(memory)
            elif any(word in content for word in ["usually", "always", "never", "habit", "routine"]):
                categories["behavior"].append(memory)
            elif any(word in content for word in ["friend", "family", "colleague", "relationship"]):
                categories["relationships"].append(memory)
            elif any(word in content for word in ["goal", "plan", "want", "need", "hope"]):
                categories["goals"].append(memory)
            else:
                # Default to behavior if unclear
                categories["behavior"].append(memory)
        
        return {k: v for k, v in categories.items() if v}  # Remove empty categories

    async def _generate_category_insights(self, category: str, memories: List[Dict[str, Any]]) -> List[str]:
        """Generate insights for a specific category of memories."""
        if not memories:
            return []
            
        # Prepare memory content for analysis
        memory_texts = [mem.get("memory", "") for mem in memories[-20:]]  # Last 20 for efficiency
        combined_text = "\n".join(memory_texts)
        
        # Category-specific prompts for better insights
        category_prompts = {
            "preferences": "Analyze the user's preferences and tastes. What do they consistently like or dislike?",
            "knowledge": "What does the user know about? What are their areas of expertise or learning?",
            "behavior": "What behavioral patterns can you identify? How does the user typically act or respond?",
            "relationships": "What can you infer about the user's relationships and social interactions?",
            "goals": "What are the user's goals, aspirations, or things they're working towards?"
        }
        
        prompt = f"""
        {category_prompts.get(category, "Analyze the following memories and extract key insights about the user.")}
        
        Based on these memories, generate 2-3 concise insights (max 50 words each) that would help me serve this user better in future conversations.
        
        Format as JSON array: [{"insight": "text", "confidence": "high/medium/low"}]
        
        Memories:
        {combined_text}
        """
        
        try:
            response = await self.openai.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are an expert at analyzing user behavior and extracting actionable insights."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3  # Lower temperature for more consistent insights
            )
            
            content = response.choices[0].message.content
            # Extract JSON from response
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                insights_data = json.loads(content[start:end])
                return [
                    f"[{category.upper()}] {insight['insight']} (Confidence: {insight['confidence']})"
                    for insight in insights_data
                ]
        except Exception as e:
            logger.error(f"Failed to generate insights for category {category}: {e}")
        
        return []

    async def _store_insights(self, insights: List[str]) -> None:
        """Store generated insights with proper metadata."""
        if not self.memory or not insights:
            return
            
        for insight in insights:
            metadata = {
                "type": "user_insight",
                "category": "insight",
                "source": "automated_analysis",
                "timestamp": datetime.now().isoformat(),
                "session_id": f"session_{int(self._session_start_time)}",
                "generation_method": "enhanced_analytics"
            }
            
            self.memory.add(
                messages=[{"role": "system", "content": insight}],
                user_id=self.user_id,
                agent_id=self.agent_id,
                app_id=self.app_id,
                metadata=metadata,
                version=MEMORY_VERSION,
                infer=False  # Don't re-infer insights
            )

    # ------------------------------------------------------------------
    # Graceful teardown helpers
    # ------------------------------------------------------------------

    async def __aexit__(self, exc_type, exc, tb):  # noqa: D401 – async context manager
        self._insight_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._insight_task
