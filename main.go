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

const (
	Token   = "vk1.a.GPEBmYPG-udUnhJYcT_4Zo-jEKzU7VFUYVzRDNwr1wVwo_fsBabigDoS-2BW9bvMbjdYBmf-QH6dwf-ZL4dMYkKMEEiviqU5GPmM5kaG4Xt535Hb1ApvImzJkk_cq-Q7ZxOQYVPbnULj0Fg6U0yDNSPgLwANkGKX348kTlENY6s99NOBeUO-e486DAX-0XtbAa3tmQdMYjF2GLxluGvHrhFHhvr5YCuDXfYxTgw5cYo"
	AdminID = 200005093141
	GroupID = 242296265
)

var (
	vk *api.VK
	db *sql.DB

	stateMutex          sync.Mutex
	waitingMode         = make(map[int]string)
	waitingManualReply  = make(map[int]int)
	usersInReport       = make(map[int]bool)
	waitingForRating    = make(map[int]int)
)

func main() {
	vk = api.NewVK(Token)
	initDB()

	lp, err := longpoll.NewLongPoll(vk, GroupID)
	if err != nil {
		log.Fatal("Ошибка LongPoll: ", err)
	}

	lp.MessageNew(handleMessage)

	go autoUnbanChecker()

	log.Println("БОТ НА GO УСПЕШНО ЗАПУЩЕН!")
	if err := lp.Run(); err != nil {
		log.Fatal("Ошибка запуска: ", err)
	}
}

func initDB() {
	var err error
	db, err = sql.Open("sqlite", "super_bot.db")
	if err != nil {
		log.Fatal(err)
	}
	db.Exec("PRAGMA journal_mode=WAL;")
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

func handleMessage(_ context.Context, obj events.MessageNewObject) {
	msg := obj.Message
	peerID := msg.PeerID
	userID := msg.FromID
	text := strings.ToLower(strings.TrimSpace(strings.ReplaceAll(msg.Text, "@club242296265", "")))

	if text == "/ping" || text == "пинг" || text == "!пинг" {
		pingMs := time.Now().UnixMilli() - int64(msg.Date)*1000
		if pingMs < 0 { pingMs = 0 }
		sendMsg(peerID, fmt.Sprintf("🏓 Понг!\n\n⚡ Скорость: %d мс\n📊 Статус: 🟢 Отлично", pingMs), nil)
		return
	}

	if peerID != userID {
		return
	}

	_, banUntil, uploads := getUserData(userID)
	now := int(time.Now().Unix())

	if banUntil > 0 && banUntil <= now {
		db.Exec("UPDATE users SET ban_until = 0 WHERE user_id = ?", userID)
		sendMsg(peerID, "🎉 **ПРИВЕТСТВУЕМ СНОВА!**\n\nС вас снят ЧС.", getMainKB())
	}

	if banUntil > now {
		sendMsg(peerID, fmt.Sprintf("⛔ ВЫ В ЧС! Осталось: %d сек.", banUntil-now), nil)
		return
	}

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

	if userID == AdminID {
		stateMutex.Lock()
		target, isWaiting := waitingManualReply[AdminID]
		stateMutex.Unlock()
		if isWaiting {
			playerReply := fmt.Sprintf("📩 **Вам ответил администратор** [id%d|Владелец]:\n\n💬 *%s*\n\n👇 *Пожалуйста, выберите действие на кнопках внизу:*", AdminID, msg.Text)
			sendMsg(target, playerReply, getRatingKB())
			sendMsg(AdminID, "✅ Ответ доставлен.", getMainKB())
			stateMutex.Lock()
			delete(waitingManualReply, AdminID)
			stateMutex.Unlock()
			return
		}
	}

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
			sendMsg(peerID, "❌ Введи число от 1 до 10.", getRatingKB())
		}
		return
	}

	stateMutex.Lock()
	mode, isWaitingMode := waitingMode[peerID]
	stateMutex.Unlock()
	if isWaitingMode {
		handlePhotoUpload(peerID, userID, msg, mode)
		return
	}

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
		waitingManualReply[userID] = userID
		stateMutex.Unlock()
		sendMsg(peerID, "✍️ Напиши свой вопрос:", getMainKB())
	} else if strings.Contains(text, "⭐ оценить работу") {
		stateMutex.Lock()
		waitingForRating[userID] = 1
		stateMutex.Unlock()
		sendMsg(peerID, "⭐ Напиши оценку от 1 до 10:", getRatingKB())
	} else if strings.Contains(text, "❌ закрыть вопрос") {
		stateMutex.Lock()
		delete(usersInReport, userID)
		stateMutex.Unlock()
		sendMsg(peerID, "✅ Ваш вопрос закрыт. Спасибо!", getMainKB())
	} else {
		sendMsg(peerID, "Выбери действие 👇", getMainKB())
	}
}

func handlePhotoUpload(peerID, userID int, msg object.MessagesMessage, mode string) {
	if len(msg.Attachments) == 0 {
		stateMutex.Lock()
		delete(waitingMode, peerID)
		stateMutex.Unlock()
		return
	}

	fullMsg, err := vk.MessagesGetByID(params.NewMessagesGetByIDBuilder().MessageIDs([]int{msg.ID}).Params)
	if err != nil || len(fullMsg.Items) == 0 {
		log.Println("Ошибка getById:", err)
		return
	}

	attachments := fullMsg.Items[0].Attachments
	var links []string

	for _, att := range attachments {
		if att.Type == "photo" {
			sizes := att.Photo.Sizes
			if len(sizes) > 0 {
				links = append(links, sizes[len(sizes)-1].URL)
			}
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
			time.Sleep(1 * time.Second)
		}
		resText += "💾 *Скопируй ссылки в браузер.*"
	}

	sendMsg(peerID, resText, getMainKB())
	stateMutex.Lock()
	delete(waitingMode, peerID)
	stateMutex.Unlock()
}

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
				sendMsg(u, "🎉 ЧС снят автоматически!", getMainKB())
			}
			rows.Close()
		}
	}
}

func shortenLink(link string) string {
	res, err := vk.UtilsGetShortLink(params.NewUtilsGetShortLinkBuilder().URL(link).Params)
	if err == nil && res.ShortURL != "" {
		return strings.ReplaceAll(res.ShortURL, "https://", "")
	}
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
	b.RandomID(int(rand.Int31()))
	if kb != nil {
		b.Keyboard(kb)
	}
	_, err := vk.MessagesSend(b.Params)
	if err != nil {
		log.Println("Ошибка отправки:", err)
	}
}

// ===== ИСПРАВЛЕННЫЕ КЛАВИАТУРЫ =====
// В этой версии библиотеки вторым аргументом идет payload, а третьим — цвет.

func getMainKB() *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(false)
	kb.AddRow().AddTextButton("📸 Загрузить фото", nil, "positive").AddTextButton("📸 Несколько фото", nil, "positive")
	kb.AddRow().AddTextButton("🎬 Загрузка видео", nil, "primary").AddTextButton("📊 Статистика", nil, "secondary")
	kb.AddRow().AddTextButton("📖 Помощь", nil, "negative")
	return kb
}

func getSupportKB() *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(false)
	kb.AddRow().AddTextButton("📋 Выбор по шаблонам", nil, "primary").AddTextButton("✍️ Свой вопрос", nil, "positive")
	return kb
}

// Новая клавиатура для оценки — обычные текстовые кнопки
func getRatingKB() *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(false)
	kb.AddRow()
	kb.AddTextButton("⭐ Оценить работу", nil, "positive")
	kb.AddTextButton("❌ Закрыть вопрос", nil, "negative")
	return kb
}
