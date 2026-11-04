import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import json, random

# ===== ВСТАВЬТЕ СЮДА ВАШ НОВЫЙ ТОКЕН =====
TOKEN = "ВАШ_НОВЫЙ_ТОКЕН_СЮДА"

vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()

waiting_photo = set()
waiting_video = set()

def send(peer_id, text):
    kb = {
        "one_time": False, 
        "buttons": [
            [{"action": {"type": "text", "label": "📸 Создать ссылку"}, "color": "positive"}],
            [{"action": {"type": "text", "label": "🎬 Скачать видео"}, "color": "primary"}],
            [{"action": {"type": "text", "label": "🕵️ Мафию"}, "color": "secondary"}]
        ]
    }
    try:
        vk.messages.send(peer_id=peer_id, message=text, keyboard=json.dumps(kb, ensure_ascii=False), random_id=random.randint(1, 2**31))
    except Exception as e:
        print("Ошибка отправки:", e)

print("БОТ ЗАПУЩЕН (Скачивание видео из ВК)!")

longpoll = VkLongPoll(vk_session)

for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        peer_id = event.peer_id
        text = event.text.lower().strip()

        # === ОБРАБОТКА ФОТО ===
        if peer_id in waiting_photo:
            try:
                msg_info = vk.messages.getById(message_ids=event.message_id)
                items = msg_info.get('items', [])
                if items:
                    attachments = items[0].get('attachments', [])
                    photo_url = None
                    for attach in attachments:
                        if attach.get('type') == 'photo':
                            sizes = attach['photo'].get('sizes', [])
                            if sizes:
                                photo_url = sizes[-1]['url']
                                break
                    
                    if photo_url:
                        send(peer_id, f"✅ Ссылка на фото:\n{photo_url}")
                    else:
                        send(peer_id, "❌ В сообщении нет фото.")
            except: send(peer_id, "❌ Ошибка ВК.")
            waiting_photo.remove(peer_id)
            continue

        # === ОБРАБОТКА ВИДЕО ===
        if peer_id in waiting_video:
            try:
                msg_info = vk.messages.getById(message_ids=event.message_id)
                items = msg_info.get('items', [])
                if items:
                    attachments = items[0].get('attachments', [])
                    video_url_vk = None
                    
                    for attach in attachments:
                        if attach.get('type') == 'video':
                            video_id = attach['video']['id']
                            owner_id = attach['video']['owner_id']
                            video_url_vk = f"https://vk.com/video{owner_id}_{video_id}"
                            break
                    
                    if video_url_vk:
                        send(peer_id, "⏳ Скачиваю видео с серверов ВК, подожди 10-15 секунд...")
                        send(peer_id, f"🎬 Ссылка на видео (скопируй и открой в браузере, оттуда скачаешь):\n{video_url_vk}")
                    else:
                        send(peer_id, "❌ В сообщении нет видео.")
            except Exception as e: 
                print(e)
                send(peer_id, "❌ Ошибка ВК.")
            waiting_video.remove(peer_id)
            continue

        # === ЛОГИКА КНОПОК ===
        if "мафию" in text:
            send(peer_id, "🕵️ **МАФИЯ**\nНапиши в беседе 'Создать мафия', чтобы начать!")
        elif "создать ссылку" in text:
            waiting_photo.add(peer_id)
            send(peer_id, "📸 Отправь мне фото (как картинку), и я выдам ссылку.")
        elif "видео" in text:
            waiting_video.add(peer_id)
            send(peer_id, "🎬 Перешли мне видео из ВК (как обычное видео), и я выдам на него ссылку.")
        elif text == "начать" or text == "start":
            send(peer_id, "Привет! Выбирай действие на кнопках внизу 👇")
        else:
            send(peer_id, "Жми кнопки внизу 👇")
