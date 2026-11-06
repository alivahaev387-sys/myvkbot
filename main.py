import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import json, random, sqlite3, time, requests, re

# ===== ТОКЕН =====
TOKEN = "vk1.a.GPEBmYPG-udUnhJYcT_4Zo-jEKzU7VFUYVzRDNwr1wVwo_fsBabigDoS-2BW9bvMbjdYBmf-QH6dwf-ZL4dMYkKMEEiviqU5GPmM5kaG4Xt535Hb1ApvImzJkk_cq-Q7ZxOQYVPbnULj0Fg6U0yDNSPgLwANkGKX348kTlENY6s99NOBeUO-e486DAX-0XtbAa3tmQdMYjF2GLxluGvHrhFHhvr5YCuDXfYxTgw5cYo"
ADMIN_ID = 200005093141
GROUP_ID = 242296265 

vk_session = vk_api.VkApi(token=TOKEN)
longpoll = VkBotLongPoll(vk_session, GROUP_ID)
vk = vk_session.get_api()

# Состояния
waiting_mode = {}
waiting_for_support = set() 
waiting_for_manual_report = set()
waiting_for_manual_reply = {} 
users_in_report = set() 
waiting_for_rating = set() 
active_reports = {}

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('super_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, warns INTEGER, ban_until INTEGER, uploads INTEGER)''')
    try:
        c.execute("ALTER TABLE users ADD COLUMN uploads INTEGER DEFAULT 0")
    except: pass
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = sqlite3.connect('super_bot.db')
    c = conn.cursor()
    c.execute("SELECT warns, ban_until, uploads FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (user_id, warns, ban_until, uploads) VALUES (?, 0, 0, 0)", (user_id,))
        conn.commit()
        row = (0, 0, 0)
    conn.close()
    return row

def add_upload(user_id):
    conn = sqlite3.connect('super_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET uploads = uploads + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def add_warn(user_id):
    conn = sqlite3.connect('super_bot.db')
    c = conn.cursor()
    c.execute("SELECT warns FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    current_warns = row[0] if row else 0
    
    new_warns = current_warns + 1
    c.execute("UPDATE users SET warns = ? WHERE user_id = ?", (new_warns, user_id))
    conn.commit()
    conn.close()
    return new_warns

init_db()

# --- СОКРАЩЕНИЕ ССЫЛОК ---
def shorten_link(url):
    try:
        res = vk.utils.getShortLink(url=url)
        if 'short_url' in res:
            return res['short_url'].replace('https://', '').replace('http://', '')
    except: pass
    return url.replace('https://', '').replace('http://', '')

# --- ФУНКЦИЯ ОТПРАВКИ ---
def send_msg(peer_id, message, keyboard=None):
    try:
        random_id = random.randint(1, 2**31 - 1)
        params = {
            'peer_id': peer_id,
            'message': message,
            'random_id': random_id
        }
        if keyboard:
            params['keyboard'] = keyboard
        return vk.messages.send(**params)
    except Exception as e:
        print(f"Ошибка при отправке: {e}")
        return None

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    return json.dumps({
        "one_time": False, 
        "buttons": [
            [{"action": {"type": "text", "label": "📸 Загрузить фото"}, "color": "positive"},
             {"action": {"type": "text", "label": "📸 Несколько фото"}, "color": "positive"}],
            [{"action": {"type": "text", "label": "🎬 Загрузка видео"}, "color": "primary"},
             {"action": {"type": "text", "label": "📊 Статистика"}, "color": "secondary"}],
            [{"action": {"type": "text", "label": "📖 Помощь"}, "color": "negative"}]
        ]
    }, ensure_ascii=False)

def get_help_kb():
    return json.dumps({
        "one_time": False, 
        "buttons": [
            [{"action": {"type": "text", "label": "📩 Связь с администрацией"}, "color": "primary"}],
            [{"action": {"type": "text", "label": "⬅️ Назад"}, "color": "secondary"}]
        ]
    }, ensure_ascii=False)

def get_choice_kb_player():
    return json.dumps({
        "one_time": False, 
        "buttons": [
            [{"action": {"type": "text", "label": "📋 Выбор по шаблонам"}, "color": "primary"},
             {"action": {"type": "text", "label": "✍️ Свой вопрос"}, "color": "positive"}],
            [{"action": {"type": "text", "label": "⬅️ Назад"}, "color": "secondary"}]
        ]
    }, ensure_ascii=False)

def get_templates_kb():
    return json.dumps({
        "one_time": False,
        "buttons": [
            [{"action": {"type": "text", "label": "❌ Фото не загрузилось"}, "color": "secondary"},
             {"action": {"type": "text", "label": "❌ Ссылка не открывается"}, "color": "secondary"}],
            [{"action": {"type": "text", "label": "❌ Видео не скачивается"}, "color": "secondary"},
             {"action": {"type": "text", "label": "❌ На iPhone не сохраняется"}, "color": "secondary"}],
            [{"action": {"type": "text", "label": "⬅️ Назад"}, "color": "secondary"}]
        ]
    }, ensure_ascii=False)

def get_rating_kb(target_user_id):
    return json.dumps({
        "inline": True,
        "buttons": [
            [{"action": {"type": "callback", "label": "⭐ Оценить работу", "payload": json.dumps({"cmd": "rate_report", "target_id": target_user_id})}, "color": "positive"},
             {"action": {"type": "callback", "label": "❌ Закрыть вопрос", "payload": json.dumps({"cmd": "close_report", "target_id": target_user_id})}, "color": "negative"}]
        ]
    }, ensure_ascii=False)

def get_admin_report_kb(report_id, target_user_id):
    return json.dumps({
        "inline": True,
        "buttons": [
            [{"action": {"type": "callback", "label": "✍️ Ответить", "payload": json.dumps({"cmd": "admin_reply", "report_id": report_id, "target_id": target_user_id})}, "color": "positive"},
             {"action": {"type": "callback", "label": "🚫 Спам", "payload": json.dumps({"cmd": "admin_spam", "report_id": report_id, "target_id": target_user_id})}, "color": "negative"}]
        ]
    }, ensure_ascii=False)

def get_ban_time_kb(target_user, report_id):
    return json.dumps({
        "inline": True,
        "buttons": [
            [{"action": {"type": "callback", "label": "1 Мин", "payload": json.dumps({"cmd": "set_ban", "target_id": target_user, "report_id": report_id, "time": 60})}, "color": "secondary"},
             {"action": {"type": "callback", "label": "1 Час", "payload": json.dumps({"cmd": "set_ban", "target_id": target_user, "report_id": report_id, "time": 3600})}, "color": "primary"}],
            [{"action": {"type": "callback", "label": "1 День", "payload": json.dumps({"cmd": "set_ban", "target_id": target_user, "report_id": report_id, "time": 86400})}, "color": "primary"},
             {"action": {"type": "callback", "label": "7 Дней", "payload": json.dumps({"cmd": "set_ban", "target_id": target_user, "report_id": report_id, "time": 604800})}, "color": "negative"}],
            [{"action": {"type": "callback", "label": "❌ Отмена (Разбан)", "payload": json.dumps({"cmd": "cancel_ban", "target_id": target_user, "report_id": report_id})}, "color": "secondary"}]
        ]
    }, ensure_ascii=False)

print("БОТ ЗАПУЩЕН (Умная система оценок)!")

try:
    for event in longpoll.listen():
        # --- ОБРАБОТКА НАЖАТИЙ ИНЛАЙН-КНОПОК ---
        if event.type == VkBotEventType.MESSAGE_EVENT:
            payload = event.object.payload
            user_id = event.object.user_id
            peer_id = event.object.peer_id
            event_id = event.object.event_id
            
            target_id = payload.get("target_id")
            if payload.get("cmd") in ["rate_report", "close_report"]:
                if target_id and str(user_id) != str(target_id):
                    vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "❌ Эта кнопка не для вас!"}))
                    continue

            # Обработка кнопок Админа в репорте
            if user_id == ADMIN_ID:
                report_id = payload.get("report_id")
                target_user = payload.get("target_id")
                
                if payload.get("cmd") == "admin_reply":
                    if report_id not in active_reports:
                        vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "❌ Этот репорт уже закрыт!"}))
                        continue
                        
                    waiting_for_manual_reply[ADMIN_ID] = {"target_user": target_user, "report_id": report_id}
                    send_msg(ADMIN_ID, f"✍️ **Репорт #{report_id}**\nНапиши текст ответа для [id{target_user}|Игрока]:", keyboard=get_main_kb())
                    vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Напиши ответ в чат"}))
                    continue
                
                elif payload.get("cmd") == "admin_spam":
                    if report_id not in active_reports:
                        vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Этот репорт уже обработан!"}))
                        continue
                        
                    new_warns = add_warn(target_user)
                    
                    if new_warns >= 3:
                        if ADMIN_ID in waiting_for_manual_reply:
                            if waiting_for_manual_reply[ADMIN_ID]["report_id"] == report_id:
                                del waiting_for_manual_reply[ADMIN_ID]

                        ban_menu_text = f"⚠️ Пользователь [id{target_user}|Игрок] достиг лимита (3/3)!\n\nВыберите срок ЧС (бана):"
                        send_msg(ADMIN_ID, ban_menu_text, keyboard=get_ban_time_kb(target_user, report_id))
                        
                        del active_reports[report_id]
                        users_in_report.discard(target_user)
                        try:
                            vk.messages.delete(message_ids=event.object.conversation_message_id, delete_for_all=1)
                        except: pass
                        
                        vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Выберите срок бана"}))
                        continue
                    
                    else:
                        admin_msg = f"⚠️ Пользователь [id{target_user}|Игрок] получил предупреждение ({new_warns}/3). Репорт #{report_id} удален."
                        send_msg(ADMIN_ID, admin_msg)
                        
                        spam_text = (f"🚫 **ВАШ РЕПОРТ ОТКЛОНЕН!**\n\n"
                                     f"Причина: СПАМ.\n"
                                     f"Ваш счет: {new_warns}/3.\n"
                                     f"⚠️ **При 3-х предупреждениях вы будете автоматически отправлены в ЧС!**\n\n"
                                     f"Кто выдал: [id{ADMIN_ID}|Администратор].\n"
                                     f"Если вы пожалели о ситуации, обратитесь через ЛС: [id{ADMIN_ID}|Владелец]")
                        send_msg(target_user, spam_text)
                        
                        del active_reports[report_id]
                        users_in_report.discard(target_user)
                        try:
                            vk.messages.delete(message_ids=event.object.conversation_message_id, delete_for_all=1)
                        except: pass
                        
                        vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Спам обработан"}))
                        continue

                elif payload.get("cmd") == "set_ban":
                    ban_seconds = payload.get("time")
                    conn = sqlite3.connect('super_bot.db')
                    c = conn.cursor()
                    ban_until = int(time.time()) + int(ban_seconds)
                    c.execute("UPDATE users SET warns = 0, ban_until = ? WHERE user_id = ?", (ban_until, target_user))
                    conn.commit()
                    conn.close()

                    ban_text = (f"⛔ **ВЫ БЫЛИ АВТОМАТИЧЕСКИ ЗАБЛОКИРОВАНЫ!**\n\n"
                                f"Причина: Систематический спам (3/3).\n"
                                f"Кто выдал: [id{ADMIN_ID}|Администратор].\n\n"
                                f"Если вы пожалели о ситуации, обратитесь в ЛС: [id{ADMIN_ID}|Владелец]")
                    send_msg(target_user, ban_text)
                    send_msg(ADMIN_ID, f"⛔ Пользователь [id{target_user}|Игрок] отправлен в ЧС. Репорт закрыт.", keyboard=get_main_kb())
                    vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Бан выдан"}))
                    continue

                elif payload.get("cmd") == "cancel_ban":
                    send_msg(ADMIN_ID, f"✅ Вы отменили бан для [id{target_user}|Игрока].", keyboard=get_main_kb())
                    vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Бан отменен"}))
                    continue

            # Логика оценки
            if payload.get("cmd") == "rate_report":
                if user_id in users_in_report:
                    waiting_for_rating.add(user_id)
                    send_msg(peer_id, "⭐ Пожалуйста, напишите оценку от 1 до 10 одним числом (например: 5).", keyboard=get_main_kb())
                    vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Ожидаю оценку..."}))
                else:
                    vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Репорт уже закрыт!"}))
            
            elif payload.get("cmd") == "close_report":
                if user_id in users_in_report:
                    users_in_report.discard(user_id)
                    send_msg(peer_id, "✅ Спасибо за обращение! Ваш вопрос закрыт.", keyboard=get_main_kb())
                    vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Вопрос закрыт"}))
                else:
                    vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Репорт уже закрыт!"}))
            continue

        # --- ОБРАБОТКА СООБЩЕНИЙ ---
        if event.type == VkBotEventType.MESSAGE_NEW and event.object.message['peer_id']:
            msg = event.object.message
            peer_id = msg['peer_id']
            user_id = msg['from_id'] 
            
            text = msg.get('text', '').strip()
            text_lower = text.lower().replace("@club242296265", "").strip()

            is_ls = (peer_id == user_id)
            if not is_ls:
                continue 

            # =========================================================
            # 👑 КОМАНДЫ АДМИНИСТРАТОРА (Снятие ЧС)
            # =========================================================
            if user_id == ADMIN_ID:
                if "снять чс" in text_lower or "разбан" in text_lower:
                    target_user = None
                    # 1. Проверяем, есть ли ответ на сообщение (Reply)
                    if 'reply_message' in msg:
                        target_user = msg['reply_message']['from_id']
                    else:
                        # 2. Ищем ID в тексте (например, id123456 или просто цифры)
                        match = re.search(r'id(\d+)', text_lower)
                        if match:
                            target_user = int(match.group(1))
                        else:
                            match = re.search(r'\d{5,}', text)
                            if match:
                                target_user = int(match.group(0))
                    
                    if target_user:
                        conn = sqlite3.connect('super_bot.db')
                        c = conn.cursor()
                        c.execute("UPDATE users SET warns = 0, ban_until = 0 WHERE user_id = ?", (target_user,))
                        conn.commit()
                        conn.close()
                        
                        send_msg(ADMIN_ID, f"✅ С пользователя [id{target_user}|Игрок] успешно снят ЧС и обнулены варны!", keyboard=get_main_kb())
                        send_msg(target_user, "✅ **Администратор снял с вас ЧС и обнулил предупреждения!**\n\nБот снова готов с вами работать.")
                    else:
                        send_msg(ADMIN_ID, "❌ Напиши так: `Снять ЧС @id123456` (или ответь на сообщение игрока).", keyboard=get_main_kb())
                    continue
            # =========================================================

            # =========================================================
            # 🛑 ПРОВЕРКА НА ЧС
            # =========================================================
            warns, ban_until, uploads = get_user_data(user_id)
            current_time = int(time.time())

            if ban_until > current_time:
                if peer_id in waiting_mode: del waiting_mode[peer_id]
                waiting_for_support.discard(user_id)
                waiting_for_manual_report.discard(user_id)
                waiting_for_rating.discard(user_id)
                
                seconds_left = ban_until - current_time
                if seconds_left < 60:
                    time_left = f"{seconds_left} сек."
                elif seconds_left < 3600:
                    time_left = f"{seconds_left // 60} мин."
                elif seconds_left < 86400:
                    time_left = f"{seconds_left // 3600} ч."
                else:
                    time_left = f"{seconds_left // 86400} дн."

                ban_text = (f"⛔ **ВЫ НАХОДИТЕСЬ В ЧС (ЧЕРНОМ СПИСКЕ)!**\n\n"
                            f"Причина: Спам / Нарушение правил.\n"
                            f"Кто выдал: [id{ADMIN_ID}|Администратор].\n"
                            f"Осталось: {time_left}\n\n"
                            f"Бот полностью игнорирует ваши команды.\n"
                            f"Если вы пожалели о ситуации, напишите напрямую в ЛС: [id{ADMIN_ID}|Владелец]")
                send_msg(peer_id, ban_text)
                continue 
            # =========================================================

            # КОМАНДА ПИНГ
            if text_lower in ["пинг", "ping", "/ping", "/пинг", "!ping", "!пинг"]:
                ping_ms = int((time.time() - msg.get('date', time.time())) * 1000)
                if ping_ms < 0: ping_ms = 0
                
                ping_text = (
                    f"🏓 Понг!\n\n"
                    f"⚡ Скорость соединения: {ping_ms} мс\n"
                    f"📊 Статус сети: 🟢 Отлично"
                )
                send_msg(peer_id, ping_text, keyboard=None)
                continue 

            if text_lower == "начать" or text_lower == "start":
                send_msg(peer_id, "Привет! Выбирай действие на кнопках внизу 👇", keyboard=get_main_kb())
                continue

            # --- ОТВЕТ АДМИНА НА РЕПОРТ ---
            if user_id == ADMIN_ID and ADMIN_ID in waiting_for_manual_reply:
                reply_data = waiting_for_manual_reply[ADMIN_ID]
                target_user_id = reply_data["target_user"]
                report_id = reply_data["report_id"]
                
                if report_id not in active_reports:
                    send_msg(ADMIN_ID, f"❌ Ошибка: Репорт #{report_id} уже закрыт. Ответ не отправлен.", keyboard=get_main_kb())
                    del waiting_for_manual_reply[ADMIN_ID]
                    continue

                send_msg(target_user_id, f"📩 **Вам ответил администратор** [id{ADMIN_ID}|Владелец]:\n\n{text}", keyboard=get_rating_kb(target_user_id))
                send_msg(ADMIN_ID, f"✅ Ответ доставлен [id{target_user_id}|Игроку]. Репорт #{report_id} закрыт.", keyboard=get_main_kb())
                
                del active_reports[report_id]
                users_in_report.discard(target_user_id)
                del waiting_for_manual_reply[ADMIN_ID]
                continue

            # Ожидание оценки
            if user_id in waiting_for_rating:
                try:
                    rating = int(text)
                    if 1 <= rating <= 10:
                        admin_msg = (f"⭐ **Новый отзыв!**\n\n"
                                     f"👤 Пользователь: [id{user_id}|Игрок]\n"
                                     f"🌟 Оценка: {rating}/10\n\n"
                                     f"Репорт успешно закрыт.")
                        send_msg(ADMIN_ID, admin_msg)
                        
                        if 1 <= rating <= 3:
                            user_msg = (f"😔 **Спасибо за отзыв (Оценка: {rating}/10).**\n\n"
                                        f"Нам очень жаль, что мы не смогли решить вашу проблему идеально.\n\n🔒 *Репорт закрыт.*")
                        elif 4 <= rating <= 7:
                            user_msg = (f"🙂 **Спасибо за отзыв (Оценка: {rating}/10).**\n\n"
                                        f"Мы рады, что смогли вам помочь!\n\n🔒 *Репорт закрыт.*")
                        else: 
                            user_msg = (f"🤩 **Огромное спасибо! (Оценка: {rating}/10)**\n\n"
                                        f"Мы очень рады, что вам всё понравилось!\n\n🔒 *Репорт закрыт.*")
                        
                        send_msg(peer_id, user_msg, keyboard=get_main_kb())
                        waiting_for_rating.remove(user_id)
                        users_in_report.discard(user_id)
                    else:
                        send_msg(peer_id, "❌ Оценка должна быть от 1 до 10.", keyboard=get_main_kb())
                except ValueError:
                    send_msg(peer_id, "❌ Пожалуйста, введи число.", keyboard=get_main_kb())
                continue

            # Игрок пишет свой вопрос (Репорт)
            if user_id in waiting_for_manual_report:
                if text_lower == "⬅️ назад" or text_lower == "назад":
                    waiting_for_manual_report.remove(user_id)
                    send_msg(peer_id, "Вы вернулись в главное меню.", keyboard=get_main_kb())
                    continue
                else:
                    report_id = random.randint(1000, 9999)
                    active_reports[report_id] = user_id 
                    
                    support_text = f"🆘 **Репорт #{report_id}**\n👤 От: [id{user_id}|Игрок]\n\n{text}"
                    send_msg(ADMIN_ID, support_text, keyboard=get_admin_report_kb(report_id, user_id))
                    
                    users_in_report.add(user_id) 
                    send_msg(user_id, "✅ Твой репорт отправлен! Ожидай ответа.", keyboard=get_main_kb())
                    waiting_for_manual_report.remove(user_id)
                    continue

            # Игрок выбирает шаблон (Репорт)
            if user_id in waiting_for_support:
                if text_lower == "⬅️ назад" or text_lower == "назад":
                    waiting_for_support.remove(user_id)
                    send_msg(peer_id, "Вы вернулись в главное меню.", keyboard=get_main_kb())
                    continue
                
                report_id = random.randint(1000, 9999)
                active_reports[report_id] = user_id
                
                support_text = f"🆘 **Репорт #{report_id}**\n👤 От: [id{user_id}|Игрок]\n\n{text}"
                send_msg(ADMIN_ID, support_text, keyboard=get_admin_report_kb(report_id, user_id))
                
                users_in_report.add(user_id) 
                send_msg(user_id, "✅ Репорт отправлен! Ожидай.", keyboard=get_main_kb())
                waiting_for_support.remove(user_id)
                continue

            # Статистика
            if text_lower == "стата" and user_id == ADMIN_ID:
                conn = sqlite3.connect('super_bot.db')
                c = conn.cursor()
                c.execute("SELECT user_id, warns, ban_until, uploads FROM users")
                all_users = c.fetchall()
                conn.close()
                stats_text = "📊 **Статистика:**\n\n"
                for u_id, w, b_until, ups in all_users:
                    if w > 0 or b_until > time.time() or ups > 0:
                        ban_status = "Нет" if b_until == 0 or b_until < time.time() else "ДА (ЧС)"
                        stats_text += f"👤 ID: {u_id}\n⚠️ Варны: {w}/3\n📤 Загрузок: {ups}\n⛔ ЧС: {ban_status}\n\n"
                send_msg(peer_id, stats_text)
                continue

            # Обработка фото/видео
            if peer_id in waiting_mode:
                try:
                    msg_info = vk.messages.getById(message_ids=msg['id'])
                    items = msg_info.get('items', [])
                    if items:
                        attachments = items[0].get('attachments', [])
                        links = []
                        is_video, is_photo = False, False
                        
                        for attach in attachments:
                            if attach.get('type') == 'photo':
                                is_photo = True
                                sizes = attach['photo'].get('sizes', [])
                                if sizes: links.append(sizes[-1]['url'])
                            elif attach.get('type') == 'video':
                                is_video = True
                                v_id = attach['video']['id']
                                o_id = attach['video']['owner_id']
                                links.append(f"https://vk.com/video{o_id}_{v_id}")
                        
                        mode = waiting_mode[peer_id]
                        
                        if mode == 'video':
                            if is_photo and not is_video:
                                send_msg(peer_id, "❌ **Это не видео!**", keyboard=get_main_kb())
                            elif is_video and links:
                                add_upload(user_id)
                                short_link = shorten_link(links[0])
                                send_msg(peer_id, f"🎬 **Ссылка:**\n{short_link}", keyboard=get_main_kb())
                        elif mode == 'one':
                            if is_photo and links:
                                add_upload(user_id)
                                short_link = shorten_link(links[0])
                                final_text = (f"🌿 **Твоя фотография загружена!**\n\n"
                                              f"🔗 Ссылка: {short_link}\n\n"
                                              f"💾 **Как сохранить:**\n1. Скопируй ссылку.\n2. Вставь её в браузер (Safari).\n3. Зажми картинку и выбери «Сохранить».")
                                send_msg(peer_id, final_text, keyboard=get_main_kb())
                            else:
                                send_msg(peer_id, "❌ Отправь фото!", keyboard=get_main_kb())
                        elif mode == 'multi':
                            if is_photo and links:
                                add_upload(user_id)
                                final_text = "🌿 **Твои фотографии загружены!**\n\n"
                                for i, link in enumerate(links, 1):
                                    short_link = shorten_link(link)
                                    final_text += f"🔗 Фото {i}: {short_link}\n\n"
                                final_text += "💾 **Как сохранить:**\n1. Скопируй ссылку.\n2. Вставь её в браузер (Safari).\n3. Зажми картинку и выбери «Сохранить»."
                                send_msg(peer_id, final_text, keyboard=get_main_kb())
                            else:
                                send_msg(peer_id, "❌ Отправь фото!", keyboard=get_main_kb())
                except Exception as e: print(e)
                if peer_id in waiting_mode: del waiting_mode[peer_id]
                continue

            # Меню
            if "видео" in text_lower:
                waiting_mode[peer_id] = 'video'
                send_msg(peer_id, "🎬 **Отправь мне видео!**", keyboard=get_main_kb())
            elif "несколько" in text_lower:
                waiting_mode[peer_id] = 'multi'
                send_msg(peer_id, "📸 **Отправь мне несколько фото!**", keyboard=get_main_kb())
            elif "загрузить фото" in text_lower or "создать ссылку" in text_lower:
                waiting_mode[peer_id] = 'one'
                send_msg(peer_id, "📸 **Отправь мне фотографию, и я сделаю из неё прямую ссылку!**", keyboard=get_main_kb())
            elif "статистика" in text_lower:
                send_msg(peer_id, f"📊 **Загружено:** {uploads}", keyboard=get_main_kb())
            
            elif "помощь" in text_lower:
                help_text = "📖 **Помощь по боту**\n\n1. Жми «Загрузить фото».\n2. Отправь картинку.\n3. Получи прямую ссылку.\n\nПо всем вопросам пиши в поддержку 👇"
                send_msg(peer_id, help_text, keyboard=get_help_kb())
                
            elif "связь с администрацией" in text_lower:
                if user_id in users_in_report:
                    send_msg(peer_id, "⏳ **У вас уже есть активный репорт!**\n\nПожалуйста, дождитесь ответа.", keyboard=get_main_kb())
                else:
                    send_msg(peer_id, "📩 **Выберите способ обращения в поддержку:**", keyboard=get_choice_kb_player())
                    
            elif "выбор по шаблонам" in text_lower:
                send_msg(peer_id, "📩 **Выберите тему обращения:**", keyboard=get_templates_kb())
                waiting_for_support.add(user_id)
                
            elif "свой вопрос" in text_lower:
                send_msg(peer_id, "✍️ **Напишите вашу проблему одним сообщением (или нажмите 'Назад'):**", keyboard=get_main_kb())
                waiting_for_manual_report.add(user_id)
                
            elif "назад" in text_lower:
                send_msg(peer_id, "Выбирай действие на кнопках внизу 👇", keyboard=get_main_kb())
                
            else:
                send_msg(peer_id, "Выбери действие на кнопках 👇", keyboard=get_main_kb())

except Exception as e:
    print("\n❌ КРИТИЧЕСКАЯ ОШИБКА:", e)
