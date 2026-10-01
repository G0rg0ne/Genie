import json
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import AIMessageChunk
from loguru import logger

from agents.genie_graph import llm
from core.langfuse_client import build_trace_config
from schemas.title import TitleOutput
from utils.logger import setup_logging
from utils.sse import base_chunk, build_inputs, extract_text

setup_logging()

ANSWER_NODE = "writer"
DEFAULT_MODEL = "Genie"
TITLE_MARKER = "TITLE_REQUEST::"

router = APIRouter()


def _optional_str(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _trace_ids(body: dict) -> tuple[str | None, str | None]:
    user_id = _optional_str(body.get("user"))
    session_id = (
        _optional_str(body.get("session_id"))
        or _optional_str(body.get("conversation_id"))
        or _optional_str(body.get("thread_id"))
    )
    return user_id, session_id


@router.post("/v1/chat/completions")
async def completions(req: Request):
    logger.info("Request received ...")

    graph = req.app.state.graph

    body = await req.json()
    model = body.get("model") or DEFAULT_MODEL
    cid = f"chatcmpl-{uuid.uuid4().hex}"
    messages = body.get("messages", [])
    last_content = messages[-1]["content"] if messages else ""
    stream = bool(body.get("stream"))
    user_id, session_id = _trace_ids(body)

    if not stream and isinstance(last_content, str) and last_content.startswith(TITLE_MARKER):
        question = last_content[len(TITLE_MARKER):].strip()
        config = build_trace_config(
            cid=cid,
            model=model,
            stream=False,
            user_id=user_id,
            session_id=session_id,
            run_name="genie-title",
        )
        try:
            title_result = llm.with_structured_output(TitleOutput).invoke(
                f"Summarize this question into a short, 3-6 word conversation title:\n\n{question}",
                config=config,
            )
        except Exception as exc:
            logger.exception(f"[{cid}] Title generation failed")
            return JSONResponse(status_code=500, content={"error": {"message": str(exc)}})

        return JSONResponse({
            "id": cid,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": title_result.title},
            }],
        })

    try:
        inputs = build_inputs(body.get("messages", []))
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": {"message": str(exc)}})

    logger.info(f"[{cid}] question={inputs['question']!r} history_len={len(inputs['chat_history'])}")

    config = build_trace_config(
        cid=cid,
        model=model,
        stream=stream,
        user_id=user_id,
        session_id=session_id,
        run_name="genie-chat-completion",
    )

    # ---------- non-streaming ----------
    if not stream:
        try:
            result = await graph.ainvoke(inputs, config=config)
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
        created = int(time.time())

        opener = base_chunk(cid, model, created)
        opener["choices"][0]["delta"] = {"role": "assistant", "content": ""}
        yield f"data: {json.dumps(opener)}\n\n"

        try:
            async for stream_type, payload in graph.astream(
                inputs,
                config=config,
                stream_mode=["custom", "messages"],
            ):
                if stream_type == "custom":
                    evt = base_chunk(cid, model, created)
                    evt["choices"][0]["delta"] = {"reasoning_content": payload["status"] + "\n"}
                    yield f"data: {json.dumps(evt)}\n\n"

                elif stream_type == "messages":
                    msg, meta = payload
                    if isinstance(msg, AIMessageChunk) and meta.get("langgraph_node") == ANSWER_NODE:
                        text = extract_text(msg.content)
                        if text:
                            evt = base_chunk(cid, model, created)
                            evt["choices"][0]["delta"] = {"content": text}
                            yield f"data: {json.dumps(evt)}\n\n"

        except Exception as exc:
            logger.exception(f"[{cid}] Graph failed during streaming")
            evt = base_chunk(cid, model, created)
            evt["choices"][0]["delta"] = {"content": f"⚠️ Agent error: {type(exc).__name__}: {exc}"}
            yield f"data: {json.dumps(evt)}\n\n"

        final = base_chunk(cid, model, created)
        final["choices"][0]["finish_reason"] = "stop"
        yield f"data: {json.dumps(final)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
