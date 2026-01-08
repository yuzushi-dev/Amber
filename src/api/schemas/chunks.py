from pydantic import BaseModel

class ChunkUpdate(BaseModel):
    content: str
