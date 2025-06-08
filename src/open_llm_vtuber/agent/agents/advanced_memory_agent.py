"""
Description: Memory-enhanced LLM agent implementation using mem0, with short-term, 
long-term, and insight-based memory systems, inspired by ChatGPT's memory architecture.
"""

import json
from typing import AsyncIterator, List, Dict, Any, Callable, Literal

from loguru import logger
from mem0 import Memory

from .basic_memory_agent import BasicMemoryAgent
from ..stateless_llm.stateless_llm_interface import StatelessLLMInterface
from ...config_manager import TTSPreprocessorConfig
from ...chat_history_manager import get_history

# Transformers from BasicMemoryAgent's pipeline
from ..transformers import (
    sentence_divider,
    actions_extractor,
    tts_filter,
    display_processor,
)
from ..input_types import BatchInput
from ..output_types import SentenceOutput


class AdvancedMemoryAgent(BasicMemoryAgent):
    """
    An advanced agent that leverages multiple memory systems inspired by ChatGPT:
    1.  Short-Term Memory: The immediate conversation context.
    2.  Long-Term "Saved" Memory: Explicit facts stored by the user via a "bio tool".
    3.  Long-Term "User Insights": Automatically generated insights about the user.

    It uses `mem0` for managing long-term memories and insights.
    Inherits from `BasicMemoryAgent` to reuse its chat processing pipeline.
    """

    def __init__(
        self,
        llm: StatelessLLMInterface,
        system: str,
        live2d_model,
        mem0_config: dict,
        user_id: str = "default_user",
        tts_preprocessor_config: TTSPreprocessorConfig = None,
        faster_first_response: bool = True,
        segment_method: str = "pysbd",
        interrupt_method: Literal["system", "user"] = "user",
    ):
        """
        Initialize the advanced agent.

        Args:
            llm: An instance of `StatelessLLMInterface`.
            system: The base system prompt for the agent.
            live2d_model: Model for expression extraction.
            mem0_config: Configuration dictionary for `mem0.Memory`.
            user_id: A unique identifier for the user to scope memories in mem0.
            tts_preprocessor_config: Configuration for TTS preprocessing.
            faster_first_response: Whether to enable faster first-response streaming.
            segment_method: Method for sentence segmentation.
            interrupt_method: Method for handling user interruptions.
        """
        # We call the parent __init__ but re-assign `self.chat` later with our own factory.
        super().__init__(
            llm=llm,
            system=system,
            live2d_model=live2d_model,
            tts_preprocessor_config=tts_preprocessor_config,
            faster_first_response=faster_first_response,
            segment_method=segment_method,
            interrupt_method=interrupt_method,
        )
        self.user_id = user_id
        self._user_insights = []
        self._conversation_count = 0  # Track conversation rounds for insights generation

        logger.info("Initializing Mem0 for AdvancedMemoryAgent...")
        try:
            self.mem0 = Memory.from_config(mem0_config)
            logger.info("Mem0 initialized successfully.")
            # Load existing user insights on initialization
            self._load_user_insights()
        except Exception as e:
            logger.error(
                f"Failed to initialize Mem0. All memory functions will be disabled. Error: {e}"
            )
            self.mem0 = None

        # Override the chat function with our advanced version
        self.chat = self._chat_function_factory(llm.chat_completion)

    def _load_user_insights(self):
        """Load existing user insights from memory."""
        if not self.mem0:
            return
            
        try:
            # Search for saved insights
            all_memories = self.mem0.get_all(user_id=self.user_id)
            if all_memories and all_memories.get('results'):
                saved_insights = []
                for mem in all_memories['results']:
                    memory_text = mem.get('memory', '')
                    if memory_text.startswith("[USER_INSIGHT]"):
                        insight = memory_text.replace("[USER_INSIGHT] ", "")
                        saved_insights.append(insight)
                
                if saved_insights:
                    self._user_insights = saved_insights
                    logger.info(f"🧠 [INSIGHTS LOADED] Loaded {len(saved_insights)} existing user insights")
        except Exception as e:
            logger.error(f"Failed to load user insights: {e}")

    def _save_user_insights(self):
        """Save user insights to memory for persistence."""
        if not self.mem0 or not self._user_insights:
            return
            
        try:
            for insight in self._user_insights:
                insight_text = f"[USER_INSIGHT] {insight}"
                self.mem0.add(insight_text, user_id=self.user_id)
            logger.info(f"💾 [INSIGHTS SAVED] Saved {len(self._user_insights)} user insights to memory")
        except Exception as e:
            logger.error(f"Failed to save user insights: {e}")

    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        """
        Load agent memory from chat history, populating both short-term
        context and the long-term `mem0` store.
        """
        if not self.mem0:
            logger.warning("Mem0 not initialized, skipping memory loading from history.")
            # Still load short-term memory via parent
            super().set_memory_from_history(conf_uid, history_uid)
            return

        messages = get_history(conf_uid, history_uid)

        # Reset and populate short-term memory (self._memory)
        self._memory = [{"role": "system", "content": self._system}]
        mem0_messages_to_add = []
        for msg in messages:
            role = "user" if msg["role"] == "human" else "assistant"
            content = msg["content"]
            self._memory.append({"role": role, "content": content})
            mem0_messages_to_add.append({"role": role, "content": content})

        # Bulk add to mem0
        if mem0_messages_to_add:
            logger.info(
                f"Adding {len(mem0_messages_to_add)} messages from history to Mem0."
            )
            self.mem0.add(mem0_messages_to_add, user_id=self.user_id)

        logger.info("Memory loaded from history.")
        # Insights will be generated on the next chat call.

    async def _update_user_insights(self):
        """
        Simulates a batch job to generate user insights from conversation history.
        In a real-world scenario, this would be an offline, periodic process.
        Here, it's triggered every 20 conversations for demonstration.
        """
        if not self.mem0:
            return

        # Only generate insights every 20 conversations
        if self._conversation_count % 20 != 0:
            return

        history = self.mem0.get_all(user_id=self.user_id)
        if not history or not history.get('results') or len(history['results']) < 5:
            self._user_insights = []
            return

        # Extract memory content from the results (exclude existing insights)
        history_text = "\n".join([
            mem.get('memory', '') for mem in history['results'][-40:]
            if not mem.get('memory', '').startswith("[USER_INSIGHT]")
        ])  # Use recent history, exclude saved insights

        if not history_text.strip():
            return

        prompt = f"""
        Based on the following conversation history, generate a list of user insights.
        Each insight should be a concise statement about the user's preferences, knowledge, or personality.
        For each insight, provide a confidence level (high, medium, low).
        Format the output as a JSON list of objects, where each object has "insight" and "confidence" keys.

        Conversation History:
        ---
        {history_text}
        ---
        """
        messages = [
            {
                "role": "system",
                "content": "You are a user profiling expert. Your task is to analyze conversation history and extract key insights about the user.",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            response_stream = self._llm.chat_completion(messages, system="")
            full_response = "".join([token async for token in response_stream])

            json_str = full_response[
                full_response.find("[") : full_response.rfind("]") + 1
            ]
            insights_data = json.loads(json_str)

            self._user_insights = [
                f"- {item['insight']} (Confidence: {item['confidence']})"
                for item in insights_data
            ]
            logger.info(f"🧠 [INSIGHTS GENERATED] Generated {len(self._user_insights)} new user insights after {self._conversation_count} conversations")
            
            # Save the generated insights to memory
            self._save_user_insights()
            
        except Exception as e:
            logger.error(f"Failed to generate user insights: {e}")
            self._user_insights = []

    def _to_message_content(self, input_data: BatchInput) -> str | list:
        """Helper to format input data into OpenAI message content format."""
        user_input_text = self._to_text_prompt(input_data)
        if input_data.images:
            content = [{"type": "text", "text": user_input_text}]
            for img_data in input_data.images:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": img_data.data, "detail": "auto"},
                    }
                )
            return content
        else:
            return user_input_text

    async def _construct_messages_with_advanced_memory(
        self, input_data: BatchInput
    ) -> List[Dict[str, Any]]:
        """
        Constructs the LLM prompt by augmenting the system prompt with insights,
        saved facts, and relevant conversation history from `mem0`.
        """
        user_input_text = self._to_text_prompt(input_data)

        if self.mem0:
            await self._update_user_insights()
            relevant_memories = self.mem0.search(
                query=user_input_text, user_id=self.user_id, limit=5
            )
            # Log retrieved relevant memories
            if relevant_memories and relevant_memories.get('results'):
                results = relevant_memories['results']
                logger.info(f"🔍 [MEMORY RETRIEVED] Found {len(results)} relevant memories for query: '{user_input_text}'")
                for i, mem in enumerate(results, 1):
                    logger.debug(f"  {i}. {mem.get('memory', '')}")
            
            # Get all memories and filter saved facts manually
            all_memories = self.mem0.get_all(user_id=self.user_id)
            # Handle case where memories are strings
            saved_facts = []
            if all_memories and all_memories.get('results'):
                for mem in all_memories['results']:
                    memory_text = mem.get('memory', '')
                    # Skip user insights when looking for saved facts
                    if memory_text.startswith("[USER_INSIGHT]"):
                        continue
                    # Handle both string and dict formats for saved facts
                    if memory_text.startswith("[SAVED_FACT]"):
                        saved_facts.append({"text": memory_text.replace("[SAVED_FACT] ", "")})
                    elif isinstance(mem, dict):
                        if mem.get('metadata', {}).get('type') == 'saved_fact':
                            saved_facts.append(mem)
            
            # Log retrieved saved facts
            if saved_facts:
                logger.info(f"📝 [SAVED FACTS RETRIEVED] Found {len(saved_facts)} saved facts:")
                for i, fact in enumerate(saved_facts, 1):
                    fact_text = fact.get('text', fact) if isinstance(fact, dict) else fact
                    logger.debug(f"  {i}. {fact_text}")
        else:
            relevant_memories, saved_facts = [], []

        system_prompt_parts = [self._system]

        if self._user_insights:
            insights_str = "\n".join(self._user_insights)
            system_prompt_parts.append(f"\n\n# User Insights\n{insights_str}")
            logger.info(f"🧠 [USER INSIGHTS] Applied {len(self._user_insights)} user insights to context")

        if saved_facts:
            facts_str = "\n".join([f"- {mem.get('text', mem) if isinstance(mem, dict) else mem}" for mem in saved_facts])
            system_prompt_parts.append(
                f"\n\n# Saved Memories\nThese are facts the user has explicitly asked you to remember:\n{facts_str}"
            )

        if relevant_memories and relevant_memories.get('results'):
            # Extract memory content from search results
            history_str = "\n".join([
                f"- {result.get('memory', '')}" 
                for result in relevant_memories['results']
            ])
            system_prompt_parts.append(
                f"\n\n# Relevant Conversation History\nHere are relevant snippets from past conversations:\n{history_str}"
            )

        enhanced_system_prompt = "\n".join(system_prompt_parts)

        messages = self._memory.copy()
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] = enhanced_system_prompt
        else:
            messages.insert(0, {"role": "system", "content": enhanced_system_prompt})

        logger.debug(f"Enhanced System Prompt:\n{enhanced_system_prompt}")
        # logger.info(f"Enhanced System Prompt: {enhanced_system_prompt}") # TODO: remove this

        # Add current user input to memory and the message list
        user_message_content = self._to_message_content(input_data)
        messages.append({"role": "user", "content": user_message_content})
        self._add_message(user_message_content, "user")

        return messages

    def _chat_function_factory(
        self, chat_func: Callable[[List[Dict[str, Any]], str], AsyncIterator[str]]
    ) -> Callable[..., AsyncIterator[SentenceOutput]]:
        @tts_filter(self._tts_preprocessor_config)
        @display_processor()
        @actions_extractor(self._live2d_model)
        @sentence_divider(
            faster_first_response=self._faster_first_response,
            segment_method=self._segment_method,
            valid_tags=["think"],
        )
        async def chat_with_advanced_memory(
            input_data: BatchInput,
        ) -> AsyncIterator[str]:
            user_input_text = self._to_text_prompt(input_data)

            messages = await self._construct_messages_with_advanced_memory(input_data)

            token_stream = chat_func(messages, "")
            complete_response = ""
            async for token in token_stream:
                yield token
                complete_response += token

            # After the conversation turn is complete, save it to long-term memory
            if self.mem0:
                # Save conversation as a formatted string instead of a list
                conversation_text = f"User: {user_input_text}\nAssistant: {complete_response}"
                self.mem0.add(conversation_text, user_id=self.user_id)
                logger.info(f"💾 [MEMORY STORED] Saved conversation turn:")
                logger.debug(f"  User: {user_input_text}")
                logger.debug(f"  AI: {complete_response}")

            self._add_message(complete_response, "assistant")
            
            # Increment conversation counter
            self._conversation_count += 1
            logger.debug(f"📊 [CONVERSATION COUNT] Total conversations: {self._conversation_count}")

        return chat_with_advanced_memory
