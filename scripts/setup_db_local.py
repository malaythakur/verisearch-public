"""Create the documents table on the local verisearch Postgres (host port 5442)."""
import asyncio
import asyncpg

DSN = "postgresql://agentic:agentic_dev@localhost:5442/agentic_research"

DDL = """
CREATE TABLE IF NOT EXISTS documents (
    document_id   TEXT PRIMARY KEY,
    source_url    TEXT UNIQUE NOT NULL,
    version       INTEGER NOT NULL DEFAULT 1,
    content_hash  TEXT,
    cleaned_text  TEXT,
    visible       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    await conn.execute(DDL)
    count = await conn.fetchval("SELECT COUNT(*) FROM documents")
    await conn.close()
    print(f"documents table ready. rows={count}")


if __name__ == "__main__":
    asyncio.run(main())
