from typing import List, Literal, Optional, Dict, Any

from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api import set_token
from assistant import (
    SYSTEM,
    MODEL,
    client,
    tools,
    call_tool,
)
from memory_store import (
    get_memory,
    bootstrap_memory_from_messages,
    memory_to_openai_messages,
)
from speech import transcribe_audio, synthesize_speech
import json


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    user_message: Optional[str] = None
    messages: Optional[List[ChatMessage]] = None


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    audio_format: Optional[str] = None


app = FastAPI(title="LumiDrive Assistant API")

# Add CORS middleware to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific frontend URL
    allow_credentials=False,  # We use Bearer tokens, not cookies
    allow_methods=["*"],
    allow_headers=["*"],
)


def _set_backend_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty bearer token.")
    set_token(token)
    return token


def _last_user_message(messages: List[ChatMessage]) -> Optional[str]:
    for msg in reversed(messages):
        if msg.role == "user" and msg.content:
            return msg.content
    return None


def _run_tools_for_message(msg, messages: List[Dict[str, Any]]) -> None:
    """
    Execute any tool calls in msg and append their outputs to messages.
    This mirrors the logic in assistant.chat_loop but without CLI I/O.
    """
    if not msg.tool_calls:
        return

    # Mirror the structure we keep in the interactive assistant
    messages.append({
        "role": "assistant",
        "content": msg.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            }
            for tc in msg.tool_calls
        ],
    })

    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments or "{}")
        try:
            # all tool_* functions are defined in assistant.py
            result = eval(f"tool_{tc.function.name}")(**args)
        except TypeError as e:
            result = {"ok": False, "error": f"tool_{tc.function.name} invocation error", "details": str(e)}
        except NameError:
            result = call_tool(tc.function.name, args)
        except Exception as exc:
            result = {"ok": False, "error": f"tool_{tc.function.name} crashed", "details": str(exc)}

        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "name": tc.function.name,
            "content": json.dumps(result),
        })


@app.post("/chat")
async def chat_endpoint(
    body: ChatRequest,
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
):
    """
    Chat endpoint for the LumiDrive assistant.

    - Expects full conversation array in `body.messages`.
    - Uses the Bearer token from the Authorization header to talk to the rides backend.
    - Streams the final assistant reply back to the caller.
    """
    _set_backend_token(authorization)

    if not body.session_id:
        raise HTTPException(status_code=400, detail="session_id is required.")

    memory = get_memory(body.session_id)

    if body.messages:
        bootstrap_memory_from_messages(memory, [m.dict() for m in body.messages])

    user_message = (body.user_message or "").strip()
    if not user_message and body.messages:
        user_message = (_last_user_message(body.messages) or "").strip()

    if not user_message:
        raise HTTPException(status_code=400, detail="user_message is required.")

    memory.chat_memory.add_user_message(user_message)

    messages = memory_to_openai_messages(memory, SYSTEM)

    try:
        first = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=[{"type": "function", "function": t["function"]} for t in tools],
            tool_choice="auto",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach OpenAI: {exc}") from exc

    first_msg = first.choices[0].message
    _run_tools_for_message(first_msg, messages)

    try:
        stream = client.chat.completions.create(
            model=MODEL,
            messages=messages + [{"role": "assistant", "content": first_msg.content or ""}],
            stream=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to stream OpenAI response: {exc}") from exc

    def token_stream():
        final_chunks: List[str] = []
        try:
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    final_chunks.append(delta.content)
                    yield delta.content
        finally:
            final_text = "".join(final_chunks).strip()
            if final_text:
                memory.chat_memory.add_ai_message(final_text)

    return StreamingResponse(token_stream(), media_type="text/plain")


@app.post("/stt")
async def stt_endpoint(
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
    file: UploadFile = File(...),
    language: Optional[str] = Form(default=None),
    session_id: Optional[str] = Form(default=None),
):
    """
    Speech-to-text helper.

    Frontend uploads audio via multipart/form-data. We call OpenAI STT and return the transcript.
    """
    _set_backend_token(authorization)

    try:
        audio_bytes = await file.read()
        result = transcribe_audio(audio_bytes, filename=file.filename or "audio.wav", language=language)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Speech-to-text failed: {exc}") from exc

    return {
        "ok": True,
        "text": result.get("text"),
        "language": result.get("language") or language,
        "duration": result.get("duration"),
        "segments": result.get("segments"),
        "session_id": session_id,
    }


@app.post("/tts")
async def tts_endpoint(
    body: TTSRequest,
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
):
    """
    Text-to-speech helper.

    Accepts assistant text and returns audio bytes for playback.
    """
    _set_backend_token(authorization)

    if not body.text:
        raise HTTPException(status_code=400, detail="text is required for TTS.")

    try:
        audio_bytes, content_type = synthesize_speech(
            text=body.text,
            voice=body.voice,
            audio_format=body.audio_format,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Text-to-speech failed: {exc}") from exc

    headers = {
        "Content-Disposition": 'inline; filename="speech.{}"'.format((body.audio_format or "mp3").lower())
    }

    return Response(content=audio_bytes, media_type=content_type, headers=headers)


