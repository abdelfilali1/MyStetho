from pydantic import BaseModel, EmailStr
from typing import Optional


class UserCreate(BaseModel):
    email: str
    password: str
    first_name: str
    last_name: str
    role: str = "medecin"
    specialty: Optional[str] = None
    phone: Optional[str] = None


class UserLogin(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    first_name: str
    last_name: str
    role: str
    specialty: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = True
