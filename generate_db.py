import aiosqlite
import asyncio

async def create_database():
    async with aiosqlite.connect('chat_data.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                author TEXT,
                content TEXT,
                tag TEXT
            )
        ''')
        await db.commit()

if __name__ == '__main__':
    asyncio.run(create_database())
