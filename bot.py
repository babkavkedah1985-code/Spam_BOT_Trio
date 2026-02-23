import re
from datetime import datetime, timedelta, timezone
from typing import Set, Dict, List

from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.constants import ChatMemberStatus

# ⚠️ ТВОИ ДАННЫЕ
TOKEN = "1543341831:AAGjnQb9uLLLmfyF_9rR-hLG8_uvNiXHbgM"

# 📋 СПИСОК РАЗРЕШЕННЫХ ГРУПП (можно добавлять как ID, так и username)
ALLOWED_CHATS: List[str | int] = [
    -3585377659,        # Группа 1 (по ID)
    -1001507274063,  # Группа 2 (по username)
    # Добавляй новые группы в любом формате:
    # -1001234567890,   # Еще группа по ID
    # "@another_group", # Еще группа по username
]

# Настройки фильтра
MUTE_DURATION: int = 120  # 1200 секунд (20 минут)

# Слова-триггеры
TRIGGER_WORDS: Set[str] = {
    "добавить", "дабавить", "номер", "дабавте", "добавте",
    "добавьте", "дабавьте", "заработай", "бизнес", "пассивный доход",
    "http", "https", "www", "com", "ru", "net", "org"
}

# Опасные символы
DANGEROUS_SYMBOLS: Set[str] = {'@', '#'}

restricted_users: Dict[int, datetime] = {}

def contains_emoji(text: str) -> bool:
    """Проверяет наличие смайликов"""
    if not text:
        return False
    
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F" u"\U0001F300-\U0001F5FF" 
        u"\U0001F680-\U0001F6FF" u"\U0001F1E0-\U0001F1FF" 
        u"\U00002702-\U000027B0" u"\U000024C2-\U0001F251"
        u"\U0001F900-\U0001F9FF" u"\U0001FA70-\U0001FAFF"
        "]+", flags=re.UNICODE)
    
    return bool(emoji_pattern.search(text))

def contains_trigger_words(text: str) -> bool:
    """Проверяет слова-триггеры"""
    if not text:
        return False
    text_lower = text.lower()
    return any(word in text_lower for word in TRIGGER_WORDS)

def contains_dangerous_symbols(text: str) -> bool:
    """Проверяет @ или #"""
    if not text:
        return False
    return any(symbol in text for symbol in DANGEROUS_SYMBOLS)

def contains_phone_number(text: str) -> bool:
    """Проверяет наличие номеров телефона"""
    if not text:
        return False
    
    clean_text = re.sub(r'[\s\-\(\)]', '', text)
    
    patterns = [
        r'\+79\d{7,}', r'89\d{7,}', r'8-9\d{6,}',
        r'8\s?9\s?\d{7,}', r'79\d{7,}',
    ]
    
    for pattern in patterns:
        if re.search(pattern, clean_text):
            return True
    
    digit_sequences = re.findall(r'\d{7,}', clean_text)
    if digit_sequences:
        return True
    
    return False

async def is_admin(update: Update, user_id: int) -> bool:
    """Проверка на администратора"""
    try:
        chat_member = await update.effective_chat.get_member(user_id)
        return chat_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except:
        return False

async def restrict_user(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """Блокировка пользователя"""
    try:
        until_time = datetime.now(timezone.utc) + timedelta(seconds=MUTE_DURATION)
        
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_time
        )
        
        restricted_users[user_id] = until_time
        
        try:
            await update.message.delete()
        except:
            pass
        
        return True
    except:
        return False

async def check_restrictions(context: ContextTypes.DEFAULT_TYPE):
    """Проверка и снятие блокировок"""
    if not context.job or not context.job.data:
        return
    
    chat_id = context.job.data
    current_time = datetime.now(timezone.utc)
    users_to_remove = []
    
    for user_id, restriction_time in list(restricted_users.items()):
        if current_time >= restriction_time:
            users_to_remove.append(user_id)
    
    for user_id in users_to_remove:
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            del restricted_users[user_id]
        except:
            pass

async def is_chat_allowed(chat: Update.effective_chat) -> bool:
    """Проверяет, разрешена ли группа"""
    # Проверка по ID
    if chat.id in ALLOWED_CHATS:
        return True
    
    # Проверка по username (если есть)
    if chat.username and f"@{chat.username}" in ALLOWED_CHATS:
        return True
    if chat.username and chat.username in ALLOWED_CHATS:
        return True
    
    return False

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основной обработчик"""
    message = update.message
    if not message:
        return
    
    chat = message.chat
    
    # 🔥 ПРОВЕРКА: если группа не в списке разрешенных - игнорируем
    if not await is_chat_allowed(chat):
        return
    
    user = message.from_user
    
    # Пропускаем администраторов
    if await is_admin(update, user.id):
        return
    
    # Получаем текст
    message_text = message.text or message.caption or ""
    
    # ВСЕ ПРОВЕРКИ В ОДНОМ МЕСТЕ
    if (contains_trigger_words(message_text) or 
        contains_dangerous_symbols(message_text) or 
        contains_emoji(message_text) or
        contains_phone_number(message_text)):
        
        await restrict_user(update, context, user.id)
        
        # Запускаем задачу для снятия блокировок
        if context.job_queue:
            jobs = context.job_queue.get_jobs_by_name(f"restriction_check_{message.chat.id}")
            if not jobs:
                context.job_queue.run_repeating(
                    check_restrictions,
                    interval=30,
                    first=10,
                    name=f"restriction_check_{message.chat.id}",
                    data=message.chat.id
                )

def main():
    """Запуск бота"""
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(MessageHandler(
        filters.TEXT | filters.CAPTION, 
        message_handler
    ))
    
    # Выводим список разрешенных групп при запуске
    print("✅ Бот запущен и работает в тихом режиме")
    print("📋 Разрешенные группы:")
    for chat in ALLOWED_CHATS:
        print(f"   - {chat}")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
