package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math/rand"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/SevereCloud/vksdk/v3/api"
	"github.com/SevereCloud/vksdk/v3/api/params"
	"github.com/SevereCloud/vksdk/v3/events"
	"github.com/SevereCloud/vksdk/v3/longpoll-bot"
	"github.com/SevereCloud/vksdk/v3/object"
	_ "modernc.org/sqlite"
)

// ===== НАСТРОЙКИ =====
const (
	Token   = "vk1.a.GPEBmYPG-udUnhJYcT_4Zo-jEKzU7VFUYVzRDNwr1wVwo_fsBabigDoS-2BW9bvMbjdYBmf-QH6dwf-ZL4dMYkKMEEiviqU5GPmM5kaG4Xt535Hb1ApvImzJkk_cq-Q7ZxOQYVPbnULj0Fg6U0yDNSPgLwANkGKX348kTlENY6s99NOBeUO-e486DAX-0XtbAa3tmQdMYjF2GLxluGvHrhFHhvr5YCuDXfYxTgw5cYo"
	AdminID = 200005093141
	GroupID = 242296265
)

var (
	vk *api.VK
	db *sql.DB

	// Состояния с защитой от одновременного доступа (Mutex)
	stateMutex          sync.Mutex
	waitingMode         = make(map[int]string)
	waitingForSupport   = make(map[int]bool)
	waitingManualReport = make(map[int]bool)
	waitingManualReply  = make(map[int]int) // AdminID -> target_user_id
	usersInReport       = make(map[int]bool)
	waitingForRating    = make(map[int]int) // userID -> reportID
	activeReports       = make(map[int]int) // reportID -> userID
)

func main() {
	vk = api.NewVK(Token)
	initDB()

	lp, err := longpoll.NewLongPoll(vk, GroupID)
	if err != nil {
		log.Fatal("Ошибка LongPoll: ", err)
	}

	lp.MessageNew(handleMessage)
	lp.MessageEvent(handleEvent)

	// Запуск фоновой проверки разбана
	go autoUnbanChecker()

	log.Println("БОТ НА GO ЗАПУЩЕН!")
	if err := lp.Run(); err != nil {
		log.Fatal("Ошибка запуска: ", err)
	}
}

// ===== БАЗА ДАННЫХ =====
func initDB() {
	var err error
	db, err = sql.Open("sqlite", "super_bot.db")
	if err != nil {
		log.Fatal(err)
	}
	query := `CREATE TABLE IF NOT EXISTS users (
		user_id INTEGER PRIMARY KEY,
		warns INTEGER DEFAULT 0,
		ban_until INTEGER DEFAULT 0,
		uploads INTEGER DEFAULT 0
	);`
	_, err = db.Exec(query)
	if err != nil {
		log.Fatal(err)
	}
}

func getUserData(userID int) (warns, banUntil, uploads int) {
	err := db.QueryRow("SELECT warns, ban_until, uploads FROM users WHERE user_id = ?", userID).Scan(&warns, &banUntil, &uploads)
	if err == sql.ErrNoRows {
		db.Exec("INSERT INTO users (user_id, warns, ban_until, uploads) VALUES (?, 0, 0, 0)", userID)
		return 0, 0, 0
	}
	return
}

func addUpload(userID int) {
	db.Exec("UPDATE users SET uploads = uploads + 1 WHERE user_id = ?", userID)
}

func addWarn(userID int) int {
	w, _, _ := getUserData(userID)
	w++
	db.Exec("UPDATE users SET warns = ? WHERE user_id = ?", w, userID)
	return w
}

// ===== ОБРАБОТКА СООБЩЕНИЙ =====
func handleMessage(_ context.Context, obj events.MessageNewObject) {
	msg := obj.Message
	peerID := msg.PeerID
	userID := msg.FromID
	text := strings.ToLower(strings.TrimSpace(strings.ReplaceAll(msg.Text, "@club242296265", "")))

	// 1. ПИНГ (работает везде)
	if text == "/ping" || text == "пинг" || text == "!пинг" {
		pingMs := time.Now().UnixMilli() - int64(msg.Date)*1000
		if pingMs < 0 {
			pingMs = 0
		}
		pingText := fmt.Sprintf("🏓 Понг!\n\n⚡ Скорость: %d мс\n📊 Статус: 🟢 Отлично", pingMs)
		sendMsg(peerID, pingText, nil)
		return
	}

	// Дальше только для ЛС
	if peerID != userID {
		return
	}

	warns, banUntil, uploads := getUserData(userID)
	now := int(time.Now().Unix())

	// Проверка разбана
	if banUntil > 0 && banUntil <= now {
		db.Exec("UPDATE users SET ban_until = 0 WHERE user_id = ?", userID)
		banUntil = 0
		sendMsg(peerID, "🎉 **ПРИВЕТСТВУЕМ СНОВА!**\n\nС вас снят ЧС. Больше не нарушайте!", getMainKB())
	}

	// Проверка на бан
	if banUntil > now {
		left := banUntil - now
		sendMsg(peerID, fmt.Sprintf("⛔ ВЫ В ЧС! Осталось: %d сек.", left), nil)
		return
	}

	// Команды админа
	if userID == AdminID && (strings.Contains(text, "снять чс") || strings.Contains(text, "разбан")) {
		if msg.ReplyMessage != nil {
			target := msg.ReplyMessage.FromID
			db.Exec("UPDATE users SET warns = 0, ban_until = 0 WHERE user_id = ?", target)
			sendMsg(AdminID, fmt.Sprintf("✅ С [id%d|Игрока] снят ЧС.", target), getMainKB())
			sendMsg(target, "✅ Администратор снял с вас ЧС!", getMainKB())
		} else {
			sendMsg(AdminID, "❌ Ответь на сообщение игрока командой 'разбан'.", getMainKB())
		}
		return
	}

	if userID == AdminID && text == "стата" {
		rows, _ := db.Query("SELECT user_id, warns, ban_until, uploads FROM users")
		defer rows.Close()
		res := "📊 СТАТИСТИКА:\n\n"
		for rows.Next() {
			var u, w, b, up int
			rows.Scan(&u, &w, &b, &up)
			if w > 0 || b > now || up > 0 {
				res += fmt.Sprintf("ID: %d\nВарны: %d/3\nЗагрузки: %d\n\n", u, w, up)
			}
		}
		sendMsg(peerID, res, nil)
		return
	}

	// Ожидание ответа от Админа
	if userID == AdminID {
		stateMutex.Lock()
		target, isWaiting := waitingManualReply[AdminID]
		stateMutex.Unlock()
		if isWaiting {
			playerReply := fmt.Sprintf("📩 **Вам ответил администратор** [id%d|Владелец]:\n\n💬 *%s*\n\n👇 *Оцените или закройте:*", AdminID, msg.Text)
			sendMsg(target, playerReply, getRatingKB(target, 0)) // ID репорта не критичен для кнопок здесь
			sendMsg(AdminID, "✅ Ответ доставлен. Ожидаем оценку.", getMainKB())
			stateMutex.Lock()
			delete(waitingManualReply, AdminID)
			stateMutex.Unlock()
			return
		}
	}

	// Ввод оценки игроком
	stateMutex.Lock()
	_, isRating := waitingForRating[userID]
	stateMutex.Unlock()
	if isRating {
		rating, err := strconv.Atoi(msg.Text)
		if err == nil && rating >= 1 && rating <= 10 {
			sendMsg(AdminID, fmt.Sprintf("⭐ **Новый отзыв!**\n👤 [id%d|Игрок]\n🌟 Оценка: %d/10", userID, rating))
			sendMsg(peerID, fmt.Sprintf("🤩 Спасибо за оценку %d/10! Репорт закрыт.", rating), getMainKB())
			stateMutex.Lock()
			delete(waitingForRating, userID)
			delete(usersInReport, userID)
			stateMutex.Unlock()
		} else {
			sendMsg(peerID, "❌ Введи число от 1 до 10.", getMainKB())
		}
		return
	}

	// Режим отправки фото
	stateMutex.Lock()
	mode, isWaitingMode := waitingMode[peerID]
	stateMutex.Unlock()
	if isWaitingMode {
		handlePhotoUpload(peerID, userID, msg, mode)
		return
	}

	// Меню
	if text == "начать" || text == "start" {
		sendMsg(peerID, "Привет! Выбирай действие:", getMainKB())
	} else if strings.Contains(text, "несколько фото") {
		stateMutex.Lock()
		waitingMode[peerID] = "multi"
		stateMutex.Unlock()
		sendMsg(peerID, "📸 Отправь фото (можно альбомом)!", getMainKB())
	} else if strings.Contains(text, "загрузить фото") {
		stateMutex.Lock()
		waitingMode[peerID] = "one"
		stateMutex.Unlock()
		sendMsg(peerID, "📸 Отправь одно фото!", getMainKB())
	} else if strings.Contains(text, "статистика") {
		sendMsg(peerID, fmt.Sprintf("📊 Загружено: %d", uploads), getMainKB())
	} else if strings.Contains(text, "связь с администрацией") {
		sendMsg(peerID, "📩 Выберите способ:", getSupportKB())
	} else if strings.Contains(text, "свой вопрос") {
		stateMutex.Lock()
		waitingManualReport[userID] = true
		stateMutex.Unlock()
		sendMsg(peerID, "✍️ Напиши свой вопрос:", getMainKB())
	} else {
		sendMsg(peerID, "Выбери действие 👇", getMainKB())
	}
}

// Обработка загрузки фото
func handlePhotoUpload(peerID, userID int, msg object.MessagesMessage, mode string) {
	if len(msg.Attachments) == 0 {
		stateMutex.Lock()
		delete(waitingMode, peerID)
		stateMutex.Unlock()
		return
	}

	// Запрашиваем полное сообщение (чтобы достать все фото из альбома)
	fullMsg, err := vk.MessagesGetByID(params.NewMessagesGetByIDBuilder().MessageIDs([]int{msg.ID}).Params)
	if err != nil || len(fullMsg.Items) == 0 {
		return
	}

	attachments := fullMsg.Items[0].Attachments
	var links []string

	for _, att := range attachments {
		if att.Type == "photo" {
			sizes := att.Photo.Sizes
			links = append(links, sizes[len(sizes)-1].URL)
		} else if att.Type == "doc" {
			links = append(links, att.Doc.URL)
		}
	}

	if len(links) == 0 {
		sendMsg(peerID, "❌ Фото не найдены!", getMainKB())
		return
	}

	addUpload(userID)
	resText := ""
	if mode == "one" || len(links) == 1 {
		resText = fmt.Sprintf("🌿 **Твоя фотография загружена!**\n\n🔗 Ссылка: %s", shortenLink(links[0]))
	} else {
		resText = "🌿 **Твои фотографии загружены!**\n\n"
		for i, link := range links {
			resText += fmt.Sprintf("🔗 Фото %d: %s\n\n", i+1, shortenLink(link))
			time.Sleep(1 * time.Second) // Пауза для ВК
		}
		resText += "💾 *Скопируй ссылки в браузер.*"
	}

	sendMsg(peerID, resText, getMainKB())
	stateMutex.Lock()
	delete(waitingMode, peerID)
	stateMutex.Unlock()
}

// ===== ОБРАБОТКА ИНЛАЙН-КНОПОК =====
func handleEvent(_ context.Context, obj events.MessageEventObject) {
	payload := obj.Payload
	userID := obj.UserID
	peerID := obj.PeerID
	eventID := obj.EventID

	cmd, _ := payload["cmd"].(string)

	// Кнопки "Оценить" и "Закрыть"
	if cmd == "rate_report" {
		stateMutex.Lock()
		waitingForRating[userID] = 1 // Условный ID
		stateMutex.Unlock()
		sendMsg(peerID, "⭐ Напиши оценку от 1 до 10:", getMainKB())
		sendEventAnswer(eventID, userID, peerID, "Ожидаю оценку...")
	} else if cmd == "close_report" {
		stateMutex.Lock()
		delete(usersInReport, userID)
		stateMutex.Unlock()
		sendMsg(peerID, "✅ Ваш вопрос закрыт. Спасибо!", getMainKB())
		sendEventAnswer(eventID, userID, peerID, "Вопрос закрыт")
	}

	// Кнопки Админа
	if userID == AdminID {
		if cmd == "admin_reply" {
			targetID, _ := payload["target_id"].(float64)
			stateMutex.Lock()
			waitingManualReply[AdminID] = int(targetID)
			stateMutex.Unlock()
			sendMsg(AdminID, "✍️ Напиши ответ игроку:", getMainKB())
			sendEventAnswer(eventID, userID, peerID, "Пиши ответ...")
		} else if cmd == "admin_spam" {
			targetID, _ := payload["target_id"].(float64)
			w := addWarn(int(targetID))
			sendMsg(int(targetID), fmt.Sprintf("🚫 Репорт отклонен (Спам). Варны: %d/3", w))
			sendMsg(AdminID, "🚫 Игроку выдан варн.", getMainKB())
			sendEventAnswer(eventID, userID, peerID, "Варн выдан")
		}
	}
}

// ===== ФОНОВЫЕ ЗАДАЧИ И УТИЛИТЫ =====
func autoUnbanChecker() {
	for {
		time.Sleep(10 * time.Second)
		now := int(time.Now().Unix())
		rows, _ := db.Query("SELECT user_id FROM users WHERE ban_until > 0 AND ban_until <= ?", now)
		if rows != nil {
			for rows.Next() {
				var u int
				rows.Scan(&u)
				db.Exec("UPDATE users SET ban_until = 0 WHERE user_id = ?", u)
				sendMsg(u, "🎉 ЧС снят автоматически! Не нарушай больше.", getMainKB())
			}
			rows.Close()
		}
	}
}

func shortenLink(link string) string {
	// 1. Пробуем ВК
	res, err := vk.UtilsGetShortLink(params.NewUtilsGetShortLinkBuilder().URL(link).Params)
	if err == nil && res.ShortURL != "" {
		return strings.ReplaceAll(res.ShortURL, "https://", "")
	}
	// 2. Пробуем CLICK.RU
	resp, err := http.Get("https://clck.ru/--?url=" + url.QueryEscape(link))
	if err == nil && resp.StatusCode == 200 {
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		return strings.ReplaceAll(string(body), "https://", "")
	}
	return link
}

func sendMsg(peerID int, text string, kb interface{}) {
	b := params.NewMessagesSendBuilder()
	b.PeerID(peerID)
	b.Message(text)
	b.RandomID(rand.Int31())
	if kb != nil {
		b.Keyboard(kb)
	}
	_, err := vk.MessagesSend(b.Params)
	if err != nil {
		log.Println("Ошибка отправки:", err)
	}
}

func sendEventAnswer(eventID, userID, peerID int, text string) {
	b := params.NewMessagesSendMessageEventAnswerBuilder()
	b.EventID(eventID)
	b.UserID(userID)
	b.PeerID(peerID)
	b.EventData(fmt.Sprintf(`{"type":"show_snackbar","text":"%s"}`, text))
	vk.MessagesSendMessageEventAnswer(b.Params)
}

// ===== КЛАВИАТУРЫ =====
func getMainKB() *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(false)
	kb.AddRow().AddTextButton("📸 Загрузить фото", "positive").AddTextButton("📸 Несколько фото", "positive")
	kb.AddRow().AddTextButton("🎬 Загрузка видео", "primary").AddTextButton("📊 Статистика", "secondary")
	kb.AddRow().AddTextButton("📖 Помощь", "negative")
	return kb
}

func getSupportKB() *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(false)
	kb.AddRow().AddTextButton("📋 Выбор по шаблонам", "primary").AddTextButton("✍️ Свой вопрос", "positive")
	return kb
}

// Инлайн-клавиатура для игрока
func getRatingKB(targetID, reportID int) *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(true) // inline=true
	kb.AddRow()
	
	payloadRate := map[string]interface{}{"cmd": "rate_report", "target_id": targetID, "report_id": reportID}
	btnRate := object.NewCallbackButton("⭐ Оценить работу", payloadRate)
	btnRate.Color = "positive"
	
	payloadClose := map[string]interface{}{"cmd": "close_report", "target_id": targetID, "report_id": reportID}
	btnClose := object.NewCallbackButton("❌ Закрыть вопрос", payloadClose)
	btnClose.Color = "negative"
	
	kb.AddButton(btnRate)
	kb.AddButton(btnClose)
	return kb
}
