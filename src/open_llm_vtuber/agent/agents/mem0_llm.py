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
import json
import time
from collections import deque
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from loguru import logger
from mem0 import Memory
from openai import OpenAI, AsyncOpenAI

from .agent_interface import AgentInterface, BaseInput, BaseOutput, AsyncIterator  # type: ignore

# ----------------------------------------------------------------------------
# Tunables – tweak to taste
# ----------------------------------------------------------------------------
MAX_SHORT_MESSAGES = 20                      # hard cap on messages kept verbatim
SHORT_MEMORY_SEARCH_LIMIT = 10               # top‑k from mem0 short‑term search
LONG_MEMORY_SEARCH_LIMIT = 10                # top‑k from mem0 long‑term search
INSIGHT_SEARCH_LIMIT = 5                     # top‑k from mem0 insight search
INSIGHT_REFRESH_INTERVAL = 60 * 60          # seconds – once an hour by default


class AdvancedMem0LLMAgent(AgentInterface):
    """ChatGPT‑style agent with hierarchical memory built on mem0 + OpenAI."""

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
        verbose: bool = False,
    ) -> None:
        super().__init__()

        self.user_id = user_id
        self.model = model
        self.system_prompt_template = system  # will be enriched per‑call
        self.verbose = verbose

        # ------------------------- OpenAI clients -------------------------
        self.openai = AsyncOpenAI(  # type: ignore – pydantic stubs
            base_url=base_url,
            organization=organization_id or None,
            project=project_id or None,
            api_key=llm_api_key or None,
        )

        # ------------------------- Memory layers -------------------------
        self.short_term_mem = Memory.from_config(mem0_config)
        self.long_term_mem = Memory.from_config(mem0_config)
        self.insight_mem = Memory.from_config(mem0_config)

        # Local circular buffer for literal recent messages (no embeddings)
        self._conversation_buffer: deque[Dict[str, str]] = deque(maxlen=MAX_SHORT_MESSAGES)

        # Background task that periodically refreshes user insights
        self._last_insight_refresh = 0.0
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
    # ------------------------------------------------------------------

    async def _chat_iter(self, prompt: str) -> AsyncIterator[str]:
        # --- 1. Keep literal short‑term history up to date ----------------
        self._conversation_buffer.append({"role": "user", "content": prompt})
        self.short_term_mem.add([{"role": "user", "content": prompt}], user_id=self.user_id)

        # --- 2. Retrieve semantically relevant memories ------------------
        short_hits = self.short_term_mem.search(prompt, limit=SHORT_MEMORY_SEARCH_LIMIT, user_id=self.user_id)
        long_hits = self.long_term_mem.search(prompt, limit=LONG_MEMORY_SEARCH_LIMIT, user_id=self.user_id)
        insight_hits = self.insight_mem.search(prompt, limit=INSIGHT_SEARCH_LIMIT, user_id=self.user_id)

        def _fmt(mem_list: List[Dict[str, Any]]) -> str:
            return "\n".join(m["memory"] for m in mem_list) if mem_list else ""

        relevant_short = _fmt(short_hits)
        relevant_long = _fmt(long_hits)
        relevant_insights = _fmt(insight_hits)

        # --- 3. Assemble dynamic system prompt ---------------------------
        system_sections = [self.system_prompt_template]
        if relevant_insights:
            system_sections.append("## User Insights\n" + relevant_insights)
        if relevant_long:
            system_sections.append("## Long‑Term Memories\n" + relevant_long)
        if relevant_short:
            system_sections.append("## Recent Conversation Snippets\n" + relevant_short)

        system_message = {"role": "system", "content": "\n\n".join(system_sections)}

        # --- 4. Final message stack sent to the LLM ----------------------
        full_context = [system_message] + list(self._conversation_buffer)
        if self.verbose:
            logger.debug("LLM call with context:\n" + json.dumps(full_context, indent=2)[:1000])

        # Stream tokens back to the caller whilst capturing the full assistant reply
        completion = await self.openai.chat.completions.create(
            model=self.model,
            messages=full_context,
            stream=True,
        )

        assistant_reply = ""
        async for chunk in completion:  # type: ignore[attr-defined]
            delta = chunk.choices[0].delta.content or ""
            assistant_reply += delta
            yield delta  # type: ignore[misc]

        # --- 5. Book‑keeping after generation ----------------------------
        self._conversation_buffer.append({"role": "assistant", "content": assistant_reply})
        self.short_term_mem.add([{"role": "assistant", "content": assistant_reply}], user_id=self.user_id)

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
    # ------------------------------------------------------------------

    async def __aexit__(self, exc_type, exc, tb):  # noqa: D401 – async context manager
        self._insight_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._insight_task
"
