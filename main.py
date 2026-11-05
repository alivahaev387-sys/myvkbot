import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import json, random, sqlite3, time

# ===== НАСТРОЙКИ =====
TOKEN = "vk1.a.gQFcsQKruH5TchxgUWh13DsF_6Gz1ELhYd1NoL6Y4nPX-WsQYskpp4llV6fBNpySgogQp6zlky8j3wXRQLqNufPpLReUV1W_ew0KuQHAcXwuQ_kbPHOS3TfXnxr3mKPw72WrPtnV62LeLWxkQjbWlJMszWUDU_ygov2CN7O-RQLe6sAxEmGNbJ8DlYNysnwLyrsz9xXCUQ5g11Vs0qjCXPUTllPaLfRXmlty3U2ZFvM"
ADMIN_ID = 200005093141
GROUP_ID = 242296265 
GROUP_LINK = "https://vk.com/club242296265"

vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
waiting_mode = {}

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

init_db()

# --- ПРОВЕРКА ПОДПИСКИ ---
def is_subscribed(user_id):
    try:
        res = vk.groups.isMember(group_id=GROUP_ID, user_id=user_id)
        return bool(res)
    except:
        return False

def send(peer_id, text):
    kb = {
        "one_time": False, 
        "buttons": [
            [{"action": {"type": "text", "label": "📸 Создать ссылку"}, "color": "positive"}],
            [{"action": {"type": "text", "label": "📸 Несколько фото"}, "color": "primary"}],
            [{"action": {"type": "text", "label": "🎬 Скачать видео"}, "color": "primary"}],
            [{"action": {"type": "text", "label": "📊 Моя статистика"}, "color": "secondary"}],
            [{"action": {"type": "text", "label": "📖 Помощь"}, "color": "negative"}]
        ]
    }
    try:
        if len(text) > 4000:
            text = text[:4000] + "\n... (обрезано)"
        vk.messages.send(peer_id=peer_id, message=text, keyboard=json.dumps(kb, ensure_ascii=False), random_id=random.randint(1, 2**31))
    except Exception as e:
        print("Ошибка отправки:", e)

print("БОТ ЗАПУЩЕН!")

try:
    try:
        vk.groups.setSettings(group_id=GROUP_ID, messages_online=True)
    except: pass

    longpoll = VkLongPoll(vk_session)
    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            peer_id = event.peer_id
            user_id = peer_id 
            text = event.text.lower().strip()

            # === СТАТИСТИКА АДМИНА ===
            if text == "стата" and user_id == ADMIN_ID:
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
                send(peer_id, stats_text)
                continue

            # === ПРОВЕРКА НА ЧС ===
            warns, ban_until, uploads = get_user_data(user_id)
            current_time = int(time.time())

            if ban_until > current_time:
                send(peer_id, f"⛔ **Вы заблокированы в боте!**\nОсталось: {(ban_until - current_time)//86400} дн.")
                continue

            # === ПРОВЕРКА ПОДПИСКИ ===
            if not is_subscribed(user_id):
                send(peer_id, f"🔒 **Доступ ограничен!**\n\nПодпишись: {GROUP_LINK}\nЗатем напиши боту снова.")
                continue

            # === ОБРАБОТКА ФОТО / ВИДЕО ===
            if peer_id in waiting_mode:
                try:
                    msg_info = vk.messages.getById(message_ids=event.message_id)
                    items = msg_info.get('items', [])
                    
                    if items:
                        attachments = items[0].get('attachments', [])
                        links = []
                        
                        for attach in attachments:
                            if attach.get('type') == 'photo':
                                sizes = attach['photo'].get('sizes', [])
                                if sizes: links.append(sizes[-1]['url'])
                            elif attach.get('type') == 'video':
                                v_id = attach['video']['id']
                                o_id = attach['video']['owner_id']
                                links.append(f"https://vk.com/video{o_id}_{v_id}")
                        
                        if links:
                            add_upload(user_id)
                            mode = waiting_mode[peer_id]
                            
                            if mode == 'video':
                                send(peer_id, f"🎬 **Ссылка на видео:**\n{links[0]}")
                            elif mode == 'one':
                                send(peer_id, f"🌿 **Фото загружено!**\n\n🔗 Ссылка: {links[0]}\n\nСкопируй её и вставь куда нужно.")
                            else:
                                final_text = "🌿 **Файлы загружены!**\n\n"
                                for i, link in enumerate(links, 1):
                                    final_text += f"🔗 Файл {i}: {link}\n\n"
                                send(peer_id, final_text)
                except Exception as e: print(e)
                
                if peer_id in waiting_mode: del waiting_mode[peer_id]
                continue

            # === ЛОГИКА КНОПОК ===
            if "видео" in text:
                waiting_mode[peer_id] = 'video'
                send(peer_id, "🎬 Отправь видео, и я дам ссылку.")
            elif "несколько фото" in text:
                waiting_mode[peer_id] = 'multi'
                send(peer_id, "📸 Отправь сразу несколько фото.")
            elif "создать ссылку" in text:
                waiting_mode[peer_id] = 'one'
                send(peer_id, "📸 Отправь одно фото.")
            elif "моя статистика" in text:
                rank = "Новичок"
                if uploads >= 10: rank = "Хостинг-Мастер"
                elif uploads >= 5: rank = "Активный"
                elif uploads >= 1: rank = "Пользователь"
                send(peer_id, f"📊 **Твоя статистика:**\n\n📤 Загружено файлов: {uploads}\n🏅 Твой ранг: {rank}")
            elif "помощь" in text:
                help_text = (
                    "📖 **Как пользоваться ботом:**\n\n"
                    "1. Жми кнопку **'Создать ссылку'** и отправь боту картинку.\n"
                    "2. Бот вышлет тебе прямую ссылку на фото.\n"
                    "3. Скопируй ссылку и вставь куда нужно.\n\n"
                    "💾 *Как сохранить на iPhone:* Открой ссылку, зажми картинку и выбери «Сохранить изображение»."
                )
                send(peer_id, help_text)
            elif text == "начать" or text == "start":
                send(peer_id, "Привет! Выбирай действие на кнопках внизу 👇")
            else:
                send(peer_id, "Жми кнопки внизу 👇")

except Exception as e:
    print("КРИТИЧЕСКАЯ ОШИБКА:", e)
