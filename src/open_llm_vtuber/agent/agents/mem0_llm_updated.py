"""UPDATED: Advanced memory-augmented LLM agent utilizing ALL mem0 platform features.

This file has been updated to use the CompleteEnhancedMem0Agent which implements
ALL mem0 enterprise features including:

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

Migration Notice:
----------------
This implementation replaces the previous three-tier memory system with a unified,
feature-complete mem0 platform agent. All original functionality is preserved
but enhanced with enterprise-grade capabilities.

For new projects, consider using CompleteEnhancedMem0Agent directly for full
control over all advanced features.
"""

# Import the complete enhanced implementation
from .complete_enhanced_mem0_agent import CompleteEnhancedMem0Agent

# Maintain backward compatibility with existing code
LLM = CompleteEnhancedMem0Agent
AdvancedMem0LLMAgent = CompleteEnhancedMem0Agent

__all__ = ["LLM", "AdvancedMem0LLMAgent", "CompleteEnhancedMem0Agent"]
