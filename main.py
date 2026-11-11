import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import json, random, sqlite3, time, requests, re
import threading

# ===== ТОКЕН И НАСТРОЙКИ (HOSTBOT) =====
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
waiting_for_rating = {}  
waiting_for_feedback = {} 
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

# --- ЗАГРУЗКА ФОТО НА FASTPIC (БЕЗ СОКРАЩЕНИЯ) ---
def upload_photo_to_hosting(image_url):
    try:
        img = requests.get(image_url, timeout=15).content
        
        files = {'upload[]': ('photo.jpg', img, 'image/jpeg')}
        data = {
            'uploading': '1',
            'submit': 'Загрузить'
        }
        
        r = requests.post(
            "https://fastpic.org/upload",
            files=files,
            data=data,
            timeout=30,
            allow_redirects=True
        )
        
        if r.status_code == 200:
            # Ищем прямую ссылку на картинку
            match = re.search(r'https://i\d+\.fastpic\.org/big/\d{4}/\d{4}/\w+/\w+\.\w+', r.text)
            if match:
                return match.group(0)
                
            match = re.search(r'https://i\d+\.fastpic\.org/.+?\.(jpg|png|jpeg|gif)', r.text)
            if match:
                return match.group(0)
                
    except Exception as e:
        print(f"Ошибка загрузки на FastPic: {e}")
        
    # Резерв: Catbox
    try:
        img = requests.get(image_url, timeout=15).content
        r = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": ("photo.jpg", img)},
            timeout=30
        )
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return r.text.strip()
    except Exception as e:
        print(f"Ошибка загрузки на Catbox: {e}")
        
    return None

# --- СОКРАЩЕНИЕ ССЫЛОК (ТОЛЬКО ДЛЯ ВИДЕО) ---
def shorten_link(url):
    try:
        res = vk.utils.getShortLink(url=url)
        if 'short_url' in res:
            return res['short_url']
    except Exception as e:
        print(f"ВК не смог сократить: {e}")
    return url

# --- ФУНКЦИЯ ОТПРАВКИ ---
def send_msg(peer_id, message, keyboard=None, reply_to=None):
    try:
        params = {
            'peer_id': peer_id,
            'message': message,
            'random_id': random.randint(1, 2**31 - 1)
        }
        if keyboard: params['keyboard'] = keyboard
        if reply_to: params['reply_to'] = reply_to
        return vk.messages.send(**params)
    except Exception as e:
        print(f"Ошибка отправки: {e}")
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

def get_neg_feedback_kb(report_id):
    return json.dumps({
        "inline": True,
        "buttons": [
            [{"action": {"type": "callback", "label": "⏳ Давно без ответа", "payload": json.dumps({"cmd": "feedback", "type": "neg", "reason": "Давно без ответа", "report_id": report_id})}, "color": "secondary"},
             {"action": {"type": "callback", "label": "🚫 Не помог", "payload": json.dumps({"cmd": "feedback", "type": "neg", "reason": "Не помог", "report_id": report_id})}, "color": "secondary"}],
            [{"action": {"type": "callback", "label": "❓ Не понял ответ", "payload": json.dumps({"cmd": "feedback", "type": "neg", "reason": "Не понял ответ", "report_id": report_id})}, "color": "secondary"},
             {"action": {"type": "callback", "label": "😡 Грубость", "payload": json.dumps({"cmd": "feedback", "type": "neg", "reason": "Грубость", "report_id": report_id})}, "color": "negative"}],
            [{"action": {"type": "callback", "label": "❌ Закрыть репорт", "payload": json.dumps({"cmd": "close_feedback_report", "report_id": report_id})}, "color": "negative"}]
        ]
    }, ensure_ascii=False)

def get_pos_feedback_kb(report_id):
    return json.dumps({
        "inline": True,
        "buttons": [
            [{"action": {"type": "callback", "label": "⚡ Быстрый ответ", "payload": json.dumps({"cmd": "feedback", "type": "pos", "reason": "Быстрый ответ", "report_id": report_id})}, "color": "positive"},
             {"action": {"type": "callback", "label": "💡 Понятно объяснили", "payload": json.dumps({"cmd": "feedback", "type": "pos", "reason": "Понятно объяснили", "report_id": report_id})}, "color": "positive"}],
            [{"action": {"type": "callback", "label": "🛠 Решили проблему", "payload": json.dumps({"cmd": "feedback", "type": "pos", "reason": "Решили проблему", "report_id": report_id})}, "color": "primary"},
             {"action": {"type": "callback", "label": "🤝 Вежливый админ", "payload": json.dumps({"cmd": "feedback", "type": "pos", "reason": "Вежливый админ", "report_id": report_id})}, "color": "primary"}],
            [{"action": {"type": "callback", "label": "🔗 Удобный бот", "payload": json.dumps({"cmd": "feedback", "type": "pos", "reason": "Удобный бот", "report_id": report_id})}, "color": "secondary"},
             {"action": {"type": "callback", "label": "🔥 Всё супер!", "payload": json.dumps({"cmd": "feedback", "type": "pos", "reason": "Всё супер!", "report_id": report_id})}, "color": "positive"}],
            [{"action": {"type": "callback", "label": "❌ Закрыть репорт", "payload": json.dumps({"cmd": "close_feedback_report", "report_id": report_id})}, "color": "negative"}]
        ]
    }, ensure_ascii=False)

def get_rating_kb(target_user_id, report_id):
    return json.dumps({
        "inline": True,
        "buttons": [
            [{"action": {"type": "callback", "label": "⭐ Оценить работу", "payload": json.dumps({"cmd": "rate_report", "target_id": target_user_id, "report_id": report_id})}, "color": "positive"},
             {"action": {"type": "callback", "label": "❌ Закрыть вопрос", "payload": json.dumps({"cmd": "close_report", "target_id": target_user_id, "report_id": report_id})}, "color": "negative"}]
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

# --- ФОНОВЫЙ ПРОЦЕСС ---
def auto_unban_checker():
    while True:
        try:
            conn = sqlite3.connect('super_bot.db')
            c = conn.cursor()
            now = int(time.time())
            c.execute("SELECT user_id FROM users WHERE ban_until > 0 AND ban_until <= ?", (now,))
            expired_users = c.fetchall()

            for (user_id,) in expired_users:
                c.execute("UPDATE users SET ban_until = 0 WHERE user_id = ?", (user_id,))
                conn.commit()
                unban_text = "🎉 ПРИВЕТСТВУЕМ СНОВА! 🎉\n\nС вас был автоматически снят ЧС.\n⏳ Время наказания истекло."
                send_msg(user_id, unban_text, keyboard=get_main_kb())
            conn.close()
        except Exception as e:
            pass
        time.sleep(5)

threading.Thread(target=auto_unban_checker, daemon=True).start()

print("HOSTBOT ЗАПУЩЕН!")

while True:
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

                if payload.get("cmd") == "feedback":
                    report_id = payload.get("report_id")
                    if user_id not in waiting_for_feedback or waiting_for_feedback[user_id] != report_id:
                        vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "❌ Вы уже оставили отзыв!"}))
                        continue

                    f_type = payload.get("type")
                    reason = payload.get("reason")
                    
                    if report_id in active_reports: del active_reports[report_id]
                    users_in_report.discard(user_id)
                    if user_id in waiting_for_feedback: del waiting_for_feedback[user_id]
                    
                    emoji = "⚠️" if f_type == "neg" else "✨"
                    f_type_text = "Недоволен" if f_type == "neg" else "Доволен"
                    
                    send_msg(ADMIN_ID, f"{emoji} Отзыв по репорту #{report_id}!\n👤 Игрок: [id{user_id}|Игрок]\n📊 Оценка: {f_type_text}\n💬 Причина: {reason}")
                    send_msg(peer_id, f"🙏 Спасибо за ваш ответ!\nМы зафиксировали: {reason}.\nРепорт закрыт.", keyboard=get_main_kb())
                    vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Спасибо! Репорт закрыт."}))
                    continue

                if payload.get("cmd") == "close_feedback_report":
                    report_id = payload.get("report_id")
                    if user_id not in waiting_for_feedback or waiting_for_feedback[user_id] != report_id:
                        vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "❌ Репорт уже закрыт!"}))
                        continue

                    if report_id in active_reports: del active_reports[report_id]
                    users_in_report.discard(user_id)
                    if user_id in waiting_for_feedback: del waiting_for_feedback[user_id]
                    
                    send_msg(peer_id, "✅ Репорт успешно закрыт.", keyboard=get_main_kb())
                    send_msg(ADMIN_ID, f"🔒 Игрок [id{user_id}|Игрок] закрыл репорт #{report_id} без указания причины.")
                    vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Репорт закрыт"}))
                    continue

                if user_id == ADMIN_ID:
                    report_id = payload.get("report_id")
                    target_user = payload.get("target_id")
                    
                    if payload.get("cmd") == "admin_reply":
                        if report_id not in active_reports:
                            vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "❌ Этот репорт уже закрыт!"}))
                            continue
                        waiting_for_manual_reply[ADMIN_ID] = {"target_user": target_user, "report_id": report_id}
                        send_msg(ADMIN_ID, f"✍️ Репорт #{report_id}\nНапиши текст ответа для [id{target_user}|Игрока]:", keyboard=get_main_kb())
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
                            send_msg(ADMIN_ID, f"⚠️ Пользователь [id{target_user}|Игрок] достиг лимита (3/3)!\nВыберите срок ЧС:", keyboard=get_ban_time_kb(target_user, report_id))
                            del active_reports[report_id]
                            users_in_report.discard(target_user)
                            try: vk.messages.delete(message_ids=event.object.conversation_message_id, delete_for_all=1)
                            except: pass
                            vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Выберите срок бана"}))
                            continue
                        else:
                            send_msg(ADMIN_ID, f"⚠️ Пользователь [id{target_user}|Игрок] получил предупреждение ({new_warns}/3). Репорт #{report_id} удален.")
                            spam_text = f"🚫 ВАШ РЕПОРТ ОТКЛОНЕН!\nПричина: СПАМ.\nВаш счет: {new_warns}/3."
                            send_msg(target_user, spam_text)
                            del active_reports[report_id]
                            users_in_report.discard(target_user)
                            try: vk.messages.delete(message_ids=event.object.conversation_message_id, delete_for_all=1)
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
                        send_msg(target_user, "⛔ ВЫ БЫЛИ АВТОМАТИЧЕСКИ ЗАБЛОКИРОВАНЫ!\nПричина: Систематический спам (3/3).")
                        send_msg(ADMIN_ID, f"⛔ Пользователь [id{target_user}|Игрок] отправлен в ЧС.", keyboard=get_main_kb())
                        vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Бан выдан"}))
                        continue

                    elif payload.get("cmd") == "cancel_ban":
                        send_msg(ADMIN_ID, f"✅ Вы отменили бан для [id{target_user}|Игрока].", keyboard=get_main_kb())
                        vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Бан отменен"}))
                        continue

                if payload.get("cmd") == "rate_report":
                    if user_id in users_in_report:
                        report_id = payload.get("report_id")
                        waiting_for_rating[user_id] = report_id  
                        send_msg(peer_id, "⭐ Оцените работу администратора!\nНапишите оценку от 1 до 10 одним числом:", keyboard=get_main_kb())
                        vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Ожидаю оценку..."}))
                    else:
                        vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Этот репорт уже закрыт!"}))
                
                elif payload.get("cmd") == "close_report":
                    if user_id in users_in_report:
                        report_id = payload.get("report_id")
                        if report_id in active_reports: del active_reports[report_id]
                        users_in_report.discard(user_id)
                        if user_id in waiting_for_rating: del waiting_for_rating[user_id]
                        send_msg(peer_id, "✅ Ваш вопрос успешно закрыт!", keyboard=get_main_kb())
                        send_msg(ADMIN_ID, f"🔒 Игрок [id{user_id}|Игрок] самостоятельно закрыл репорт #{report_id}.")
                        vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Вопрос закрыт"}))
                    else:
                        vk.messages.sendMessageEventAnswer(event_id=event_id, user_id=user_id, peer_id=peer_id, event_data=json.dumps({"type": "show_snackbar", "text": "Этот репорт уже закрыт!"}))
                continue

            # --- ОБРАБОТКА СООБЩЕНИЙ ---
            if event.type == VkBotEventType.MESSAGE_NEW and event.object.message['peer_id']:
                msg = event.object.message
                peer_id = msg['peer_id']
                user_id = msg['from_id'] 
                msg_id = msg.get('id') 
                
                text = msg.get('text', '').strip()
                text_lower = text.lower().replace("@club242296265", "").strip()

                # ПИНГ РАБОТАЕТ ВЕЗДЕ
                if text_lower in ["пинг", "ping", "/ping", "/пинг", "!ping", "!пинг"]:
                    ping_ms = int((time.time() - msg.get('date', time.time())) * 1000)
                    if ping_ms < 0: ping_ms = 0
                    send_msg(peer_id, f"🏓 Понг!\n⚡ Скорость соединения: {ping_ms} мс\n📊 Статус сети: 🟢 Отлично", reply_to=msg_id)
                    continue 

                # Дальше только ЛС
                is_ls = (peer_id == user_id)
                if not is_ls: continue 

                # КОМАНДЫ АДМИНА
                if user_id == ADMIN_ID:
                    if "снять чс" in text_lower or "разбан" in text_lower:
                        target_user = None
                        if 'reply_message' in msg:
                            target_user = msg['reply_message']['from_id']
                        else:
                            match = re.search(r'id(\d+)', text_lower)
                            if match: target_user = int(match.group(1))
                        
                        if target_user:
                            conn = sqlite3.connect('super_bot.db')
                            c = conn.cursor()
                            c.execute("UPDATE users SET warns = 0, ban_until = 0 WHERE user_id = ?", (target_user,))
                            conn.commit()
                            conn.close()
                            send_msg(ADMIN_ID, f"✅ С пользователя [id{target_user}|Игрок] успешно снят ЧС!", keyboard=get_main_kb(), reply_to=msg_id)
                            send_msg(target_user, "✅ Администратор снял с вас ЧС!")
                        else:
                            send_msg(ADMIN_ID, "❌ Ответь на сообщение игрока.", keyboard=get_main_kb(), reply_to=msg_id)
                        continue

                # ПРОВЕРКА НА ЧС
                warns, ban_until, uploads = get_user_data(user_id)
                current_time = int(time.time())

                if ban_until > current_time:
                    if peer_id in waiting_mode: del waiting_mode[peer_id]
                    waiting_for_support.discard(user_id)
                    waiting_for_manual_report.discard(user_id)
                    if user_id in waiting_for_rating: del waiting_for_rating[user_id]
                    if user_id in waiting_for_feedback: del waiting_for_feedback[user_id]
                    
                    seconds_left = ban_until - current_time
                    time_left = f"{seconds_left} сек." if seconds_left < 60 else f"{seconds_left // 60} мин." if seconds_left < 3600 else f"{seconds_left // 3600} ч." if seconds_left < 86400 else f"{seconds_left // 86400} дн."

                    send_msg(peer_id, f"⛔ ВЫ НАХОДИТЕСЬ В ЧС!\nОсталось: {time_left}", reply_to=msg_id)
                    continue 

                # ФОТО
                if peer_id in waiting_mode:
                    mode = waiting_mode[peer_id]
                    try:
                        full_msg = vk.messages.getById(message_ids=str(msg['id']))['items'][0]
                        attachments = full_msg.get('attachments', [])
                    except Exception:
                        attachments = msg.get('attachments', [])
                    
                    if not attachments:
                        del waiting_mode[peer_id]
                    else:
                        links = []
                        is_video, is_photo = False, False
                        
                        for attach in attachments:
                            att_type = attach.get('type')
                            if att_type == 'photo':
                                is_photo = True
                                sizes = attach['photo'].get('sizes', [])
                                if sizes: links.append(sizes[-1]['url'])
                            elif att_type == 'doc':
                                is_photo = True
                                links.append(attach['doc']['url'])
                            elif att_type == 'video':
                                is_video = True
                                links.append(f"https://vk.com/video{attach['video']['owner_id']}_{attach['video']['id']}")
                        
                        if mode == 'video':
                            if is_photo and not is_video:
                                send_msg(peer_id, "❌ Это не видео!", keyboard=get_main_kb(), reply_to=msg_id)
                            elif is_video and links:
                                add_upload(user_id)
                                # Видео можно сокращать, это не запрещено
                                send_msg(peer_id, f"🎬 Ссылка:\n{shorten_link(links[0])}", keyboard=get_main_kb(), reply_to=msg_id)
                            else:
                                send_msg(peer_id, "❌ Отправь видео!", keyboard=get_main_kb(), reply_to=msg_id)
                            del waiting_mode[peer_id]
                            
                        elif mode == 'one':
                            if is_photo and links:
                                # Загружаем на FastPic, НЕ сокращаем
                                host_link = upload_photo_to_hosting(links[0])
                                if host_link:
                                    add_upload(user_id)
                                    final_text = (f"🌿 Твоя фотография загружена!\n\n🔗 Прямая ссылка на фотохостинг:\n{host_link}\n\n"
                                                  f"💾 Как сохранить:\n1. Скопируй ссылку.\n2. Вставь её в браузер (Safari).\n3. Зажми картинку и выбери «Сохранить».")
                                    send_msg(peer_id, final_text, keyboard=get_main_kb(), reply_to=msg_id)
                                else:
                                    send_msg(peer_id, "❌ Ошибка при загрузке фото. Попробуй ещё раз.", keyboard=get_main_kb(), reply_to=msg_id)
                            else:
                                send_msg(peer_id, "❌ Отправь фото!", keyboard=get_main_kb(), reply_to=msg_id)
                            del waiting_mode[peer_id]
                            
                        elif mode == 'multi':
                            if is_photo and links:
                                add_upload(user_id)
                                final_text = "🌿 Твои фотографии загружены!\n\n"
                                for i, link in enumerate(links, 1):
                                    host_link = upload_photo_to_hosting(link)
                                    if host_link:
                                        final_text += f"🔗 Фото {i}: {host_link}\n\n"
                                    else:
                                        final_text += f"❌ Фото {i}: Ошибка загрузки\n\n"
                                    time.sleep(1.2) 
                                final_text += "💾 Скопируй ссылки и открой в браузере."
                                send_msg(peer_id, final_text, keyboard=get_main_kb(), reply_to=msg_id)
                            else:
                                send_msg(peer_id, "❌ Отправь фото!", keyboard=get_main_kb(), reply_to=msg_id)
                        continue

                # ТЕКСТОВЫЕ КОМАНДЫ
                if text_lower == "начать" or text_lower == "start":
                    send_msg(peer_id, "Привет! Выбирай действие на кнопках внизу 👇", keyboard=get_main_kb(), reply_to=msg_id)
                    continue

                if user_id == ADMIN_ID and ADMIN_ID in waiting_for_manual_reply:
                    reply_data = waiting_for_manual_reply[ADMIN_ID]
                    target_user_id = reply_data["target_user"]
                    report_id = reply_data["report_id"]
                    
                    if report_id not in active_reports:
                        send_msg(ADMIN_ID, f"❌ Ошибка: Репорт #{report_id} уже закрыт.", keyboard=get_main_kb())
                        del waiting_for_manual_reply[ADMIN_ID]
                        continue

                    player_reply = (f"📩 Вам ответил администратор [id{ADMIN_ID}|Владелец]:\n\n💬 {text}\n\n👇 Пожалуйста, оцените работу или закройте вопрос:")
                    send_msg(target_user_id, player_reply, keyboard=get_rating_kb(target_user_id, report_id))
                    send_msg(ADMIN_ID, f"✅ Ответ доставлен игроку!", keyboard=get_main_kb())
                    del waiting_for_manual_reply[ADMIN_ID]
                    continue

                if user_id in waiting_for_rating:
                    try:
                        rating = int(text)
                        if 1 <= rating <= 10:
                            report_id = waiting_for_rating[user_id]
                            del waiting_for_rating[user_id]
                            users_in_report.discard(user_id)
                            if report_id in active_reports: del active_reports[report_id]
                            
                            send_msg(ADMIN_ID, f"⭐ Новый отзыв!\n👤 Пользователь: [id{user_id}|Игрок]\n🌟 Оценка: {rating}/10")
                            
                            if 1 <= rating <= 4:
                                waiting_for_feedback[user_id] = report_id
                                send_msg(peer_id, f"😔 Спасибо за ваш отзыв (Оценка: {rating}/10).\nПодскажите, что именно вам не понравилось?", keyboard=get_neg_feedback_kb(report_id))
                            else:
                                waiting_for_feedback[user_id] = report_id
                                send_msg(peer_id, f"🤩 Спасибо за вашу оценку! (Оценка: {rating}/10).\nПодскажите, что вам понравилось больше всего?", keyboard=get_pos_feedback_kb(report_id))
                        else:
                            send_msg(peer_id, "❌ Оценка должна быть от 1 до 10.", keyboard=get_main_kb())
                    except ValueError:
                        send_msg(peer_id, "❌ Введи число.", keyboard=get_main_kb())
                    continue

                if user_id in waiting_for_feedback:
                    send_msg(peer_id, "⚠️ Пожалуйста, выберите причину на кнопках выше 👆", reply_to=msg_id)
                    continue

                if user_id in waiting_for_manual_report:
                    if text_lower in ["⬅️ назад", "назад"]:
                        waiting_for_manual_report.remove(user_id)
                        send_msg(peer_id, "Главное меню:", keyboard=get_main_kb())
                        continue
                    else:
                        report_id = random.randint(1000, 9999)
                        active_reports[report_id] = user_id 
                        send_msg(ADMIN_ID, f"🆘 Репорт #{report_id}\n👤 От: [id{user_id}|Игрок]\n\n💬 {text}", keyboard=get_admin_report_kb(report_id, user_id))
                        users_in_report.add(user_id) 
                        send_msg(user_id, "✅ Ваш репорт отправлен! Ожидайте ответа.", keyboard=get_main_kb())
                        waiting_for_manual_report.remove(user_id)
                        continue

                if user_id in waiting_for_support:
                    if text_lower in ["⬅️ назад", "назад"]:
                        waiting_for_support.remove(user_id)
                        send_msg(peer_id, "Главное меню:", keyboard=get_main_kb())
                        continue
                    
                    report_id = random.randint(1000, 9999)
                    active_reports[report_id] = user_id
                    send_msg(ADMIN_ID, f"🆘 Репорт #{report_id}\n👤 От: [id{user_id}|Игрок]\n\n💬 {text}", keyboard=get_admin_report_kb(report_id, user_id))
                    users_in_report.add(user_id) 
                    send_msg(user_id, "✅ Ваш репорт отправлен! Ожидайте ответа.", keyboard=get_main_kb())
                    waiting_for_support.remove(user_id)
                    continue

                if text_lower == "стата" and user_id == ADMIN_ID:
                    conn = sqlite3.connect('super_bot.db')
                    c = conn.cursor()
                    c.execute("SELECT user_id, warns, ban_until, uploads FROM users")
                    all_users = c.fetchall()
                    conn.close()
                    stats_text = "📊 Статистика:\n\n"
                    for u_id, w, b_until, ups in all_users:
                        if w > 0 or b_until > time.time() or ups > 0:
                            ban_status = "Нет" if b_until == 0 or b_until < time.time() else "ДА (ЧС)"
                            stats_text += f"👤 ID: {u_id}\n⚠️ Варны: {w}/3\n📤 Загрузок: {ups}\n⛔ ЧС: {ban_status}\n\n"
                    send_msg(peer_id, stats_text)
                    continue

                # Меню
                if "видео" in text_lower:
                    waiting_mode[peer_id] = 'video'
                    send_msg(peer_id, "🎬 Отправь мне видео!", keyboard=get_main_kb())
                elif "несколько" in text_lower:
                    waiting_mode[peer_id] = 'multi'
                    send_msg(peer_id, "📸 Отправь мне несколько фото!\nВажно: прикрепи все фото к одному сообщению.", keyboard=get_main_kb())
                elif "загрузить фото" in text_lower or "создать ссылку" in text_lower:
                    waiting_mode[peer_id] = 'one'
                    send_msg(peer_id, "📸 Отправь мне фотографию, и я сделаю из неё ссылку!", keyboard=get_main_kb())
                elif "статистика" in text_lower:
                    send_msg(peer_id, f"📊 Загружено: {uploads}", keyboard=get_main_kb())
                elif "помощь" in text_lower:
                    send_msg(peer_id, "📖 Помощь по боту\n\n1. Жми «Загрузить фото».\n2. Отправь картинку.\n3. Получи прямую ссылку.\n\nПо всем вопросам пиши в поддержку 👇", keyboard=get_help_kb())
                elif "связь с администрацией" in text_lower:
                    if user_id in users_in_report:
                        send_msg(peer_id, "⏳ У вас уже есть активный репорт!", keyboard=get_main_kb())
                    else:
                        send_msg(peer_id, "📩 Выберите способ обращения:", keyboard=get_choice_kb_player())
                elif "выбор по шаблонам" in text_lower:
                    send_msg(peer_id, "📩 Выберите тему обращения:", keyboard=get_templates_kb())
                    waiting_for_support.add(user_id)
                elif "свой вопрос" in text_lower:
                    send_msg(peer_id, "✍️ Напишите вашу проблему одним сообщением:", keyboard=get_main_kb())
                    waiting_for_manual_report.add(user_id)
                elif "назад" in text_lower:
                    send_msg(peer_id, "Выбирай действие на кнопках внизу 👇", keyboard=get_main_kb())
                else:
                    send_msg(peer_id, "Выбери действие на кнопках 👇", keyboard=get_main_kb())

    except Exception as e:
        print(f"⚠️ Ошибка: {e}")
        time.sleep(2)
