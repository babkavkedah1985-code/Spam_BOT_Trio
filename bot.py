import re
from datetime import datetime, timedelta, timezone
from typing import Set, Dict

from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.constants import ChatMemberStatus

# ⚠️ ТВОИ ДАННЫЕ
TOKEN = "1543341831:AAGjnQb9uLLLmfyF_9rR-hLG8_uvNiXHbgM"
ALLOWED_CHAT_ID = -3585377659

# Настройки фильтра
MUTE_DURATION: int = 1200  # 120 (2 минуты)

# Слова-триггеры
TRIGGER_WORDS: Set[str] = {
    "добавить", "дабавить", "как", "номер", "дабавте", "добавте", "добавьте", "дабавьте", "заработай", "бизнес", "пассивный доход",
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
    
    # Убираем пробелы и дефисы для проверки
    clean_text = re.sub(r'[\s\-\(\)]', '', text)
    
    # Проверяем разные паттерны
    patterns = [
        r'\+79\d{7,}',      # +79 и 7+ цифр
        r'89\d{7,}',         # 89 и 7+ цифр
        r'8-9\d{6,}',        # 8-9 и 6+ цифр
        r'8\s?9\s?\d{7,}',   # 8 9 1234567
        r'79\d{7,}',         # 79 и 7+ цифр (без +)
    ]
    
    for pattern in patterns:
        if re.search(pattern, clean_text):
            return True
    
    # Если есть последовательность из 7+ цифр
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
        
        # Удаляем сообщение
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

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основной обработчик"""
    message = update.message
    if not message or message.chat.id != ALLOWED_CHAT_ID:
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
        contains_phone_number(message_text)):  # 👈 Новая проверка телефонов
        
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
    
    print("✅ Бот запущен и работает в тихом режиме")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
