import asyncio
import json
import os
from telethon import events, TelegramClient
from telethon.tl.types import UserStatusOnline
import datetime
from telethon import functions

class UserHandler:
    def __init__(self, queue_from_bot, queue_to_bot, keys_path="../config/keys.json",
                 ignored_chats_path="../config/ignored_chats.json",
                 all_chats_path="../config/all_chats.json",
                 config_path="../config/config.json",
                 user_session_path="../config/user_session.session"):
        if not os.path.exists(keys_path):
            raise Exception(f"Invalid keys_path: {keys_path} doesn't exist")

        try:
            with open(keys_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            self.API_ID = config["API_ID"]
            self.API_HASH = config["API_HASH"]
            self.BOT_USERNAME = config["BOT_USERNAME"]
            self.USER_ID = config["USER_ID"]
        except Exception as e:
            raise Exception(f"Some of keys in {keys_path} seems to be invalid: {e}")

        if not os.path.exists(config_path):
            config = {
                "READ_NEW_POSTS": True,
                "STAY_OFFLINE": True
            }
            with open(config_path, "w", encoding="utf-8") as f:
                # noinspection PyTypeChecker
                json.dump(config, f, ensure_ascii=False, indent=4)

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            self.MARK_AS_UNREAD = config["MARK_AS_UNREAD"]
            self.STAY_OFFLINE = config["STAY_OFFLINE"]

        except Exception as e:
            raise Exception(f"Some of parameters in {config_path} seems to be invalid: {e}")

        self.IGNORED_CHATS_PATH = ignored_chats_path
        self.ALL_CHATS_PATH = all_chats_path

        self.queue_from_bot = queue_from_bot
        self.queue_to_bot = queue_to_bot
        self.chat_ids = []
        self.user_client = TelegramClient(user_session_path, self.API_ID, self.API_HASH, system_version='4.16.30-vxCUSTOM')
        self.unread_queue = asyncio.Queue()

        self.user_client.on(events.UserUpdate(chats=self.USER_ID))(self.handle_user_update)

    async def handle_chat_message(self, event):
        status = (await self.user_client.get_me()).status
        if self.STAY_OFFLINE and not isinstance(status, UserStatusOnline):
            await self.unread_queue.put((event.chat_id, event.message))
        else:
            await self.user_client.send_read_acknowledge(event.chat_id, event.message)
            if self.MARK_AS_UNREAD:
                await self.user_client(functions.messages.MarkDialogUnreadRequest(peer=event.chat_id, unread=True))


    async def handle_user_update(self, event):
        if isinstance(event.status, UserStatusOnline):
            while not self.unread_queue.empty():
                chat_id, msg = await self.unread_queue.get()
                await self.user_client.send_read_acknowledge(chat_id, msg)
                if self.MARK_AS_UNREAD:
                    await self.user_client(functions.messages.MarkDialogUnreadRequest(peer=chat_id, unread=True))

    # noinspection PyTypeChecker
    def reload_ignored_chats(self):
        if not os.path.exists(self.IGNORED_CHATS_PATH):
            with open(self.IGNORED_CHATS_PATH, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=4)

        with open(self.IGNORED_CHATS_PATH, "r", encoding="utf-8") as f:
            ignored_chats = json.load(f)
        self.chat_ids = [channel["id"] for channel in ignored_chats]

        self.user_client.remove_event_handler(self.handle_chat_message)
        self.user_client.on(events.NewMessage(chats=self.chat_ids))(self.handle_chat_message)

    # noinspection PyTypeChecker
    async def initialize_all_chats(self):
        chats = dict()
        dialogs = await self.user_client.get_dialogs()
        for chat in dialogs:
            chats[chat.title] = chat.id

        formatted_chats = [{"name": key, "id": value} for key, value in chats.items()]

        with open(self.ALL_CHATS_PATH, "w", encoding="utf-8") as f:
            json.dump(formatted_chats, f, ensure_ascii=False, indent=4)

    async def start(self):
        await self.user_client.start()
        await self.initialize_all_chats()
        self.reload_ignored_chats()
        print(f"{datetime.datetime.now()}\n🔷UserHandler🔷: Пользовательский клиент запущен.")

    async def run_until_disconnected(self):
        await asyncio.gather(
            self.user_client.run_until_disconnected(),
            self.listen_for_signals()
        )

    async def listen_for_signals(self):
        while True:
            signal = await self.queue_from_bot.get()
            if signal == "RELOAD_CHATS":
                self.reload_ignored_chats()
                await self.queue_to_bot.put("RELOAD_ACK")
            elif signal == "INITIALIZE_CHATS":
                await self.initialize_all_chats()
                await self.queue_to_bot.put("INITIALIZE_ACK")
