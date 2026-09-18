import asyncio
import logging
from core import tg
from telegram_bot import handle_update

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("telegram_poll")

async def main():
    if not tg.enabled:
        logger.error("Telegram token not set; bot disabled.")
        return

    logger.info("Starting Telegram bot polling...")
    
    # Delete webhook first so polling works
    del_res = await tg._call("deleteWebhook", {"drop_pending_updates": True})
    logger.info("deleteWebhook -> %s", del_res)
    
    me = await tg.get_me()
    if me.get("ok"):
        logger.info("Bot: @%s", me["result"]["username"])
    else:
        logger.error("Failed to fetch bot info. Check your token! Details: %s", me)
        return

    offset = 0
    while True:
        try:
            res = await tg._call("getUpdates", {"offset": offset, "timeout": 15})
            if res.get("ok"):
                for update in res["result"]:
                    offset = update["update_id"] + 1
                    asyncio.create_task(handle_update(update))
            else:
                logger.error("Failed to get updates: %s", res)
                await asyncio.sleep(3)
        except Exception as e:
            logger.exception("Polling error: %s", e)
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
