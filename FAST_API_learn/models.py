from pydantic import BaseModel

class Promptrequest(BaseModel):
    prompt: str

class Promptresponse(BaseModel):
    response: str
    model: str
    status: str