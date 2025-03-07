import json
import asyncio
import os
from telethon import events, TelegramClient, types
from telethon.tl.custom import Button
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.types import BotCommand
import datetime


class BotHandler:
    def __init__(self, queue_from_bot, queue_to_bot, keys_path="../config/keys.json",
                 ignored_chats_path="../config/ignored_chats.json",
                 all_chats_path="../config/all_chats.json",
                 bot_session_path="../config/bot_session.session"):
        if not os.path.exists(keys_path):
            raise Exception(f"Invalid keys_path: {keys_path} doesn't exist")

        try:
            with open(keys_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            self.API_ID = config["API_ID"]
            self.API_HASH = config["API_HASH"]
            self.BOT_TOKEN = config["BOT_API_TOKEN"]
            self.USER_ID = config["USER_ID"]
        except Exception as e:
            raise Exception(f"Some of keys in {keys_path} seems to be invalid: {e}")

        self.IGNORED_CHATS_PATH = ignored_chats_path
        self.ALL_CHATS_PATH = all_chats_path
        self.queue_from_bot = queue_from_bot
        self.queue_to_bot = queue_to_bot

        self.chats_per_page = 15
        self.management_chats_per_page = 10  # 10 чатов на страницу для меню управления

        self.reload_event = asyncio.Event()
        self.initialize_event = asyncio.Event()
        self.all_chats_buffer = []
        self.ignored_chats_buffer = []

        self.bot_client = TelegramClient(bot_session_path, self.API_ID, self.API_HASH,
                                         system_version='4.16.30-vxCUSTOM')
        self.bot_client.on(events.NewMessage())(self.handle_message)
        self.bot_client.on(events.CallbackQuery())(self.handle_callback_query)
        self.bot_client.on(events.InlineQuery())(self.handle_inline_query)

    async def show_main_menu(self, event, message=None):
        buttons = [
            [
                Button.inline("⚙️ Управление чатами", data="manage_chats_menu"),
                types.KeyboardButtonSwitchInline("🔍 Поиск чатов", query="", same_peer=True)
            ],
            [
                Button.inline("🔄 Обновить список", data="refresh_chats")
            ]
        ]
        text = "Главное меню управления чатами:\nВыберите действие:"
        if message:
            await event.edit(text, buttons=buttons)
        else:
            await event.respond(text, buttons=buttons)

    async def handle_message(self, event):
        if event.sender_id != self.USER_ID:
            await self.bot_client.send_message(event.sender_id, "У вас нет доступа к этому боту")
            return

        if event.message.text == '/start' or not event.message.text.startswith('/'):
            await self.show_main_menu(event)

    async def handle_callback_query(self, event):
        query = event.query
        data = query.data.decode("utf-8")

        if data == "manage_chats_menu":
            await self.show_chat_management_menu(event)
        elif data == "refresh_chats":
            await self.refresh_all_chats(event)
        elif data.startswith("page_manage_"):
            parts = data.split("_")
            page_num = int(parts[-1])
            await self.send_chat_management_page(event, page_num)
        elif data.startswith("manage_chat_"):
            parts = data.split("_")
            chat_id = int(parts[2])
            page_num = int(parts[4])
            await self.show_individual_chat_management(event, chat_id, page_num)
        elif data.startswith("toggle_unread_"):
            parts = data.split("_")
            chat_id = int(parts[2])
            page_num = int(parts[4])
            await self.toggle_unread_handler(event, chat_id, page_num)
        elif data.startswith("add_chat_"):
            await self.add_chat_handler(event, data)
        elif data.startswith("remove_chat_"):
            await self.remove_chat_handler(event, data)
        elif data == "back_to_menu":
            await self.show_main_menu(event, message=True)
        await event.answer()

    async def show_chat_management_menu(self, event):
        if not self.ignored_chats_buffer:
            await event.edit("Нет чатов для управления.", buttons=self.back_button())
            return

        # Начинаем с первой страницы (номер 0)
        await self.send_chat_management_page(event, 0)

    async def send_chat_management_page(self, event, page_num):
        pages = [self.ignored_chats_buffer[i:i + self.management_chats_per_page]
                 for i in range(0, len(self.ignored_chats_buffer), self.management_chats_per_page)]
        if page_num < 0 or page_num >= len(pages):
            await event.edit("Некорректная страница.", buttons=self.back_button())
            return

        page = pages[page_num]
        text = f"Страница {page_num + 1}/{len(pages)}\nВыберите чат для управления:\n\n"
        for idx, chat in enumerate(page, start=page_num * self.management_chats_per_page + 1):
            text += f"{idx}. {chat['name']}\n"

        buttons = []
        # Для каждой кнопки перед именем чата добавляем эмодзи:
        # 🔔 если mark_this_as_unread == True, иначе 🔕
        for chat in page:
            emoji = "🔔" if chat.get("mark_this_as_unread", False) else "🔕"
            buttons.append([Button.inline(f"{emoji} {chat['name']}", data=f"manage_chat_{chat['id']}_page_{page_num}")])

        nav_buttons = []
        if page_num > 0:
            nav_buttons.append(Button.inline("⬅️ Назад", data=f"page_manage_{page_num - 1}"))
        if page_num < len(pages) - 1:
            nav_buttons.append(Button.inline("Вперёд ➡️", data=f"page_manage_{page_num + 1}"))
        if nav_buttons:
            buttons.append(nav_buttons)

        buttons.append([self.back_button()])

        await event.edit(text, buttons=buttons)

    async def show_individual_chat_management(self, event, chat_id, page_num):
        chat = next((ch for ch in self.ignored_chats_buffer if ch["id"] == chat_id), None)
        if not chat:
            await event.answer("Чат не найден!", alert=True)
            return

        status_text = "Включено" if chat.get("mark_this_as_unread", False) else "Выключено"
        text = (f"Управление чатом:\n\n"
                f"Название: {chat['name']}\n"
                f"ID: {chat['id']}\n"
                f"Помечается непрочитанным: {status_text}\n\n"
                f"Выберите действие:")
        buttons = [
            [Button.inline("❌ Удалить чат", data=f"remove_chat_{chat['id']}_page_{page_num}")],
            [Button.inline("↩️ Переключить отметку", data=f"toggle_unread_{chat['id']}_page_{page_num}")],
            [Button.inline("🔙 Назад", data=f"page_manage_{page_num}")]
        ]
        await event.edit(text, buttons=buttons)

    async def toggle_unread_handler(self, event, chat_id, page_num):
        chat = next((ch for ch in self.ignored_chats_buffer if ch["id"] == chat_id), None)
        if not chat:
            await event.answer("Чат не найден!", alert=True)
            return

        chat["mark_this_as_unread"] = not chat.get("mark_this_as_unread", False)
        with open(self.IGNORED_CHATS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.ignored_chats_buffer, f, indent=4)

        await self.queue_from_bot.put("RELOAD_CHATS")
        self.reload_event.clear()
        await self.reload_event.wait()

        status_text = "Включено" if chat["mark_this_as_unread"] else "Выключено"
        answer_text = f"Теперь{' ' if chat['mark_this_as_unread'] else ' не '}помечается непрочитанным"
        await event.answer(answer_text, alert=True)
        await self.show_individual_chat_management(event, chat_id, page_num)

    async def remove_chat_handler(self, event, data):
        parts = data.split("_")
        chat_id = int(parts[2])
        page_num = int(parts[4])
        chat_to_remove = next((ch for ch in self.ignored_chats_buffer if ch["id"] == chat_id), None)

        if not chat_to_remove:
            await event.answer("Чат не найден!", alert=True)
            return

        self.ignored_chats_buffer = [ch for ch in self.ignored_chats_buffer if ch["id"] != chat_id]
        with open(self.IGNORED_CHATS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.ignored_chats_buffer, f, indent=4)

        await self.queue_from_bot.put("RELOAD_CHATS")
        self.reload_event.clear()
        await self.reload_event.wait()
        await event.answer(f"Чат {chat_to_remove['name']} удалён!", alert=True)

        if page_num == -1:
            return

        pages = [self.ignored_chats_buffer[i:i + self.management_chats_per_page]
                 for i in range(0, len(self.ignored_chats_buffer), self.management_chats_per_page)]
        if pages:
            if page_num >= len(pages):
                page_num = max(0, len(pages) - 1)
            await self.send_chat_management_page(event, page_num)
        else:
            await event.edit("Нет чатов для управления.", buttons=self.back_button())

    async def refresh_all_chats(self, event):
        await self.queue_from_bot.put("INITIALIZE_CHATS")
        self.initialize_event.clear()
        await self.initialize_event.wait()

        with open(self.ALL_CHATS_PATH, "r", encoding="utf-8") as f:
            self.all_chats_buffer = json.load(f)
        with open(self.IGNORED_CHATS_PATH, "r", encoding="utf-8") as f:
            self.ignored_chats_buffer = json.load(f)

        await event.answer("Список чатов обновлён!", alert=True)

    def back_button(self):
        return Button.inline("🔙 Назад", data="back_to_menu")

    async def add_chat_handler(self, event, data):
        chat_id = int(data.split("_")[2])
        chat_to_add = next((ch for ch in self.all_chats_buffer if ch["id"] == chat_id), None)

        if not chat_to_add:
            await event.answer("Чат не найден!", alert=True)
            return

        if any(ch["id"] == chat_id for ch in self.ignored_chats_buffer):
            await event.answer("Этот чат уже добавлен!", alert=True)
            return

        if "mark_this_as_unread" not in chat_to_add:
            chat_to_add["mark_this_as_unread"] = False

        self.ignored_chats_buffer.append(chat_to_add)
        with open(self.IGNORED_CHATS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.ignored_chats_buffer, f, indent=4)

        await self.queue_from_bot.put("RELOAD_CHATS")
        self.reload_event.clear()
        await self.reload_event.wait()
        await event.answer(f"Чат {chat_to_add['name']} добавлен!", alert=True)

    async def handle_inline_query(self, event):
        builder = event.builder
        query_text = (event.text or "").lower()
        results = []

        for chat in self.all_chats_buffer:
            if query_text in chat["name"].lower():
                article = builder.article(
                    title=chat["name"],
                    text=f"Чат: {chat['name']} (ID: {chat['id']})",
                    description=f"ID: {chat['id']}",
                    buttons=[
                        [Button.inline("➕ Добавить", data=f"add_chat_{chat['id']}")],
                        [Button.inline("➖ Удалить", data=f"remove_chat_{chat['id']}_page_-1")]
                    ]
                )
                results.append(article)
                if len(results) >= 15:
                    break

        await event.answer(results, cache_time=0)

    async def set_bot_commands(self):
        commands = [
            BotCommand(command="start", description="Open menu"),
        ]
        await self.bot_client(
            SetBotCommandsRequest(scope=types.BotCommandScopeDefault(), lang_code='en', commands=commands))

    async def start(self):
        await self.bot_client.start(bot_token=self.BOT_TOKEN)
        await self.set_bot_commands()
        with open(self.ALL_CHATS_PATH, "r", encoding="utf-8") as f:
            self.all_chats_buffer = json.load(f)
        with open(self.IGNORED_CHATS_PATH, "r", encoding="utf-8") as f:
            self.ignored_chats_buffer = json.load(f)

        print(f"{datetime.datetime.now()}\n🔴BotHandler🔴: Бот-клиент запущен.")

    async def run_until_disconnected(self):
        await asyncio.gather(
            self.bot_client.run_until_disconnected(),
            self.listen_for_signals()
        )

    async def listen_for_signals(self):
        while True:
            signal = await self.queue_to_bot.get()
            if signal == "RELOAD_ACK":
                self.reload_event.set()
            elif signal == "INITIALIZE_ACK":
                self.initialize_event.set()
