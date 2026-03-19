from pydantic import BaseModel,EmailStr,field_validator
import re

class RegisterRequest(BaseModel):
    email:EmailStr
    password:str

    @field_validator("password")
    @classmethod
    def password_strength(cls,v:str)->str:
        if(len(v)<8):
            raise ValueError("Password must be atleast 8 characters")
        if not re.search(r"[A-Z]",v):
            raise ValueError("Password must contain uppercase letter")
        if not re.search(r"[0-9]",v):
            raise ValueError("Password must contain numeric character")
        return v
    
class LoginRequest(BaseModel):
    email:EmailStr
    password:str

class TokenResponse(BaseModel):
    access_token:str
    refresh_token:str
    token_type:str="bearer"

class RefreshRequest(BaseModel):
    refresh_token:str