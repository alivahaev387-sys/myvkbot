import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import json, random, sqlite3, time, requests

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
waiting_for_reply = {} 
waiting_for_manual_reply = {} 
reports = {} 
users_in_report = set() 
waiting_for_rating = set() 

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

def get_rating_kb(target_user_id):
    return json.dumps({
        "inline": True,
        "buttons": [
            [{"action": {"type": "callback", "label": "⭐ Оценить работу", "payload": json.dumps({"cmd": "rate_report", "target_id": target_user_id})}, "color": "positive"},
             {"action": {"type": "callback", "label": "❌ Закрыть вопрос", "payload": json.dumps({"cmd": "close_report", "target_id": target_user_id})}, "color": "negative"}]
        ]
    }, ensure_ascii=False)

print("БОТ ЗАПУЩЕН (Умная система оценок)!")

try:
    for event in longpoll.listen():
        if event.type == VkBotEventType.MESSAGE_EVENT:
            payload = event.object.payload
            user_id = event.object.user_id
            peer_id = event.object.peer_id
            event_id = event.object.event_id
            
            target_id = payload.get("target_id")
            if target_id and str(user_id) != str(target_id):
                vk.messages.sendMessageEventAnswer(
                    event_id=event_id, user_id=user_id, peer_id=peer_id, 
                    event_data=json.dumps({"type": "show_snackbar", "text": "❌ Эта кнопка не для вас!"})
                )
                continue

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

        if event.type == VkBotEventType.MESSAGE_NEW and event.object.message['peer_id']:
            msg = event.object.message
            peer_id = msg['peer_id']
            user_id = msg['from_id'] 
            
            text = msg.get('text', '').strip()
            text_lower = text.lower().replace("@club242296265", "").strip()

            is_ls = (peer_id == user_id)

            # =========================================================
            # 🚀 ТУТ САМАЯ ПРОСТАЯ КОМАНДА ПИНГ (ТОЛЬКО СЛОВО ПОНГ)
            # =========================================================
            if text_lower in ["пинг", "ping", "/ping", "/пинг", "!ping", "!пинг"]:
                send_msg(peer_id, "🏓 Понг!", keyboard=None)
                continue 
            # =========================================================

            if not is_ls:
                continue 

            if text_lower == "начать" or text_lower == "start":
                send_msg(peer_id, "Привет! Выбирай действие на кнопках внизу 👇", keyboard=get_main_kb())
                continue

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
                                        f"Нам очень жаль, что мы не смогли решить вашу проблему идеально. "
                                        f"Мы постараемся стать лучше! Если вопрос всё ещё требует внимания, "
                                        f"создайте новый репорт, и мы обязательно поможем.\n\n"
                                        f"🔒 *Текущий репорт закрыт.*")
                        elif 4 <= rating <= 7:
                            user_msg = (f"🙂 **Спасибо за отзыв (Оценка: {rating}/10).**\n\n"
                                        f"Мы рады, что смогли вам помочь! Если у вас остались "
                                        f"какие-то вопросы, всегда обращайтесь, мы на связи.\n\n"
                                        f"🔒 *Текущий репорт закрыт.*")
                        else: 
                            user_msg = (f"🤩 **Огромное спасибо! (Оценка: {rating}/10)**\n\n"
                                        f"Мы очень рады, что вам всё понравилось и проблема решена! "
                                        f"Ваша высокая оценка делает нашу работу еще лучше.\n\n"
                                        f"🔒 *Текущий репорт закрыт.*")
                        
                        send_msg(peer_id, user_msg, keyboard=get_main_kb())
                        waiting_for_rating.remove(user_id)
                        users_in_report.discard(user_id)
                    else:
                        send_msg(peer_id, "❌ Оценка должна быть от 1 до 10. Попробуй еще раз.", keyboard=get_main_kb())
                except ValueError:
                    send_msg(peer_id, "❌ Пожалуйста, введи число от 1 до 10.", keyboard=get_main_kb())
                continue

            if user_id in waiting_for_manual_report:
                if text_lower == "⬅️ назад" or text_lower == "назад":
                    waiting_for_manual_report.remove(user_id)
                    send_msg(peer_id, "Вы вернулись в главное меню.", keyboard=get_main_kb())
                    continue
                else:
                    support_text = f"🆘 **Репорт от** [id{user_id}|Игрок]:\n\n{text}"
                    msg_res = send_msg(ADMIN_ID, support_text, keyboard=get_report_kb())
                    if msg_res: 
                        reports[msg_res] = user_id
                        users_in_report.add(user_id) 
                    send_msg(user_id, "✅ Твой репорт отправлен! Ожидай ответа.", keyboard=get_main_kb())
                    waiting_for_manual_report.remove(user_id)
                    continue

            if user_id == ADMIN_ID and ADMIN_ID in waiting_for_manual_reply:
                target_user_id = waiting_for_manual_reply[ADMIN_ID]
                send_msg(target_user_id, f"📩 **Вам ответил администратор** [id{ADMIN_ID}|Владелец]:\n\n{text}", keyboard=get_rating_kb(target_user_id))
                send_msg(ADMIN_ID, f"✅ Ответ доставлен [id{target_user_id}|Игроку]. Ожидайте от него оценку.", keyboard=get_main_kb())
                del waiting_for_manual_reply[ADMIN_ID]
                continue

            if user_id == ADMIN_ID and text_lower == "✍️ ответить на репорт":
                if reports:
                    last_msg_id = list(reports.keys())[-1]
                    target_user_id = reports[last_msg_id]
                    waiting_for_reply[ADMIN_ID] = target_user_id
                    send_msg(ADMIN_ID, f"✍️ Выбери способ ответа для [id{target_user_id}|Игрока]:", keyboard=get_choice_kb_admin())
                continue
                
            if user_id == ADMIN_ID and text_lower == "📋 шаблоны ответов":
                if waiting_for_reply.get(ADMIN_ID):
                    send_msg(ADMIN_ID, "📋 Выбери готовый шаблон:", keyboard=get_admin_reply_templates_kb())
                continue
                
            if user_id == ADMIN_ID and text_lower == "✍️ свой ответ":
                if waiting_for_reply.get(ADMIN_ID):
                    target_user_id = waiting_for_reply.pop(ADMIN_ID)
                    waiting_for_manual_reply[ADMIN_ID] = target_user_id
                    send_msg(ADMIN_ID, f"✍️ Напиши свой текст для [id{target_user_id}|Игрока]:", keyboard=get_main_kb())
                continue

            if user_id == ADMIN_ID and ADMIN_ID in waiting_for_reply:
                if text_lower in ["✅ исправлено, проверяй", "⏳ скоро починим", "📱 скачай с компа", "🔄 попробуй еще раз"]:
                    target_user_id = waiting_for_reply[ADMIN_ID]
                    send_msg(target_user_id, f"📩 **Вам ответил администратор** [id{ADMIN_ID}|Владелец]:\n\n{text}", keyboard=get_rating_kb(target_user_id))
                    send_msg(ADMIN_ID, f"✅ Ответ доставлен [id{target_user_id}|Игроку].", keyboard=get_main_kb())
                    del waiting_for_reply[ADMIN_ID] 
                continue

            if user_id in waiting_for_support:
                if text_lower == "⬅️ назад" or text_lower == "назад":
                    waiting_for_support.remove(user_id)
                    send_msg(peer_id, "Вы вернулись в главное меню.", keyboard=get_main_kb())
                    continue
                
                support_text = f"🆘 **Репорт от** [id{user_id}|Игрок]:\n\n{text}"
                msg_res = send_msg(ADMIN_ID, support_text, keyboard=get_report_kb())
                if msg_res: 
                    reports[msg_res] = user_id
                    users_in_report.add(user_id) 
                send_msg(user_id, "✅ Репорт отправлен! Ожидай.", keyboard=get_main_kb())
                waiting_for_support.remove(user_id)
                continue

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

            warns, ban_until, uploads = get_user_data(user_id)
            current_time = int(time.time())

            if ban_until > current_time:
                send_msg(peer_id, f"⛔ **Вы заблокированы!**\nОсталось: {(ban_until - current_time)//86400} дн.")
                continue

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
                help_text = "📖 Как пользоваться ботом:\n1. Жми 'Загрузить фото'.\n2. Отправь картинку.\n3. Получи ссылку."
                send_msg(peer_id, help_text, keyboard=get_help_kb())
                
            elif "связь с администрацией" in text_lower:
                if user_id in users_in_report:
                    send_msg(peer_id, "⏳ **У вас уже есть активный репорт!**\n\nПожалуйста, дождитесь ответа.", keyboard=get_main_kb())
                else:
                    send_msg(peer_id, "📩 Выберите способ обращения:", keyboard=get_choice_kb_player())
                    
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
