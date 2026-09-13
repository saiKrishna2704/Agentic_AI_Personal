import json
from typing import List
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from ollama import generate
from pydantic import BaseModel
from openai import OpenAI
from streamlit_config import openai_api_key, model_name, environment_name

app = FastAPI(
    
    title="Streaming API",
    description="A FastAPI backend for streaming responses from OpenAI's API.",
    version="2.0.0",
)
client = OpenAI(api_key=openai_api_key)
class Message(BaseModel):
    role: str
    content: str
class ChatRequest(BaseModel):
    messages: List[Message]
    model: str = model_name
    environment: str = environment_name
@app.get("/")
def home():
    return {"message": "Welcome to the Streaming API!"}
@app.post("/chat/stream")
def stream_response(request: Request, chat_request: ChatRequest):
    def event_stream():
        response = client.chat.completions.create(
            model=chat_request.model,
            messages=[message.dict() for message in chat_request.messages],
            stream=True,
        )
        for chunk in response:
            if chunk.choices:
                content = chunk.choices[0].delta.content
                if content:
                    payload = json.dumps({"content": content})
                    yield f"data: {payload}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "x-Accel-Buffering": "no"},
    )
@app.post("/generate")
def generate_response(generate_request: ChatRequest):
    response = generate(
        model=generate_request.model,
        messages=[message.dict() for message in generate_request.messages],
        environment=generate_request.environment,
    )
    return {"response": response.choices[0].message.content}
