import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import json, random, sqlite3, time, requests

# ===== ТОКЕН =====
TOKEN = "vk1.a.GPEBmYPG-udUnhJYcT_4Zo-jEKzU7VFUYVzRDNwr1wVwo_fsBabigDoS-2BW9bvMbjdYBmf-QH6dwf-ZL4dMYkKMEEiviqU5GPmM5kaG4Xt535Hb1ApvImzJkk_cq-Q7ZxOQYVPbnULj0Fg6U0yDNSPgLwANkGKX348kTlENY6s99NOBeUO-e486DAX-0XtbAa3tmQdMYjF2GLxluGvHrhFHhvr5YCuDXfYxTgw5cYo"
ADMIN_ID = 200005093141
GROUP_ID = 242296265 
GROUP_LINK = "https://vk.com/club242296265"
IMGBB_API_KEY = "a771230778ab5231d5065a6c92834a11" 

vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
waiting_mode = {}
waiting_for_support = set() 
waiting_for_manual_report = set()
waiting_for_reply = {} 
waiting_for_manual_reply = {} 
reports = {} 
users_in_report = set() 

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

# --- СУПЕР-ЗАЩИТА: ПРОКСИ ДЛЯ ЗАГРУЗКИ ---
def get_clean_link(vk_image_url):
    try:
        # Скачиваем фото с прокси (притворяемся браузером)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        # Пытаемся получить саму картинку через прокси, чтобы обойти блокировку ВК
        proxy_url = f"https://api.allorigins.win/raw?url={vk_image_url}"
        img_data = requests.get(proxy_url, headers=headers, timeout=10).content
        
        # Если скачался мусор (ошибка прокси), пробуем напрямую
        if len(img_data) < 2000:
            img_data = requests.get(vk_image_url, headers=headers, timeout=10).content
            
        if len(img_data) < 2000:
            return None

        # 1. Пытаемся загрузить на ImgBB (ждем 10 секунд)
        try:
            res = requests.post(
                "https://api.imgbb.com/1/upload",
                params={"key": IMGBB_API_KEY},
                files={"image": img_data},
                timeout=10
            ).json()
            if res.get("success"): return res["data"]["url"]
        except: pass
            
        # 2. Если ImgBB упал, летим на Telegraph
        try:
            res = requests.post('https://api.telegra.ph/upload', files={'file': ('image.jpg', img_data)}, timeout=10)
            if res.status_code == 200:
                return f"https://telegra.ph{res.json()[0]['src']}"
        except: pass

        # 3. Если и он упал, летим на Catbox
        try:
            res = requests.post("https://catbox.moe/user/api.php", data={"reqtype": "fileupload"}, files={"fileToUpload": ("image.jpg", img_data)}, timeout=10)
            if res.status_code == 200 and "http" in res.text: return res.text.strip()
        except: pass

        # 4. Если ВСЕ УПАЛИ — делаем маскировку через wsrv.nl (это не даст ошибку, но ссылка будет работать)
        clean_url = vk_image_url.replace('https://', '').replace('http://', '')
        return f"https://wsrv.nl/?url={clean_url}&w=1200"
                
    except Exception as e:
        print("Критическая ошибка загрузки:", e)
        # Даже если всё сломалось, выдаем замаскированную ссылку ВК!
        clean_url = vk_image_url.replace('https://', '').replace('http://', '')
        return f"https://wsrv.nl/?url={clean_url}&w=1200"

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

print("БОТ ЗАПУЩЕН (Прокси + Обход блокировок)!")

try:
    longpoll = VkLongPoll(vk_session)
    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            peer_id = event.peer_id
            user_id = peer_id 
            text = event.text.strip()
            text_lower = text.lower()

            if text_lower == "начать" or text_lower == "start":
                send(peer_id, "Привет! Выбирай действие на кнопках внизу 👇", keyboard=get_main_kb())
                continue

            # РЕПОРТЫ И ОТВЕТЫ АДМИНА
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

            # СТАТИСТИКА
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

            # ЧС И ПОДПИСКА
            warns, ban_until, uploads = get_user_data(user_id)
            current_time = int(time.time())

            if ban_until > current_time:
                send(peer_id, f"⛔ **Вы заблокированы!**\nОсталось: {(ban_until - current_time)//86400} дн.")
                continue

            if not is_subscribed(user_id):
                send(peer_id, f"🔒 **Доступ ограничен!**\nПодпишись: {GROUP_LINK}")
                continue

            # ОБРАБОТКА ФОТО/ВИДЕО
            if peer_id in waiting_mode:
                try:
                    msg_info = vk.messages.getById(message_ids=event.message_id)
                    items = msg_info.get('items', [])
                    if items:
                        attachments = items[0].get('attachments', [])
                        links = []
                        is_video, is_photo = False, False
                        
                        for attach in attachments:
                            if attach.get('type') == 'photo':
                                is_photo = True
                                sizes = attach['photo'].get('sizes', [])
                                # Берем самый большой размер
                                if sizes: links.append(sizes[-1]['url'])
                            elif attach.get('type') == 'video':
                                is_video = True
                                v_id = attach['video']['id']
                                o_id = attach['video']['owner_id']
                                links.append(f"https://vk.com/video{o_id}_{v_id}")
                        
                        mode = waiting_mode[peer_id]
                        
                        if mode == 'video':
                            if is_photo and not is_video:
                                send(peer_id, "❌ **Это не видео!**", keyboard=get_main_kb())
                            elif is_video and links:
                                add_upload(user_id)
                                send(peer_id, f"🎬 **Ссылка:**\n{links[0]}", keyboard=get_main_kb())
                        elif mode == 'one':
                            if is_photo and links:
                                clean_link = get_clean_link(links[0])
                                if clean_link:
                                    add_upload(user_id)
                                    final_text = (f"🌿 **Твоя фотография загружена!**\n\n"
                                                  f"🔗 Ссылка: {clean_link}\n\n"
                                                  f"💾 **Как сохранить:**\n1. Нажми на ссылку (откроется в браузере).\n2. Зажми картинку пальцем и выбери «Сохранить изображение».")
                                    send(peer_id, final_text, keyboard=get_main_kb())
                                else:
                                    send(peer_id, "⚠️ **Все сервера перегружены.** Попробуй еще раз через минуту.", keyboard=get_main_kb())
                            else:
                                send(peer_id, "❌ Отправь фото!", keyboard=get_main_kb())
                        elif mode == 'multi':
                            if is_photo and links:
                                final_text = "🌿 **Твои фотографии загружены!**\n\n"
                                success_count = 0
                                for i, link in enumerate(links, 1):
                                    clean_link = get_clean_link(link)
                                    if clean_link:
                                        final_text += f"🔗 Фото {i}: {clean_link}\n\n"
                                        success_count += 1
                                
                                if success_count > 0:
                                    add_upload(user_id)
                                    final_text += "💾 *Зажми картинку в браузере и выбери «Сохранить».*"
                                    send(peer_id, final_text, keyboard=get_main_kb())
                                else:
                                    send(peer_id, "⚠️ **Все сервера перегружены.** Попробуй позже.", keyboard=get_main_kb())
                            else:
                                send(peer_id, "❌ Отправь фото!", keyboard=get_main_kb())
                except Exception as e: print(e)
                if peer_id in waiting_mode: del waiting_mode[peer_id]
                continue

            # КНОПКИ МЕНЮ
            if "видео" in text_lower:
                waiting_mode[peer_id] = 'video'
                send(peer_id, "🎬 **Отправь мне видео!**", keyboard=get_main_kb())
            elif "несколько" in text_lower:
                waiting_mode[peer_id] = 'multi'
                send(peer_id, "📸 **Отправь мне несколько фото!**", keyboard=get_main_kb())
            elif "загрузить фото" in text_lower or "создать ссылку" in text_lower:
                waiting_mode[peer_id] = 'one'
                send(peer_id, "📸 **Отправь мне фотографию, и я сделаю из неё прямую ссылку!**", keyboard=get_main_kb())
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
