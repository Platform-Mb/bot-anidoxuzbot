import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

BOT_TOKEN = CONFIG["bot_token"]
CHANNELS = CONFIG["channels"]
ADMINS = CONFIG["admins"]

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


# ---------- Foydalanuvchilar bazasi ----------
class UsersDB:
    FILE = BASE_DIR / "users.json"

    @classmethod
    def load(cls) -> list:
        if not cls.FILE.exists():
            return []
        with open(cls.FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    @classmethod
    def save(cls, data: list):
        with open(cls.FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def add(cls, user_id: int, username: str):
        data = cls.load()
        for u in data:
            if u["id"] == user_id:
                u["username"] = username
                u["last_active"] = datetime.now().isoformat()
                cls.save(data)
                return False
        data.append(
            {
                "id": user_id,
                "username": username,
                "joined": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
            }
        )
        cls.save(data)
        return True


# ---------- Obuna tekshirish yordamchilari ----------
async def get_chat_id(bot: Bot, identifier: str):
    try:
        if str(identifier).startswith("-100"):
            return int(identifier)
        chat = await bot.get_chat(identifier)
        return chat.id
    except Exception:
        return None


async def is_subscribed(bot: Bot, user_id: int, channel_id: str) -> bool:
    chat_id = await get_chat_id(bot, channel_id)
    if chat_id is None:
        return True
    try:
        status = (await bot.get_chat_member(chat_id, user_id)).status
        return status in ("member", "administrator", "creator")
    except Exception:
        return False


def subscribe_markup() -> InlineKeyboardMarkup:
    buttons = []
    row_a = []
    for ch in CHANNELS[:2]:
        row_a.append(InlineKeyboardButton(text=ch["title"], url=ch["invite"]))
    if row_a:
        buttons.append(row_a)
    row_b = []
    for ch in CHANNELS[2:4]:
        row_b.append(InlineKeyboardButton(text=ch["title"], url=ch["invite"]))
    if row_b:
        buttons.append(row_b)
    buttons.append(
        [
            InlineKeyboardButton(
                text="✅ Tekshirish", callback_data="check_subscription"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin_users")],
            [InlineKeyboardButton(text="📣 Xabar yuborish", callback_data="admin_broadcast")],
        ]
    )


# ---------- /start ----------
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = message.from_user
    UsersDB.add(user.id, user.username or "")

    for ch in CHANNELS:
        if not await is_subscribed(bot, user.id, ch["id"]):
            await message.answer(
                "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n"
                "👇 Quyidagi kanallarga obuna bo'lgandan so'ng <b>\"✅ Tekshirish\"</b> tugmasini bosing.",
                reply_markup=subscribe_markup(),
            )
            return

    await message.answer(
        "✅ <b>Xush kelibsiz!</b>\n\n"
        "Siz barcha kanallarga obuna bo'lgansiz va botdan to'liq foydalanishingiz mumkin.",
    )


# ---------- Tekshirish tugmasi ----------
@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: CallbackQuery):
    user = callback.from_user
    for ch in CHANNELS:
        if not await is_subscribed(bot, user.id, ch["id"]):
            await callback.answer("⚠️ Hali ham obuna bo'lmagansiz!", show_alert=True)
            return

    await callback.answer("✅ Barcha obunalar tasdiqlandi!", show_alert=True)
    try:
        await callback.message.edit_text(
            "✅ <b>Xush kelibsiz!</b>\n\n"
            "Siz barcha kanallarga obuna bo'lgansiz va botdan to'liq foydalanishingiz mumkin."
        )
    except Exception:
        await callback.message.answer(
            "✅ <b>Xush kelibsiz!</b>\n\n"
            "Siz barcha kanallarga obuna bo'lgansiz va botdan to'liq foydalanishingiz mumkin."
        )


# ---------- Admin panel ----------
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMINS:
        return
    await message.answer("⚙️ <b>Admin panel</b>", reply_markup=admin_keyboard())


class BroadcastStates(StatesGroup):
    text = State()


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        return
    users = UsersDB.load()
    await callback.answer()
    await callback.message.answer(f"👥 Jami foydalanuvchilar: <b>{len(users)}</b>")


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        return
    await callback.answer()
    await callback.message.answer("📝 Yuborish uchun xabar matnini kiriting:")
    await state.set_state(BroadcastStates.text)


@dp.message(BroadcastStates.text)
async def broadcast_send(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    users = UsersDB.load()
    ok = 0
    fail = 0
    for u in users:
        try:
            await bot.send_message(u["id"], message.text)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await message.answer(
        f"📣 Xabar yuborildi.\n✅ Muvaffaqiyatli: <b>{ok}</b>\n❌ Xato: <b>{fail}</b>\n👥 Jami: <b>{len(users)}</b>"
    )
    await state.clear()


# ---------- Bot boshlanishi ----------
async def main():
    logging.info("Bot ishga tushmoqda...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
