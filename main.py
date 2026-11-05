import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import json, random, sqlite3, time

# ===== НАСТРОЙКИ =====
TOKEN = "vk1.a.ZJv5Q0c0NZUB1AHhY9bDgkq8_yuchIdQweB1DzzAxa_cx6HTZJ7HEg2KlJtP2n_kOuFSFk_M8HRPAtChfrdd6S4y8_1Sp0dlw2hbwuewcIjBDaFR5DlqskY9sfqcsSoycuNQUR9T4rNpqqVc7DDvSItqI4WqNRcpW5v7oO0Zv7Laeh4uE0E754_I35PGFqxnKk_Rc7Sy57gx2hlriWzAJ1VhBDQMeMLXmg0t_yZBN8o"
ADMIN_ID = 200005093141
GROUP_ID = 242296265 

vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
waiting_mode = {}

def send(peer_id, text):
    # Отправляем сообщение БЕЗ клавиатуры (keyboard)
    params = {'peer_id': peer_id, 'message': text, 'random_id': random.randint(1, 2**31)}
    try:
        return vk.messages.send(**params)
    except Exception as e:
        print("Ошибка отправки:", e)
        return None

print("ТЕСТОВЫЙ БОТ БЕЗ КНОПОК ЗАПУЩЕН!")

try:
    longpoll = VkLongPoll(vk_session)
    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            peer_id = event.peer_id
            user_id = peer_id 
            text = event.text.strip()
            text_lower = text.lower()

            # Отвечаем только на Начать и на любые сообщения, чтобы проверить связь
            if text_lower == "начать" or text_lower == "start":
                send(peer_id, "👋 ТЕСТ: Я новый бот, кнопки полностью удалены! Если ты видишь внизу экрана старые кнопки — значит, ВК их закешировал, или работает старый бот.")
            else:
                send(peer_id, "Я получил твое сообщение. Кнопок больше нет.")
                
except Exception as e:
    print("КРИТИЧЕСКАЯ ОШИБКА:", e)
