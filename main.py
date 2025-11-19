import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from database import db, create_document, get_documents
from schemas import User, BlogPost, ContactMessage

SECRET_KEY = os.getenv("SECRET_KEY", "devsecret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

app = FastAPI(title="SaaS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: str
    password: str


# -----------------------------
# Helpers
# -----------------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow().timestamp() + ACCESS_TOKEN_EXPIRE_MINUTES * 60})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_user_by_email(email: str) -> Optional[dict]:
    users = get_documents("user", {"email": email}, limit=1)
    return users[0] if users else None


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user_by_email(email)
    if not user:
        raise credentials_exception
    return user


# -----------------------------
# Health & Schema
# -----------------------------
@app.get("/")
def root():
    return {"message": "SaaS API running"}


@app.get("/schema")
def get_schema():
    return {
        "collections": [
            {"name": "user", "schema": User.model_json_schema()},
            {"name": "blogpost", "schema": BlogPost.model_json_schema()},
            {"name": "contactmessage", "schema": ContactMessage.model_json_schema()},
        ]
    }


@app.get("/test")
def test_database():
    response = {
        "backend": "OK",
        "database": "Connected" if db is not None else "Not Available",
        "collections": []
    }
    if db is not None:
        try:
            response["collections"] = db.list_collection_names()
        except Exception as e:
            response["database"] = f"Error: {str(e)[:80]}"
    return response


# -----------------------------
# Auth
# -----------------------------
@app.post("/auth/register", response_model=Token)
def register(user: User):
    if get_user_by_email(user.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = get_password_hash(user.password_hash)
    data = user.model_dump()
    data["password_hash"] = hashed
    create_document("user", data)
    token = create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}


@app.post("/auth/login", response_model=Token)
def login(payload: LoginRequest):
    user = get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    token = create_access_token({"sub": user["email"]})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/auth/me")
async def me(current_user: dict = Depends(get_current_user)):
    user = {k: v for k, v in current_user.items() if k not in ["password_hash"]}
    return user


# -----------------------------
# Blog
# -----------------------------
@app.get("/blog", response_model=List[BlogPost])
def list_posts():
    docs = get_documents("blogpost", {"status": "published"}, limit=20)
    posts = []
    for d in docs:
        d.pop("_id", None)
        posts.append(BlogPost(**d))
    return posts


class BlogCreate(BaseModel):
    title: str
    excerpt: Optional[str] = None
    content: str
    author_name: str
    tags: List[str] = []
    status: str = "published"


@app.post("/blog", response_model=BlogPost)
async def create_post(payload: BlogCreate, current_user: dict = Depends(get_current_user)):
    slug = payload.title.lower().strip().replace(" ", "-")
    doc = {
        "title": payload.title,
        "slug": slug,
        "excerpt": payload.excerpt,
        "content": payload.content,
        "author_name": payload.author_name,
        "tags": payload.tags,
        "status": payload.status,
        "published_at": datetime.utcnow() if payload.status == "published" else None,
    }
    create_document("blogpost", doc)
    return BlogPost(**doc)


# -----------------------------
# Contact
# -----------------------------
@app.post("/contact")
async def submit_contact(msg: ContactMessage):
    create_document("contactmessage", msg)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
