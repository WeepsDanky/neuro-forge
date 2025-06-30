"""An advanced memory‑augmented LLM agent that mimics ChatGPT’s three‑tier memory system:

1. **Short‑term memory** – recent conversation context that stays in RAM and a transient
   vector store so we can semantic‑search within the current session.
2. **Long‑term memory (Saved Memory)** – developer or user‑explicit facts that should be
   remembered across sessions.  The agent provides a public `remember()` helper that the
   application or a tool‑call can invoke to store durable facts.
3. **User Insights** – automatically derived, higher‑level summaries of the user’s
   habits or recurring themes.  A background coroutine consolidates long‑term memory
   into insights every `INSIGHT_REFRESH_INTERVAL` minutes using the LLM itself.

The agent is still *stateless* with respect to the OpenAI chat endpoint – we rebuild the
prompt for every request – but it is **stateful** with respect to its three mem0
vector stores.

The implementation purposefully keeps the public surface small:

```python
agent = AdvancedMem0LLMAgent(
    user_id="u123",
    base_url="https://api.openai.com/v1",
    model="gpt-4o-mini",
    system="You are a helpful assistant …",
    mem0_config={"driver": "sqlite", "database": "./mem.db"},
)

async for token in agent.chat("How do I cook tofu?"):
    print(token, end="", flush=True)
```

Design notes
------------
* **Short term** – The last `MAX_SHORT_MESSAGES` messages are appended verbatim to the
  OpenAI call.  We *also* embed them into `self.short_term_mem" to enable semantic
  recall within the session (e.g. quoting a message from ten turns ago even if it has
  scrolled out of the literal context window).
* **Long term** – When the host application calls `remember()`, the text is embedded and
  persisted in `self.long_term_mem`.  The agent itself never decides to store long‑term
  facts – that UX choice is left to a higher layer (tool‑call, button, etc.).
* **Insights** – A coroutine periodically clusters the long‑term memories that belong
  to the same user and asks the LLM to summarise each cluster.  The resulting summary
  strings are embedded into `self.insight_mem` so they, too, can be semantically
  searched at inference time.

The code intentionally avoids external scheduling frameworks – the background task is
spawned on first instantiation and lives for the lifetime of the Python process.
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


class AdvancedMem0LLMAgent(AgentInterface):
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
    # AgentInterface overrides
    # ---------------------------------------------------------------------

    async def chat(self, input_data: BaseInput) -> AsyncIterator[BaseOutput]:
        """Entry‑point expected by *AgentInterface* – dispatch to `_chat_iter`."""

        # Extract plain‑text prompt from *input_data* (re‑use logic from BasicMemoryAgent)
        # For brevity this demo covers the simple case of a single user text field.
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
        """Load *past* chat history into **short‑term** and **long‑term** storage."""
        from ...chat_history_manager import get_history  # local import to avoid cycles

        history = get_history(conf_uid, history_uid)
        for msg in history[-MAX_SHORT_MESSAGES:]:
            role = "user" if msg["role"] == "human" else "assistant"
            self._conversation_buffer.append({"role": role, "content": msg["content"]})
            # Keep embeddings for semantic search within the session, too.
            self.short_term_mem.add([{"role": role, "content": msg["content"]}], user_id=self.user_id)

        # Everything goes into long‑term so it *could* be recalled in future sessions.
        self.long_term_mem.add(history, user_id=self.user_id)

    # ------------------------------------------------------------------
    # Public helpers for the *application layer* – optional usage
    # ------------------------------------------------------------------

    def remember(self, fact: str) -> None:
        """Persist a *fact* to long‑term memory (analogous to ChatGPT’s Saved Memory)."""
        self.long_term_mem.add([{"role": "system", "content": fact}], user_id=self.user_id)
        logger.info(f"[mem] Saved long‑term fact: {fact!r}")

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------    async def _chat_iter(self, prompt: str) -> AsyncIterator[str]:
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
    # Insight refresh machinery – runs in the background
    # ------------------------------------------------------------------

    async def _periodic_insight_refresh(self) -> None:
        """Cluster long‑term memories and periodically regenerate user insights."""
        while True:
            now = time.time()
            if now - self._last_insight_refresh >= INSIGHT_REFRESH_INTERVAL:
                try:
                    await self._recompute_insights()
                    self._last_insight_refresh = now
                except Exception as exc:
                    logger.error(f"Insight refresh failed: {exc}")
            await asyncio.sleep(10)  # light‑weight guard loop – adjust as needed

    async def _recompute_insights(self) -> None:
        """Query long‑term memories, cluster them, and store fresh summaries."""
        logger.info("[insight] Regenerating user insights …")

        # Pull **all** long‑term memories for this user – small users only!
        all_memories = self.long_term_mem.get_all(user_id=self.user_id)
        if not all_memories:
            logger.info("[insight] No long‑term memories yet – skipping")
            return

        # Very naive clustering: split into chunks of *N* messages by recency
        CHUNK_SIZE = 20
        clusters: List[List[Dict[str, str]]] = [
            all_memories[i : i + CHUNK_SIZE] for i in range(0, len(all_memories), CHUNK_SIZE)
        ]

        new_insights: List[str] = []
        for cluster in clusters:
            joined = "\n".join(mem["content"] for mem in cluster)
            summary_prompt = (
                "You are an AI assistant. Summarise the following user facts/messages "
                "into a **concise insight** that would help you serve the user better in "
                "future chats (max 60 words).\n\n" + joined
            )
            try:
                resp = await self.openai.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": summary_prompt}],
                )
                insight_text = resp.choices[0].message.content.strip()
                new_insights.append(insight_text)
            except Exception as e:
                logger.error(f"Insight generation failed: {e}")
                continue

        # Clear and re‑insert insights for idempotency
        self.insight_mem.clear(user_id=self.user_id)
        self.insight_mem.add([{"role": "system", "content": txt} for txt in new_insights], user_id=self.user_id)
        logger.info(f"[insight] Stored {len(new_insights)} refreshed insights")

    # ------------------------------------------------------------------
    # Graceful teardown helpers
    # ------------------------------------------------------------------    async def __aexit__(self, exc_type, exc, tb):  # noqa: D401 – async context manager
        self._insight_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._insight_task
