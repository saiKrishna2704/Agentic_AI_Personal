from fastapi import FastAPI, HTTPException
from openai import OpenAI
from models import Promptrequest, Promptresponse
from config import openai_api_key, model_name

app = FastAPI(
    title="AI Agentic API",
    description="A simple API for interacting with the OpenAI GPT-3 model",
    version="1.0.0"
)
client = OpenAI(api_key=openai_api_key)

@app.get("/")
def home():
    return {
        "message": "FastAPI LLM Application is running."
    }


@app.post(
    "/generate",
    response_model=Promptresponse
)

def generate_response(request: Promptrequest):
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "user",
                    "content": request.prompt
                }
            ],
            temperature=0.2,
            max_tokens=300
        )

        generated_text = (
            response.choices[0]
            .message
            .content
        )

        return {
            "response": generated_text,
            "model": model_name,
            "status": "success"
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )
