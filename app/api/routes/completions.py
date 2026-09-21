import json
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import AIMessageChunk
from loguru import logger

from agents.genie_graph import agent_graph
from utils.logger import setup_logging

setup_logging()

ANSWER_NODE = "writer"          # the node that writes state.answer
DEFAULT_MODEL = "Genie"

graph = agent_graph()
router = APIRouter()


def extract_text(content) -> str:
    """Return plain text from a message's content.

    Handles a plain string, or a list of content blocks: LibreChat's multimodal parts
    on the way in, and Responses API blocks (text + reasoning) on the way out.
    Only blocks of type "text" are kept, so reasoning blocks never leak.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
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
        if m.get("role") in ("user", "assistant")  # system prompt dropped on purpose
    ]
    return {"question": question, "chat_history": history}  # add_messages converts the dicts


@router.post("/v1/chat/completions")
async def completions(req: Request):
    body = await req.json()
    model = body.get("model") or DEFAULT_MODEL
    cid = f"chatcmpl-{uuid.uuid4().hex}"

    try:
        inputs = build_inputs(body.get("messages", []))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": {"message": str(exc)}})

    logger.info(f"[{cid}] question={inputs['question']!r} history_len={len(inputs['chat_history'])}")

    # ---------- non-streaming ----------
    if not body.get("stream"):
        try:
            result = await graph.ainvoke(inputs)
        except Exception as exc:
            logger.exception(f"[{cid}] Graph failed")
            return JSONResponse(status_code=500, content={"error": {"message": str(exc)}})

        return JSONResponse({
            "id": cid,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": result["answer"]},
            }],
        })

    # ---------- streaming ----------
    async def gen():
        try:
            async for msg, meta in graph.astream(inputs, stream_mode="messages"):
                if isinstance(msg, AIMessageChunk) and meta.get("langgraph_node") == ANSWER_NODE:
                    text = extract_text(msg.content)
                    if text:  # skips reasoning blocks and empty chunks
                        yield chunk(cid, model, text)
        except Exception as exc:
            # headers are already sent, so surface the error in the chat instead of failing silently
            logger.exception(f"[{cid}] Graph failed during streaming")
            yield chunk(cid, model, f"⚠️ Agent error: {type(exc).__name__}: {exc}")

        yield chunk(cid, model, finish="stop")
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")