from pydantic import BaseModel, EmailStr, field_validator
from app.modules.auth.utils import validate_password_strength, strip_email


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    def strip_email_whitespace(cls, email):
        return strip_email(email)

    @field_validator("password")
    def validate_password(cls, pwd):
        return validate_password_strength(pwd)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    def strip_email_whitespace(cls, email):
        return strip_email(email)


class LoginResponse(BaseModel):
    access_token: str


class RefreshResponse(BaseModel):
    access_token: str


class OAuthSessionRequest(BaseModel):
    access_token: str
    refresh_token: str
