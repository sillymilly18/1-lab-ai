"""Постоянные настройки и история пользователей в PostgreSQL."""


class HistoryStore:
    def __init__(self, pool):
        self.pool = pool

    async def initialize(self):
        await self.pool.execute("""
            CREATE TABLE IF NOT EXISTS lab1_users (
                user_id BIGINT PRIMARY KEY,
                mode TEXT NOT NULL DEFAULT 'study',
                temperature DOUBLE PRECISION NOT NULL DEFAULT 0.3
                    CHECK (temperature IN (0.0, 0.3, 0.7, 1.0))
            );
            CREATE TABLE IF NOT EXISTS lab1_messages (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES lab1_users(user_id),
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS lab1_messages_user_order
                ON lab1_messages(user_id, id);
        """)

    async def settings(self, user_id):
        await self.pool.execute(
            "INSERT INTO lab1_users(user_id) VALUES($1) ON CONFLICT DO NOTHING", user_id
        )
        row = await self.pool.fetchrow(
            "SELECT mode, temperature FROM lab1_users WHERE user_id=$1", user_id
        )
        return dict(row)

    async def history(self, user_id, limit):
        rows = await self.pool.fetch(
            """
            SELECT role, content FROM (
                SELECT id, role, content FROM lab1_messages
                WHERE user_id=$1 ORDER BY id DESC LIMIT $2
            ) recent ORDER BY id
        """,
            user_id,
            limit // 2 * 2,
        )
        return [dict(row) for row in rows]

    async def reset(self, user_id):
        await self.pool.execute("DELETE FROM lab1_messages WHERE user_id=$1", user_id)

    async def switch(self, user_id, mode):
        await self.settings(user_id)
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "UPDATE lab1_users SET mode=$2 WHERE user_id=$1", user_id, mode
                )
                await connection.execute("DELETE FROM lab1_messages WHERE user_id=$1", user_id)

    async def temperature(self, user_id, value):
        await self.settings(user_id)
        await self.pool.execute(
            "UPDATE lab1_users SET temperature=$2 WHERE user_id=$1", user_id, value
        )

    async def save_turn(self, user_id, text, answer, max_messages):
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.executemany(
                    "INSERT INTO lab1_messages(user_id,role,content) VALUES($1,$2,$3)",
                    [(user_id, "user", text), (user_id, "assistant", answer)],
                )
                # Храним целые пары, максимум задаётся конфигурацией.
                keep = max_messages // 2 * 2
                await connection.execute(
                    """
                    DELETE FROM lab1_messages WHERE user_id=$1 AND id NOT IN (
                        SELECT id FROM lab1_messages WHERE user_id=$1
                        ORDER BY id DESC LIMIT $2
                    )
                """,
                    user_id,
                    keep,
                )
