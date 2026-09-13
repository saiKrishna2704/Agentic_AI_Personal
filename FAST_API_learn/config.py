from dotenv import load_dotenv
import os

load_dotenv()

openai_api_key = os.getenv("OpenAI_API_KEY")
model_name = os.getenv("MODEL_NAME")
environment = os.getenv("ENVIRONMENT")
print(openai_api_key, model_name, environment)