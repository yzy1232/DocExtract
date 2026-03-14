import asyncio
from app.database import engine
from sqlalchemy import text
async def main():
    async with engine.connect() as conn:
        res = await conn.execute(text('SELECT * FROM llm_configs'))
        for r in res.fetchall():
            print(r)
        
asyncio.run(main())
