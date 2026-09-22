import json
import time

def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""

def chunk(cid: str, model: str, content: str | None = None, finish: str | None = None) -> str:
    """Format one OpenAI-style SSE chunk."""
    delta = {"content": content} if content is not None else {}
    return "data: " + json.dumps({
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }) + "\n\n"
def base_chunk(cid: str, model: str, created: int) -> dict:
    return {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
    }
def reasoning_chunk(cid: str, model: str, text: str) -> str:
    payload = {
        "id": cid,
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [{"index": 0, "delta": {"reasoning_content": text}}],
    }
    return f"data: {json.dumps(payload)}\n\n"

def build_inputs(messages: list[dict]) -> dict:
    """Split LibreChat's messages into the latest question and the previous turns."""
    user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if not user_indices:
        raise ValueError("No user message found in the request")
    last_user_idx = user_indices[-1]

    question = extract_text(messages[last_user_idx].get("content"))
    history = [
        {"role": m["role"], "content": extract_text(m.get("content"))}
        for m in messages[:last_user_idx]
        if m.get("role") in ("user", "assistant")
    ]
    return {"question": question, "chat_history": history}