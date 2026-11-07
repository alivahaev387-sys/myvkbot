package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math/rand"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/SevereCloud/vksdk/v3/api"
	"github.com/SevereCloud/vksdk/v3/api/params"
	"github.com/SevereCloud/vksdk/v3/events"
	"github.com/SevereCloud/vksdk/v3/longpoll-bot"
	"github.com/SevereCloud/vksdk/v3/object"
)

const (
	Token   = "vk1.a.GPEBmYPG-udUnhJYcT_4Zo-jEKzU7VFUYVzRDNwr1wVwo_fsBabigDoS-2BW9bvMbjdYBmf-QH6dwf-ZL4dMYkKMEEiviqU5GPmM5kaG4Xt535Hb1ApvImzJkk_cq-Q7ZxOQYVPbnULj0Fg6U0yDNSPgLwANkGKX348kTlENY6s99NOBeUO-e486DAX-0XtbAa3tmQdMYjF2GLxluGvHrhFHhvr5YCuDXfYxTgw5cYo"
	AdminID = 200005093141
	GroupID = 242296265
	DBFile  = "users.json"
)

// Структура для хранения данных пользователя
type UserData struct {
	Warns    int `json:"warns"`
	BanUntil int `json:"ban_until"`
	Uploads  int `json:"uploads"`
}

var (
	vk *api.VK

	usersMutex sync.RWMutex
	users      = make(map[int]UserData)

	stateMutex         sync.Mutex
	waitingMode        = make(map[int]string)
	waitingManualReply = make(map[int]int)
	usersInReport      = make(map[int]bool)
	waitingForRating   = make(map[int]bool)
)

func main() {
	vk = api.NewVK(Token)
	loadDB()

	lp, err := longpoll.NewLongPoll(vk, GroupID)
	if err != nil {
		log.Fatal("Ошибка LongPoll: ", err)
	}

	lp.MessageNew(handleMessage)

	go autoUnbanChecker()

	log.Println("БОТ НА GO УСПЕШНО ЗАПУЩЕН! (База: JSON)")
	if err := lp.Run(); err != nil {
		log.Fatal("Ошибка запуска: ", err)
	}
}

// ===== РАБОТА С ФАЙЛОМ БАЗЫ ДАННЫХ =====
func loadDB() {
	usersMutex.Lock()
	defer usersMutex.Unlock()
	file, err := os.ReadFile(DBFile)
	if err == nil {
		json.Unmarshal(file, &users)
	}
}

func saveDB() {
	usersMutex.RLock()
	data, _ := json.MarshalIndent(users, "", "  ")
	usersMutex.RUnlock()
	os.WriteFile(DBFile, data, 0644)
}

func getUserData(userID int) (warns, banUntil, uploads int) {
	usersMutex.RLock()
	defer usersMutex.RUnlock()
	u, exists := users[userID]
	if !exists {
		return 0, 0, 0
	}
	return u.Warns, u.BanUntil, u.Uploads
}

func updateUser(userID int, warns, banUntil, uploads int) {
	usersMutex.Lock()
	users[userID] = UserData{Warns: warns, BanUntil: banUntil, Uploads: uploads}
	usersMutex.Unlock()
	saveDB()
}

func addUpload(userID int) {
	w, b, up := getUserData(userID)
	updateUser(userID, w, b, up+1)
}

func addWarn(userID int) int {
	w, b, up := getUserData(userID)
	w++
	updateUser(userID, w, b, up)
	return w
}

// ===== ОБРАБОТКА СООБЩЕНИЙ =====
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

	warns, banUntil, uploads := getUserData(userID)
	now := int(time.Now().Unix())

	if banUntil > 0 && banUntil <= now {
		updateUser(userID, warns, 0, uploads)
		sendMsg(peerID, "🎉 **ПРИВЕТСТВУЕМ СНОВА!**\n\nС вас снят ЧС.", getMainKB())
	}

	if banUntil > now {
		sendMsg(peerID, fmt.Sprintf("⛔ ВЫ В ЧС! Осталось: %d сек.", banUntil-now), nil)
		return
	}

	if userID == AdminID && (strings.Contains(text, "снять чс") || strings.Contains(text, "разбан")) {
		if msg.ReplyMessage != nil {
			target := msg.ReplyMessage.FromID
			tw, tb, tu := getUserData(target)
			updateUser(target, 0, 0, tu) // обнуляем варны и бан
			sendMsg(AdminID, fmt.Sprintf("✅ С [id%d|Игрока] снят ЧС.", target), getMainKB())
			sendMsg(target, "✅ Администратор снял с вас ЧС!", getMainKB())
			_ = tw // чтобы компилятор не ругался
			_ = tb
		} else {
			sendMsg(AdminID, "❌ Ответь на сообщение игрока командой 'разбан'.", getMainKB())
		}
		return
	}

	if userID == AdminID && text == "стата" {
		usersMutex.RLock()
		res := "📊 СТАТИСТИКА:\n\n"
		for u, data := range users {
			if data.Warns > 0 || data.BanUntil > now || data.Uploads > 0 {
				res += fmt.Sprintf("ID: %d\nВарны: %d/3\nЗагрузки: %d\n\n", u, data.Warns, data.Uploads)
			}
		}
		usersMutex.RUnlock()
		sendMsg(peerID, res, nil)
		return
	}

	if userID == AdminID {
		stateMutex.Lock()
		target, isWaiting := waitingManualReply[AdminID]
		stateMutex.Unlock()
		if isWaiting {
			playerReply := fmt.Sprintf("📩 **Вам ответил администратор** [id%d|Владелец]:\n\n💬 *%s*\n\n👇 *Выберите действие на кнопках внизу:*", AdminID, msg.Text)
			sendMsg(target, playerReply, getRatingKB())
			sendMsg(AdminID, "✅ Ответ доставлен.", getMainKB())
			stateMutex.Lock()
			delete(waitingManualReply, AdminID)
			stateMutex.Unlock()
			return
		}
	}

	stateMutex.Lock()
	isRating := waitingForRating[userID]
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
		waitingForRating[userID] = true
		stateMutex.Unlock()
		sendMsg(peerID, "⭐ Напиши оценку от 1 до 10:", getRatingKB())
	} else if strings.Contains(text, "❌ закрыть вопрос") {
		stateMutex.Lock()
		delete(usersInReport, userID)
		delete(waitingForRating, userID)
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

// ===== УТИЛИТЫ =====
func autoUnbanChecker() {
	for {
		time.Sleep(10 * time.Second)
		now := int(time.Now().Unix())
		usersMutex.Lock()
		for u, data := range users {
			if data.BanUntil > 0 && data.BanUntil <= now {
				data.BanUntil = 0
				users[u] = data
				sendMsg(u, "🎉 ЧС снят автоматически!", getMainKB())
			}
		}
		usersMutex.Unlock()
		saveDB()
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

func getRatingKB() *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(false)
	kb.AddRow()
	kb.AddTextButton("⭐ Оценить работу", nil, "positive")
	kb.AddTextButton("❌ Закрыть вопрос", nil, "negative")
	return kb
}
