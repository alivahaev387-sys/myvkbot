import vk_api
from vk_api.longpoll import VkLongPoll, VkBotEventType
import json, random, sqlite3, time, requests

# ===== НАСТРОЙКИ =====
# ВСТАВЬТЕ СЮДА ВАШ ТОКЕН ГРУППЫ
TOKEN = "vk1.a.GPEBmYPG-udUnhJYcT_4Zo-jEKzU7VFUYVzRDNwr1wVwo_fsBabigDoS-2BW9bvMbjdYBmf-QH6dwf-ZL4dMYkKMEEiviqU5GPmM5kaG4Xt535Hb1ApvImzJkk_cq-Q7ZxOQYVPbnULj0Fg6U0yDNSPgLwANkGKX348kTlENY6s99NOBeUO-e486DAX-0XtbAa3tmQdMYjF2GLxluGvHrhFHhvr5YCuDXfYxTgw5cYo" "ВАШ_ТОКЕН_ЗДЕСЬ" 
ADMIN_ID = 200005093141
GROUP_ID = 242296265 
GROUP_LINK = "https://vk.com/club242296265"

vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()

# Переменные состояния
waiting_mode = {} # Режим ожидания контента: 'one', 'multi', 'video'
waiting_for_support = set() 
waiting_for_manual_report = set()
waiting_for_reply = {} 
waiting_for_manual_reply = {} 
reports = {} 
users_in_report = set() 

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

# --- ПРОВЕРКИ ---
def is_subscribed(user_id):
    try:
        res = vk.groups.isMember(group_id=GROUP_ID, user_id=user_id)
        return bool(res)
    except:
        return False

def send(peer_id, text, keyboard=None):
    params = {'peer_id': peer_id, 'message': text, 'random_id': random.randint(1, 2**31)}
    if keyboard: params['keyboard'] = keyboard
    try:
        return vk.messages.send(**params)
    except Exception as e:
        print("Ошибка отправки:", e)
        return None

# --- TELEGRAPH API ---
def get_telegraph_token():
    """Получает токен для создания страниц"""
    try:
        # Создаем аккаунт (или используем существующий, если нужно постоянное имя)
        res = requests.post("https://api.telegra.ph/createAccount", data={
            "short_name": "PhotoBotLinker",
            "author_name": "VK Bot",
            "author_url": GROUP_LINK
        }).json()
        if res.get("ok"): 
            return res["result"]["access_token"]
    except: pass
    return None

def upload_image_to_telegraph(img_data):
    """Загружает картинку и возвращает ссылку"""
    try:
        res = requests.post("https://api.telegra.ph/upload", files={'file': ('image.jpg', img_data)}, timeout=10).json()
        if isinstance(res, list) and 'src' in res[0]:
            return f"https://telegra.ph{res[0]['src']}"
    except: pass
    return None

def create_telegraph_page(title, image_urls, token):
    """Создает одну страницу с несколькими картинками"""
    try:
        # Формируем контент для Telegraph
        content = [{"tag": "img", "attrs": {"src": url}} for url in image_urls]
        
        payload = {
            "access_token": token, 
            "title": title, 
            "content": json.dumps(content), 
            "return_content": False
        }
        res = requests.post("https://api.telegra.ph/createPage", data=payload, timeout=10).json()
        if res.get("ok"): 
            return res["result"]["url"]
    except Exception as e:
        print(f"Ошибка создания страницы: {e}")
    return None

# --- КЛАВИАТУРЫ (БЕЗ ИЗМЕНЕНИЙ) ---
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

def get_choice_kb_admin():
    return json.dumps({
        "one_time": False, 
        "buttons": [
            [{"action": {"type": "text", "label": "📋 Шаблоны ответов"}, "color": "primary"},
             {"action": {"type": "text", "label": "✍️ Свой ответ"}, "color": "positive"}],
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

def get_admin_reply_templates_kb():
    return json.dumps({
        "one_time": False,
        "buttons": [
            [{"action": {"type": "text", "label": "✅ Исправлено, проверяй"}, "color": "positive"},
             {"action": {"type": "text", "label": "⏳ Скоро починим"}, "color": "primary"}],
            [{"action": {"type": "text", "label": "📱 Скачай с компа"}, "color": "secondary"},
             {"action": {"type": "text", "label": "🔄 Попробуй еще раз"}, "color": "secondary"}],
            [{"action": {"type": "text", "label": "⬅️ Назад"}, "color": "secondary"}]
        ]
    }, ensure_ascii=False)

def get_report_kb():
    return json.dumps({
        "one_time": False,
        "buttons": [
            [{"action": {"type": "text", "label": "✍️ Ответить на репорт"}, "color": "positive"}],
            [{"action": {"type": "text", "label": "⬅️ Назад"}, "color": "secondary"}]
        ]
    }, ensure_ascii=False)

print("БОТ ЗАПУЩЕН! Режим: Одна ссылка на альбом фото.")

try:
    longpoll = VkLongPoll(vk_session)
    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            peer_id = event.peer_id
            user_id = peer_id 
            text = event.text.strip()
            text_lower = text.lower()

            # === СТАРТ ===
            if text_lower == "начать" or text_lower == "start":
                send(peer_id, "Привет! Выбирай действие на кнопках внизу 👇", keyboard=get_main_kb())
                continue

            # === АДМИНКА И РЕПОРТЫ (БЕЗ ИЗМЕНЕНИЙ) ===
            if user_id in waiting_for_manual_report:
                support_text = f"🆘 **Репорт от** [id{user_id}|Игрок]:\n\n{text}"
                msg_res = send(ADMIN_ID, support_text, keyboard=get_report_kb())
                if msg_res: 
                    reports[msg_res] = user_id
                    users_in_report.add(user_id) 
                send(user_id, "✅ Твой репорт отправлен! Ожидай ответа.", keyboard=get_main_kb())
                waiting_for_manual_report.remove(user_id)
                continue

            if user_id == ADMIN_ID and ADMIN_ID in waiting_for_manual_reply:
                target_user_id = waiting_for_manual_reply[ADMIN_ID]
                send(target_user_id, f"📩 **Вам ответил администратор** [id{ADMIN_ID}|Владелец]:\n\n{text}", keyboard=get_main_kb())
                send(ADMIN_ID, f"✅ Ответ доставлен [id{target_user_id}|Игроку].", keyboard=get_main_kb())
                del waiting_for_manual_reply[ADMIN_ID]
                users_in_report.discard(target_user_id) 
                continue

            if user_id == ADMIN_ID and text_lower == "✍️ ответить на репорт":
                if reports:
                    last_msg_id = list(reports.keys())[-1]
                    target_user_id = reports[last_msg_id]
                    waiting_for_reply[ADMIN_ID] = target_user_id
                    send(ADMIN_ID, f"✍️ Выбери способ ответа для [id{target_user_id}|Игрока]:", keyboard=get_choice_kb_admin())
                continue
                
            if user_id == ADMIN_ID and text_lower == "📋 шаблоны ответов":
                if waiting_for_reply.get(ADMIN_ID):
                    send(ADMIN_ID, "📋 Выбери готовый шаблон:", keyboard=get_admin_reply_templates_kb())
                continue
                
            if user_id == ADMIN_ID and text_lower == "✍️ свой ответ":
                if waiting_for_reply.get(ADMIN_ID):
                    target_user_id = waiting_for_reply.pop(ADMIN_ID)
                    waiting_for_manual_reply[ADMIN_ID] = target_user_id
                    send(ADMIN_ID, f"✍️ Напиши свой текст для [id{target_user_id}|Игрока]:", keyboard=get_main_kb())
                continue

            if user_id == ADMIN_ID and ADMIN_ID in waiting_for_reply:
                if text_lower in ["✅ исправлено, проверяй", "⏳ скоро починим", "📱 скачай с компа", "🔄 попробуй еще раз"]:
                    target_user_id = waiting_for_reply[ADMIN_ID]
                    send(target_user_id, f"📩 **Вам ответил администратор** [id{ADMIN_ID}|Владелец]:\n\n{text}", keyboard=get_main_kb())
                    send(ADMIN_ID, f"✅ Ответ доставлен [id{target_user_id}|Игроку].", keyboard=get_main_kb())
                    del waiting_for_reply[ADMIN_ID] 
                    users_in_report.discard(target_user_id) 
                continue

            if user_id in waiting_for_support:
                support_text = f"🆘 **Репорт от** [id{user_id}|Игрок]:\n\n{text}"
                msg_res = send(ADMIN_ID, support_text, keyboard=get_report_kb())
                if msg_res: 
                    reports[msg_res] = user_id
                    users_in_report.add(user_id) 
                send(user_id, "✅ Репорт отправлен! Ожидай.", keyboard=get_main_kb())
                waiting_for_support.remove(user_id)
                continue

            # === СТАТИСТИКА ===
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
                send(peer_id, stats_text)
                continue

            # === ПРОВЕРКА БЛОКИРОВКИ И ПОДПИСКИ ===
            warns, ban_until, uploads = get_user_data(user_id)
            current_time = int(time.time())

            if ban_until > current_time:
                send(peer_id, f"⛔ **Вы заблокированы!**\nОсталось: {(ban_until - current_time)//86400} дн.")
                continue

            if not is_subscribed(user_id):
                send(peer_id, f"🔒 **Доступ ограничен!**\nПодпишись: {GROUP_LINK}")
                continue

            # === ОБРАБОТКА ФОТО/ВИДЕО (ГЛАВНАЯ ЛОГИКА) ===
            if peer_id in waiting_mode:
                try:
                    msg_info = vk.messages.getById(message_ids=event.message_id)
                    items = msg_info.get('items', [])
                    if items:
                        attachments = items[0].get('attachments', [])
                        urls = []
                        
                        # Сбор ссылок на фото
                        for attach in attachments:
                            if attach.get('type') == 'photo':
                                sizes = attach['photo'].get('sizes', [])
                                best_url = None
                                # Ищем оптимальный размер
                                for size in sizes:
                                    if size.get('type') in ['y', 'x']: # y=807, x=604
                                        best_url = size['url']
                                        break
                                if not best_url and sizes: best_url = sizes[-1]['url']
                                if best_url: urls.append(best_url)
                        
                        mode = waiting_mode[peer_id]
                        
                        # Если режим 'one' (одно фото), обрезаем список до 1 элемента
                        if mode == 'one' and len(urls) > 1:
                            urls = urls[:1] 

                        if urls:
                            send(peer_id, "⏳ Загружаю фото и создаю ссылку...")
                            
                            # 1. Загружаем все картинки на хостинг Telegraph
                            uploaded_urls = []
                            for u in urls:
                                try:
                                    img_data = requests.get(u, timeout=10).content
                                    tg_link = upload_image_to_telegraph(img_data)
                                    if tg_link: uploaded_urls.append(tg_link)
                                except:
                                    continue
                            
                            if uploaded_urls:
                                add_upload(user_id)
                                
                                # 2. Генерация ссылки
                                final_link = ""
                                
                                if len(uploaded_urls) == 1:
                                    # Если фото одно - прямая ссылка на картинку
                                    final_link = uploaded_urls[0]
                                    msg_text = (f"🌿 **Твоя фотография готова!**\n\n"
                                                f"🔗 Ссылка: {final_link}\n\n"
                                                f"💾 Нажми на ссылку, чтобы открыть и сохранить.")
                                else:
                                    # Если фото несколько - создаем СТРАНИЦУ с галереей
                                    token = get_telegraph_token()
                                    page_url = create_telegraph_page("Фотоальбом", uploaded_urls, token) if token else None
                                    
                                    if page_url:
                                        final_link = page_url
                                        msg_text = (f"🌿 **Твои {len(uploaded_urls)} фото загружены!**\n\n"
                                                    f"🔗 Общая ссылка: {final_link}\n\n"
                                                    f"💾 Внутри ссылки находятся все твои фото.")
                                    else:
                                        # Фоллбек: если страница не создалась, кидаем списком
                                        final_link = "Список ссылок ниже"
                                        msg_text = "🌿 **Твои фотографии загружены!**\n\n"
                                        for i, link in enumerate(uploaded_urls, 1):
                                            msg_text += f"🔗 Фото {i}: {link}\n"
                                
                                send(peer_id, msg_text, keyboard=get_main_kb())
                            else:
                                send(peer_id, "⚠️ **Ошибка загрузки.** Попробуй еще раз.", keyboard=get_main_kb())
                        else:
                            send(peer_id, "❌ В сообщении нет фото.", keyboard=get_main_kb())
                except Exception as e: 
                    print(e)
                
                # Сброс режима ожидания
                if peer_id in waiting_mode: del waiting_mode[peer_id]
                continue

            # === КНОПКИ МЕНЮ ===
            if "видео" in text_lower:
                waiting_mode[peer_id] = 'video'
                send(peer_id, "🎬 **Отправь мне видео!** (Пока работает только с фото, но режим активирован)", keyboard=get_main_kb())
            
            elif "несколько" in text_lower:
                # Режим для альбома -> одна ссылка
                waiting_mode[peer_id] = 'multi'
                send(peer_id, "📸 **Отправь мне несколько фото!**\nЯ объединю их в одну ссылку.", keyboard=get_main_kb())
            
            elif "загрузить фото" in text_lower or "создать ссылку" in text_lower:
                # Режим для одного фото
                waiting_mode[peer_id] = 'one'
                send(peer_id, "📸 **Отправь мне фотографию!**", keyboard=get_main_kb())
            
            elif "статистика" in text_lower:
                send(peer_id, f"📊 **Загружено:** {uploads}", keyboard=get_main_kb())
            
            elif "помощь" in text_lower:
                help_text = "📖 Как пользоваться ботом:\n1. Жми 'Загрузить фото'.\n2. Отправь картинку.\n3. Получи ссылку."
                send(peer_id, help_text, keyboard=get_help_kb())
                
            elif "связь с администрацией" in text_lower:
                if user_id in users_in_report:
                    send(peer_id, "⏳ **У вас уже есть активный репорт!**\n\nПожалуйста, дождитесь ответа.", keyboard=get_main_kb())
                else:
                    send(peer_id, "📩 Выберите способ обращения:", keyboard=get_choice_kb_player())
                    
            elif "выбор по шаблонам" in text_lower:
                send(peer_id, "📩 **Выберите тему обращения:**", keyboard=get_templates_kb())
                waiting_for_support.add(user_id)
                
            elif "свой вопрос" in text_lower:
                send(peer_id, "✍️ **Напишите вашу проблему одним сообщением:**", keyboard=get_main_kb())
                waiting_for_manual_report.add(user_id)
                
            elif "назад" in text_lower:
                send(peer_id, "Привет! Выбирай действие на кнопках внизу 👇", keyboard=get_main_kb())
                
            else:
                send(peer_id, "Выбери действие на кнопках 👇", keyboard=get_main_kb())

except Exception as e:
    print("КРИТИЧЕСКАЯ ОШИБКА:", e)
