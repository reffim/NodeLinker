from typing import Optional
import uuid
from pydantic import BaseModel, EmailStr, field_validator


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("username must be alphanumeric (underscores/hyphens allowed)")
        if len(v) < 3 or len(v) > 64:
            raise ValueError("username must be 3-64 characters")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    role: str
    oidc_provider: Optional[str] = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    user: UserResponse
    token_type: str = "bearer"


class OIDCLoginResponse(BaseModel):
    authorization_url: str
