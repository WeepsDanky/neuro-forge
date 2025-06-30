"""Complete Enhanced mem0 agent implementation utilizing ALL platform features.

This module imports and exposes the complete enhanced mem0 agent that leverages
EVERY mem0 enterprise feature including:

🔥 ADVANCED RETRIEVAL FEATURES:
- Keyword Search: Enhanced recall with keyword matching
- Reranking: Neural network-based relevance ordering  
- Filtering: High-precision targeted results

🧠 MEMORY MANAGEMENT:
- Contextual Add v2: Automatic context retrieval
- Multimodal Support: Images, PDFs, documents
- Custom Categories: Domain-specific organization
- Custom Instructions: Project-specific guidelines
- Selective Memory: Include/exclude filters
- Direct Import: Bypass inference for explicit storage

⚡ ADVANCED FEATURES:
- Graph Memory: Relationship-based retrieval
- Memory Export: Structured Pydantic schemas
- Memory Timestamps: Historical accuracy
- Expiration Dates: Time-bound memories
- Webhooks: Real-time event notifications
- Feedback Mechanism: Continuous learning
- Criteria Retrieval: Weighted custom scoring
- Async Client: High-concurrency operations

🔧 ENTERPRISE CAPABILITIES:
- Multi-entity scoping (user/agent/app/run)
- Memory versioning and history tracking
- Confidence thresholds and quality control
- Performance optimization with latency <10ms for keyword search
- 26% higher accuracy, 91% faster, 90% token savings vs OpenAI Memory
"""

from .complete_enhanced_mem0_agent import CompleteEnhancedMem0Agent

# Export the complete enhanced agent as the main implementation
AdvancedMem0LLMAgent = CompleteEnhancedMem0Agent
LLM = CompleteEnhancedMem0Agent  # For backward compatibility

__all__ = ["AdvancedMem0LLMAgent", "CompleteEnhancedMem0Agent", "LLM"]
