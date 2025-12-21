import os
import asyncpg
from typing import Optional, Dict, Any, List

DATABASE_URL = os.getenv("DATABASE_URL", "")

_pool: Optional[asyncpg.Pool] = None

async def init_db():
    global _pool
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is not set")

    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    async with _pool.acquire() as conn:
        # Профиль пользователя
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            language TEXT,
            name TEXT,
            goal TEXT,
            height_cm INT,
            weight_kg REAL,
            activity TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        );
        """)

        # История диалога (для контекста)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            role TEXT NOT NULL,          -- 'user' or 'assistant'
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id);
        """)

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        return dict(row) if row else None

async def upsert_user(user_id: int, **fields):
    # fields: name, goal, height_cm, weight_kg, activity, language, etc.
    set_parts = []
    values = [user_id]
    i = 2
    for k, v in fields.items():
        set_parts.append(f"{k}=${i}")
        values.append(v)
        i += 1

    # updated_at
    set_parts.append("updated_at=now()")

    set_sql = ", ".join(set_parts)

    async with _pool.acquire() as conn:
        await conn.execute(f"""
        INSERT INTO users (user_id)
        VALUES ($1)
        ON CONFLICT (user_id) DO UPDATE SET {set_sql};
        """, *values)

async def add_message(user_id: int, role: str, content: str):
    async with _pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages (user_id, role, content) VALUES ($1, $2, $3)",
            user_id, role, content
        )

async def get_recent_messages(user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT role, content
            FROM messages
            WHERE user_id=$1
            ORDER BY id DESC
            LIMIT $2
        """, user_id, limit)

    # Вернем в правильном порядке (старые -> новые)
    rows = list(reversed(rows))
    return [{"role": r["role"], "content": r["content"]} for r in rows]
