from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ApiKeyResponse(BaseModel):
    api_key: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None = None

    model_config = {"from_attributes": True}
