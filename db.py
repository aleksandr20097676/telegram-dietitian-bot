import os
import asyncpg
from typing import Optional, Dict, Any, List, Tuple

# Railway/PG могут давать разные переменные.
# Главное: в WEB-сервисе должен быть DATABASE_URL (мы ниже всё равно подстрахуемся).
def _get_database_url() -> str:
    return (
        os.getenv("DATABASE_URL", "").strip()
        or os.getenv("DATABASE_PUBLIC_URL", "").strip()
        or os.getenv("POSTGRES_URL", "").strip()
        or os.getenv("POSTGRESQL_URL", "").strip()
        or os.getenv("PGDATABASE_URL", "").strip()
    )

DATABASE_URL = _get_database_url()

_pool: Optional[asyncpg.Pool] = None


def _require_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool is not initialized. Call init_db() first.")
    return _pool


async def init_db() -> None:
    """
    Initialize asyncpg pool + create tables if not exist.
    
    ⚠️ IMPORTANT: This will DROP and recreate tables on first run!
    After first successful deployment, you should remove the DROP commands.
    """
    global _pool

    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is not set (set it in Railway WEB service variables).")

    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    pool = _require_pool()
    async with pool.acquire() as conn:
        # ⚠️ TODO: После первого успешного деплоя - УДАЛИ эти 3 строки!
        # Они нужны только ОДИН РАЗ чтобы пересоздать таблицы с правильной структурой
        await conn.execute("DROP TABLE IF EXISTS messages CASCADE;")
        await conn.execute("DROP TABLE IF EXISTS user_facts CASCADE;")
        await conn.execute("DROP TABLE IF EXISTS users CASCADE;")
        
        # 1) Профиль пользователя: хранит "последние" известные значения
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     BIGINT PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            language    TEXT,

            -- то, что бот собирает по анкете:
            name        TEXT,
            age         INT,
            goal        TEXT,
            height_cm   INT,
            weight_kg   REAL,
            activity    TEXT,

            created_at  TIMESTAMPTZ DEFAULT now(),
            updated_at  TIMESTAMPTZ DEFAULT now()
        );
        """)

        # 2) История диалога (контекст)
        # ✅ PRODUCTION: Foreign key включён для целостности данных
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id          BIGSERIAL PRIMARY KEY,
            user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TIMESTAMPTZ DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_messages_user_id_id ON messages(user_id, id);
        """)

        # 3) Универсальные факты о пользователе (ключ-значение)
        # ✅ PRODUCTION: Foreign key включён для целостности данных
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_facts (
            user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            key         TEXT NOT NULL,
            value       TEXT NOT NULL,
            updated_at  TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (user_id, key)
        );
        CREATE INDEX IF NOT EXISTS idx_user_facts_user_id ON user_facts(user_id);
        """)


# -----------------------
# Users (profile)
# -----------------------

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        return dict(row) if row else None


async def ensure_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    language: Optional[str] = None
) -> None:
    """
    Create user row if it doesn't exist, and update basic telegram fields.
    """
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, first_name, language)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE SET
                username   = COALESCE(EXCLUDED.username, users.username),
                first_name = COALESCE(EXCLUDED.first_name, users.first_name),
                language   = COALESCE(EXCLUDED.language, users.language),
                updated_at = now();
        """, user_id, username, first_name, language)


# ✅ ИСПРАВЛЕНИЕ: Алиас для совместимости с main.py
ensure_user_exists = ensure_user


async def upsert_user(user_id: int, **fields: Any) -> None:
    """
    Upsert any profile fields into users, keeping the latest value.
    Example: upsert_user(user_id, goal="похудеть", weight_kg=112.5)
    """
    if not fields:
        return

    allowed = {
        "username", "first_name", "language",
        "name", "age", "goal", "height_cm", "weight_kg", "activity",
    }

    clean_fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not clean_fields:
        return

    cols = list(clean_fields.keys())
    vals = list(clean_fields.values())

    # строим INSERT(user_id, col1, col2...) VALUES($1, $2...)
    insert_cols = ["user_id"] + cols
    placeholders = [f"${i}" for i in range(1, len(insert_cols) + 1)]

    # ON CONFLICT: обновляем только те поля, что пришли
    set_sql = ", ".join([f"{c}=EXCLUDED.{c}" for c in cols] + ["updated_at=now()"])

    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            INSERT INTO users ({", ".join(insert_cols)})
            VALUES ({", ".join(placeholders)})
            ON CONFLICT (user_id) DO UPDATE SET {set_sql};
            """,
            user_id, *vals
        )


# -----------------------
# Messages (history)
# -----------------------

async def add_message(user_id: int, role: str, content: str) -> None:
    # ✅ ИСПРАВЛЕНО: Создаём пользователя если его нет
    await ensure_user(user_id)
    
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages (user_id, role, content) VALUES ($1, $2, $3)",
            user_id, role, content
        )


async def get_recent_messages(user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT role, content
            FROM messages
            WHERE user_id=$1
            ORDER BY id DESC
            LIMIT $2
        """, user_id, limit)

    rows = list(reversed(rows))
    return [{"role": r["role"], "content": r["content"]} for r in rows]


async def trim_messages(user_id: int, keep_last: int = 60) -> None:
    """
    Optional: keep only last N messages per user (чтобы база не разрасталась).
    """
    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            DELETE FROM messages
            WHERE user_id = $1
              AND id NOT IN (
                  SELECT id FROM messages
                  WHERE user_id = $1
                  ORDER BY id DESC
                  LIMIT $2
              );
        """, user_id, keep_last)


# -----------------------
# Facts (memory key/value)
# -----------------------

async def set_fact(user_id: int, key: str, value: str) -> None:
    """
    Save/overwrite a single fact. Always keeps last value.
    ✅ ИСПРАВЛЕНО: Автоматически создаёт пользователя если его нет!
    """
    key = key.strip().lower()
    value = value.strip()

    if not key or not value:
        return

    # ✅ ВАЖНО: Создаём пользователя ПЕРЕД вставкой факта!
    await ensure_user(user_id)

    pool = _require_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_facts (user_id, key, value)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = now();
        """, user_id, key, value)


async def set_facts(user_id: int, facts: Dict[str, str]) -> None:
    """
    Save multiple facts in one transaction.
    ✅ ИСПРАВЛЕНО: Автоматически создаёт пользователя если его нет!
    """
    if not facts:
        return

    # ✅ ВАЖНО: Создаём пользователя ПЕРЕД вставкой фактов!
    await ensure_user(user_id)

    pool = _require_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for k, v in facts.items():
                if k is None or v is None:
                    continue
                k2 = str(k).strip().lower()
                v2 = str(v).strip()
                if not k2 or not v2:
                    continue
                await conn.execute("""
                    INSERT INTO user_facts (user_id, key, value)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = now();
                """, user_id, k2, v2)


async def get_fact(user_id: int, key: str) -> Optional[str]:
    key = key.strip().lower()
    if not key:
        return None

    pool = _require_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT value FROM user_facts
            WHERE user_id=$1 AND key=$2
        """, user_id, key)
        return row["value"] if row else None


async def get_all_facts(user_id: int) -> Dict[str, str]:
    pool = _require_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT key, value
            FROM user_facts
            WHERE user_id=$1
            ORDER BY key ASC
        """, user_id)

    return {r["key"]: r["value"] for r in rows}
