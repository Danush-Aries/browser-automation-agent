"""
Conversation compaction logic for the Browser Automation Agent.

Two strategies:
1. Server-side compaction: Uses Anthropic's beta compact-2026-01-12 feature.
   When enabled, the API automatically summarizes earlier context.
2. Client-side fallback: When message count exceeds MAX_MESSAGES, summarize
   older messages with a Claude call and replace them with the summary.
"""

import anthropic

MAX_MESSAGES = 20  # trigger client-side compaction after this many messages
COMPACTION_KEEP_RECENT = 6  # keep the most recent N messages when compacting


def needs_client_compaction(messages: list[dict]) -> bool:
    """Return True if the conversation is long enough to compact."""
    return len(messages) > MAX_MESSAGES


def compact_messages(
    client: anthropic.Anthropic,
    messages: list[dict],
    model: str,
    system_prompt: str,
) -> list[dict]:
    """
    Client-side compaction: summarize old messages and return a trimmed list.

    Keeps the most recent COMPACTION_KEEP_RECENT messages and replaces everything
    before them with a single assistant summary message.
    """
    if len(messages) <= COMPACTION_KEEP_RECENT:
        return messages

    # Split: old messages to summarize, recent messages to keep
    old_messages = messages[:-COMPACTION_KEEP_RECENT]
    recent_messages = messages[-COMPACTION_KEEP_RECENT:]

    # Build a text representation of the old conversation for summarization
    conversation_text = []
    for msg in old_messages:
        role = msg["role"]
        content = msg.get("content", "")
        if isinstance(content, list):
            # Handle content blocks (tool use, tool result, etc.)
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        text_parts.append(f"[Tool call: {block.get('name')}({block.get('input', {})})]")
                    elif block.get("type") == "tool_result":
                        text_parts.append(f"[Tool result: {str(block.get('content', ''))[:200]}]")
                    elif hasattr(block, "type"):
                        if block.type == "text":
                            text_parts.append(block.text)
                        elif block.type == "tool_use":
                            text_parts.append(f"[Tool call: {block.name}]")
                else:
                    text_parts.append(str(block))
            content = " ".join(text_parts)
        elif hasattr(content, "__iter__") and not isinstance(content, str):
            content = str(content)
        conversation_text.append(f"{role.upper()}: {content}")

    conversation_str = "\n\n".join(conversation_text)

    # Use Claude to summarize the old conversation
    try:
        summary_response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=(
                "You are a conversation summarizer. "
                "Produce a concise summary of the browser automation conversation below. "
                "Include: what pages were visited, what actions were taken, what was found, "
                "and the current state of the task. Be specific about URLs and content seen."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"Summarize this browser automation conversation:\n\n{conversation_str}"
                }
            ]
        )
        summary_text = next(
            (b.text for b in summary_response.content if b.type == "text"),
            "Summary unavailable."
        )
    except Exception as e:
        summary_text = f"[Conversation compacted. Earlier context unavailable due to: {e}]"

    # Build the compacted message history
    compacted = [
        {
            "role": "user",
            "content": "Please continue the browser automation task."
        },
        {
            "role": "assistant",
            "content": f"[CONVERSATION SUMMARY - Earlier context]\n{summary_text}\n\n"
                       "I'll continue from the current state of the task."
        }
    ]
    compacted.extend(recent_messages)
    return compacted


def build_server_compaction_request(
    client: anthropic.Anthropic,
    model: str,
    system: list[dict],
    tools: list[dict],
    messages: list[dict],
    max_tokens: int = 4096,
) -> anthropic.types.Message:
    """
    Make a Claude API call with server-side compaction enabled.
    Uses the beta compact-2026-01-12 feature.

    The API will automatically summarize earlier context when it approaches
    the context window limit. Compaction blocks in the response must be
    preserved and passed back on subsequent requests.
    """
    return client.beta.messages.create(
        betas=["compact-2026-01-12"],
        model=model,
        max_tokens=max_tokens,
        system=system,
        tools=tools,
        messages=messages,
        context_management={
            "edits": [{"type": "compact_20260112"}]
        }
    )
