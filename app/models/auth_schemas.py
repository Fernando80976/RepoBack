from pydantic import BaseModel, EmailStr

class LoginSchema(BaseModel):
    identifier: str
    password: str

class SignupSchema(BaseModel):
    email: EmailStr
    password: str
    username: str 