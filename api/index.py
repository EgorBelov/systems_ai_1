from __future__ import annotations

import hashlib
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerifyMismatchError
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, String, create_engine, select
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)
from sqlalchemy.pool import NullPool

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_DIR / ".env")
except Exception:
    pass


def _db_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        return "sqlite:///" + str(PROJECT_DIR / "todos.db")
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DB_URL = _db_url()
IS_SQLITE = DB_URL.startswith("sqlite")

if IS_SQLITE:
    _connect_args = {"check_same_thread": False}
else:
    # Supabase Connection Pooling (transaction mode) не поддерживает
    # server-side prepared statements — отключаем их в psycopg.
    _connect_args = {"prepare_threshold": None}
engine = create_engine(
    DB_URL,
    poolclass=NullPool,
    pool_pre_ping=True,
    connect_args=_connect_args,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SessionToken(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


SESSION_COOKIE = "session"
SESSION_TTL = timedelta(days=30)
COOKIE_SECURE = (os.environ.get("COOKIE_SECURE", "1") or "1") != "0"
_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, Argon2Error):
        return False
    except Exception:
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        SessionToken(
            id=_hash_token(token),
            user_id=user.id,
            expires_at=_utcnow() + SESSION_TTL,
        )
    )
    db.commit()
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Требуется вход")

    row = db.get(SessionToken, _hash_token(token))
    if row is None:
        raise HTTPException(status_code=401, detail="Сессия не найдена")

    if _as_aware(row.expires_at) < _utcnow():
        db.delete(row)
        db.commit()
        raise HTTPException(status_code=401, detail="Сессия истекла")

    user = db.get(User, row.user_id)
    if user is None:
        db.delete(row)
        db.commit()
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Todo", lifespan=lifespan)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str


class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)


class TodoUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    done: Optional[bool] = None


class TodoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    done: bool
    created_at: datetime


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/auth/register", response_model=UserOut, status_code=201)
def register(payload: RegisterIn, response: Response, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Этот email уже зарегистрирован")

    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_session(db, user)
    set_session_cookie(response, token)
    return user


@app.post("/api/auth/login", response_model=UserOut)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(user.password_hash, payload.password):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    token = create_session(db, user)
    set_session_cookie(response, token)
    return user


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        row = db.get(SessionToken, _hash_token(token))
        if row is not None:
            db.delete(row)
            db.commit()
    clear_session_cookie(response)


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@app.get("/api/todos", response_model=list[TodoOut])
def list_todos(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Todo).where(Todo.user_id == user.id).order_by(Todo.done, Todo.id.desc())
    ).all()
    return list(rows)


@app.post("/api/todos", response_model=TodoOut, status_code=201)
def create_todo(
    payload: TodoCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Название не может быть пустым")

    todo = Todo(user_id=user.id, title=title)
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return todo


@app.patch("/api/todos/{todo_id}", response_model=TodoOut)
def update_todo(
    todo_id: int,
    payload: TodoUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    todo = db.get(Todo, todo_id)
    if todo is None or todo.user_id != user.id:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="Нет полей для обновления")

    if "title" in fields:
        title = (fields["title"] or "").strip()
        if not title:
            raise HTTPException(status_code=422, detail="Название не может быть пустым")
        todo.title = title
    if "done" in fields:
        todo.done = bool(fields["done"])

    db.commit()
    db.refresh(todo)
    return todo


@app.delete("/api/todos/{todo_id}", status_code=204)
def delete_todo(
    todo_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    todo = db.get(Todo, todo_id)
    if todo is None or todo.user_id != user.id:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    db.delete(todo)
    db.commit()


def _find_static_dir() -> Optional[Path]:
    for candidate in (
        PROJECT_DIR / "public",
        BASE_DIR / "public",
        Path.cwd() / "public",
    ):
        if candidate.is_dir():
            return candidate
    return None


_static_dir = _find_static_dir()
if _static_dir is not None:
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
