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
	waitingMode        = make(map[int]string)         // peerID -> mode (multi, one, video)
	waitingForSupport  = make(map[int]bool)           // userID -> bool
	waitingManualReport = make(map[int]bool)          // userID -> bool
	waitingManualReply = make(map[int]map[string]int) // AdminID -> {"target_user": int, "report_id": int}
	usersInReport      = make(map[int]bool)           // userID -> bool
	waitingForRating   = make(map[int]int)            // userID -> report_id
	activeReports      = make(map[int]int)            // reportID -> userID
)

func main() {
	vk = api.NewVK(Token)
	loadDB()

	lp, err := longpoll.NewLongPoll(vk, GroupID)
	if err != nil {
		log.Fatal("Ошибка LongPoll: ", err)
	}

	lp.MessageNew(handleMessage)
	lp.MessageEvent(handleEvent)

	go autoUnbanChecker()

	log.Println("БОТ ЗАПУЩЕН (Умная система оценок)!")
	if err := lp.Run(); err != nil {
		log.Fatal("Ошибка запуска: ", err)
	}
}

// ===== БАЗА ДАННЫХ =====
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

	// ПИНГ
	if text == "/ping" || text == "пинг" || text == "!пинг" {
		pingMs := time.Now().UnixMilli() - int64(msg.Date)*1000
		if pingMs < 0 { pingMs = 0 }
		sendMsg(peerID, fmt.Sprintf("🏓 Понг!\n\n⚡ Скорость соединения: %d мс\n📊 Статус сети: 🟢 Отлично", pingMs), nil)
		return
	}

	// Только для ЛС
	if peerID != userID {
		return
	}

	warns, banUntil, uploads := getUserData(userID)
	now := int(time.Now().Unix())

	if banUntil > 0 && banUntil <= now {
		updateUser(userID, warns, 0, uploads)
		sendMsg(userID, "🎉 **ПРИВЕТСТВУЕМ СНОВА!** 🎉\n\nС вас был автоматически снят ЧС.\n⏳ Время наказания истекло.\n\n⚠️ **Пожалуйста, больше не нарушайте правила.**", getMainKB())
	}

	if banUntil > now {
		stateMutex.Lock()
		delete(waitingMode, peerID)
		delete(waitingForSupport, userID)
		delete(waitingManualReport, userID)
		delete(waitingForRating, userID)
		stateMutex.Unlock()

		secondsLeft := banUntil - now
		timeLeft := ""
		if secondsLeft < 60 { timeLeft = fmt.Sprintf("%d сек.", secondsLeft) } else if secondsLeft < 3600 { timeLeft = fmt.Sprintf("%d мин.", secondsLeft/60) } else if secondsLeft < 86400 { timeLeft = fmt.Sprintf("%d ч.", secondsLeft/3600) } else { timeLeft = fmt.Sprintf("%d дн.", secondsLeft/86400) }

		sendMsg(peerID, fmt.Sprintf("⛔ **ВЫ НАХОДИТЕСЬ В ЧС (ЧЕРНОМ СПИСКЕ)!**\n\nПричина: Спам / Нарушение правил.\nКто выдал: [id%d|Администратор].\nОсталось: %s\n\nБот полностью игнорирует ваши команды.", AdminID, timeLeft), nil)
		return
	}

	// АДМИН: СНЯТИЕ ЧС
	if userID == AdminID && (strings.Contains(text, "снять чс") || strings.Contains(text, "разбан")) {
		targetUser := 0
		if msg.ReplyMessage != nil {
			targetUser = msg.ReplyMessage.FromID
		} else {
			// Ищем ID в тексте
			parts := strings.Fields(text)
			for _, p := range parts {
				if strings.HasPrefix(p, "id") {
					id, _ := strconv.Atoi(strings.TrimPrefix(p, "id"))
					targetUser = id
				} else if strings.HasPrefix(p, "@id") {
					id, _ := strconv.Atoi(strings.TrimPrefix(p, "@id"))
					targetUser = id
				}
			}
		}

		if targetUser > 0 {
			tw, _, tu := getUserData(targetUser)
			updateUser(targetUser, 0, 0, tu) // Обнуляем варны и бан
			sendMsg(AdminID, fmt.Sprintf("✅ С пользователя [id%d|Игрок] успешно снят ЧС и обнулены варны!", targetUser), getMainKB())
			sendMsg(targetUser, "✅ **Администратор снял с вас ЧС и обнулил предупреждения!**", nil)
			_ = tw
		} else {
			sendMsg(AdminID, "❌ Напиши так: `Снять ЧС @id123456` (или ответь на сообщение игрока).", getMainKB())
		}
		return
	}

	// АДМИН: СТАТИСТИКА
	if userID == AdminID && text == "стата" {
		usersMutex.RLock()
		res := "📊 **Статистика:**\n\n"
		for u, data := range users {
			if data.Warns > 0 || data.BanUntil > now || data.Uploads > 0 {
				banStatus := "Нет"
				if data.BanUntil > now { banStatus = "ДА (ЧС)" }
				res += fmt.Sprintf("👤 ID: %d\n⚠️ Варны: %d/3\n📤 Загрузок: %d\n⛔ ЧС: %s\n\n", u, data.Warns, data.Uploads, banStatus)
			}
		}
		usersMutex.RUnlock()
		sendMsg(peerID, res, nil)
		return
	}

	// АДМИН: ОТВЕТ НА РЕПОРТ
	if userID == AdminID {
		stateMutex.Lock()
		replyData, isWaiting := waitingManualReply[AdminID]
		stateMutex.Unlock()
		if isWaiting {
			target := replyData["target_user"]
			reportID := replyData["report_id"]

			stateMutex.Lock()
			_, exists := activeReports[reportID]
			stateMutex.Unlock()
			if !exists {
				sendMsg(AdminID, fmt.Sprintf("❌ Ошибка: Репорт #%d уже закрыт. Ответ не отправлен.", reportID), getMainKB())
				stateMutex.Lock()
				delete(waitingManualReply, AdminID)
				stateMutex.Unlock()
				return
			}

			playerReply := fmt.Sprintf("📩 **Вам ответил администратор** [id%d|Владелец]:\n\n💬 *%s*\n\n👇 *Пожалуйста, оцените работу или закройте вопрос:*", AdminID, msg.Text)
			sendMsg(target, playerReply, getRatingKB(target, reportID))
			sendMsg(AdminID, fmt.Sprintf("✅ **Ответ доставлен игроку!**\n👤 Кому: [id%d|Игрок]\n📝 Текст: %s\n\n⏳ *Ожидаем, пока игрок закроет репорт или поставит оценку.*", target, msg.Text), getMainKB())

			stateMutex.Lock()
			delete(waitingManualReply, AdminID)
			stateMutex.Unlock()
			return
		}
	}

	// ИГРОК: ОЦЕНКА
	stateMutex.Lock()
	_, isRating := waitingForRating[userID]
	stateMutex.Unlock()
	if isRating {
		rating, err := strconv.Atoi(text)
		if err == nil && rating >= 1 && rating <= 10 {
			stateMutex.Lock()
			reportID := waitingForRating[userID]
			delete(activeReports, reportID)
			delete(usersInReport, userID)
			delete(waitingForRating, userID)
			stateMutex.Unlock()

			sendMsg(AdminID, fmt.Sprintf("⭐ **Новый отзыв!**\n\n👤 Пользователь: [id%d|Игрок]\n🌟 Оценка: %d/10\n📄 По репорту: #%d\n\n✅ Репорт успешно закрыт.", userID, rating, reportID), nil)

			userMsg := ""
			if rating <= 3 {
				userMsg = fmt.Sprintf("😔 **Спасибо за отзыв (Оценка: %d/10).**\n\nНам очень жаль, что мы не смогли решить вашу проблему идеально.\n\n🔒 *Ваше обращение закрыто.*", rating)
			} else if rating <= 7 {
				userMsg = fmt.Sprintf("🙂 **Спасибо за отзыв (Оценка: %d/10).**\n\nМы рады, что смогли вам помочь!\n\n🔒 *Ваше обращение закрыто.*", rating)
			} else {
				userMsg = fmt.Sprintf("🤩 **Огромное спасибо! (Оценка: %d/10)**\n\nМы очень рады, что вам всё понравилось!\n\n🔒 *Ваше обращение закрыто.*", rating)
			}
			sendMsg(peerID, userMsg, getMainKB())
		} else {
			sendMsg(peerID, "❌ **Ошибка:** Оценка должна быть числом от 1 до 10. Попробуйте еще раз.", getMainKB())
		}
		return
	}

	// ИГРОК: ОЖИДАНИЕ ВОПРОСА (Свой вопрос)
	stateMutex.Lock()
	isManualReport := waitingManualReport[userID]
	stateMutex.Unlock()
	if isManualReport {
		if strings.Contains(text, "назад") {
			stateMutex.Lock()
			delete(waitingManualReport, userID)
			stateMutex.Unlock()
			sendMsg(peerID, "Вы вернулись в главное меню.", getMainKB())
			return
		}
		reportID := rand.Intn(9000) + 1000
		stateMutex.Lock()
		activeReports[reportID] = userID
		usersInReport[userID] = true
		delete(waitingManualReport, userID)
		stateMutex.Unlock()

		supportText := fmt.Sprintf("🆘 **Репорт #%d**\n👤 От: [id%d|Игрок]\n\n💬 %s", reportID, userID, msg.Text)
		sendMsg(AdminID, supportText, getAdminReportKB(reportID, userID))
		sendMsg(userID, "✅ **Ваш репорт отправлен!**\n\nПожалуйста, ожидайте ответа администратора.", getMainKB())
		return
	}

	// ИГРОК: ОЖИДАНИЕ ВОПРОСА (Шаблоны)
	stateMutex.Lock()
	isSupport := waitingForSupport[userID]
	stateMutex.Unlock()
	if isSupport {
		if strings.Contains(text, "назад") {
			stateMutex.Lock()
			delete(waitingForSupport, userID)
			stateMutex.Unlock()
			sendMsg(peerID, "Вы вернулись в главное меню.", getMainKB())
			return
		}
		reportID := rand.Intn(9000) + 1000
		stateMutex.Lock()
		activeReports[reportID] = userID
		usersInReport[userID] = true
		delete(waitingForSupport, userID)
		stateMutex.Unlock()

		supportText := fmt.Sprintf("🆘 **Репорт #%d**\n👤 От: [id%d|Игрок]\n\n💬 %s", reportID, userID, msg.Text)
		sendMsg(AdminID, supportText, getAdminReportKB(reportID, userID))
		sendMsg(userID, "✅ **Ваш репорт отправлен!**\n\nПожалуйста, ожидайте ответа администратора.", getMainKB())
		return
	}

	// ОБРАБОТКА ФОТО/ВИДЕО
	stateMutex.Lock()
	mode, isWaitingMode := waitingMode[peerID]
	stateMutex.Unlock()
	if isWaitingMode {
		handlePhotoUpload(peerID, userID, msg, mode)
		return
	}

	// МЕНЮ
	if text == "начать" || text == "start" {
		sendMsg(peerID, "Привет! Выбирай действие на кнопках внизу 👇", getMainKB())
	} else if strings.Contains(text, "видео") {
		stateMutex.Lock()
		waitingMode[peerID] = "video"
		stateMutex.Unlock()
		sendMsg(peerID, "🎬 **Отправь мне видео!**", getMainKB())
	} else if strings.Contains(text, "несколько") {
		stateMutex.Lock()
		waitingMode[peerID] = "multi"
		stateMutex.Unlock()
		sendMsg(peerID, "📸 **Отправь мне несколько фото!**\n\n⚠️ *Важно: прикрепи все фото к **одному сообщению**.*", getMainKB())
	} else if strings.Contains(text, "загрузить фото") || strings.Contains(text, "создать ссылку") {
		stateMutex.Lock()
		waitingMode[peerID] = "one"
		stateMutex.Unlock()
		sendMsg(peerID, "📸 **Отправь мне фотографию, и я сделаю из неё прямую ссылку!**", getMainKB())
	} else if strings.Contains(text, "статистика") {
		sendMsg(peerID, fmt.Sprintf("📊 **Загружено:** %d", uploads), getMainKB())
	} else if strings.Contains(text, "помощь") {
		helpText := "📖 **Помощь по боту**\n\n1. Жми «Загрузить фото».\n2. Отправь картинку.\n3. Получи прямую ссылку.\n\nПо всем вопросам пиши в поддержку 👇"
		sendMsg(peerID, helpText, getHelpKB())
	} else if strings.Contains(text, "связь с администрацией") {
		stateMutex.Lock()
		inReport := usersInReport[userID]
		stateMutex.Unlock()
		if inReport {
			sendMsg(peerID, "⏳ **У вас уже есть активный репорт!**\n\nПожалуйста, дождитесь ответа.", getMainKB())
		} else {
			sendMsg(peerID, "📩 **Выберите способ обращения в поддержку:**", getChoiceKB())
		}
	} else if strings.Contains(text, "выбор по шаблонам") {
		sendMsg(peerID, "📩 **Выберите тему обращения:**", getTemplatesKB())
		stateMutex.Lock()
		waitingForSupport[userID] = true
		stateMutex.Unlock()
	} else if strings.Contains(text, "свой вопрос") {
		sendMsg(peerID, "✍️ **Напишите вашу проблему одним сообщением (или нажмите 'Назад'):**", getMainKB())
		stateMutex.Lock()
		waitingManualReport[userID] = true
		stateMutex.Unlock()
	} else if strings.Contains(text, "назад") {
		sendMsg(peerID, "Выбирай действие на кнопках внизу 👇", getMainKB())
	} else {
		sendMsg(peerID, "Выбери действие на кнопках 👇", getMainKB())
	}
}

// ===== ОБРАБОТКА ИНЛАЙН-КНОПОК =====
func handleEvent(_ context.Context, obj events.MessageEventObject) {
	var payload map[string]interface{}
	payloadBytes, _ := json.Marshal(obj.Payload)
	json.Unmarshal(payloadBytes, &payload)

	userID := obj.UserID
	peerID := obj.PeerID
	eventID := obj.EventID
	cmd, _ := payload["cmd"].(string)

	targetIDFloat, _ := payload["target_id"].(float64)
	targetUser := int(targetIDFloat)

	reportIDFloat, _ := payload["report_id"].(float64)
	reportID := int(reportIDFloat)

	// Проверка "Не ваша кнопка"
	if cmd == "rate_report" || cmd == "close_report" {
		if targetUser > 0 && userID != targetUser {
			sendEventAnswer(eventID, userID, peerID, "❌ Эта кнопка не для вас!")
			return
		}
	}

	if userID == AdminID {
		if cmd == "admin_reply" {
			stateMutex.Lock()
			_, exists := activeReports[reportID]
			stateMutex.Unlock()
			if !exists {
				sendEventAnswer(eventID, userID, peerID, "❌ Этот репорт уже закрыт!")
				return
			}
			stateMutex.Lock()
			waitingManualReply[AdminID] = map[string]int{"target_user": targetUser, "report_id": reportID}
			stateMutex.Unlock()
			sendMsg(AdminID, fmt.Sprintf("✍️ **Репорт #%d**\nНапиши текст ответа для [id%d|Игрока]:", reportID, targetUser), getMainKB())
			sendEventAnswer(eventID, userID, peerID, "Напиши ответ в чат")
			return
		} else if cmd == "admin_spam" {
			stateMutex.Lock()
			_, exists := activeReports[reportID]
			stateMutex.Unlock()
			if !exists {
				sendEventAnswer(eventID, userID, peerID, "Этот репорт уже обработан!")
				return
			}
			newWarns := addWarn(targetUser)
			if newWarns >= 3 {
				stateMutex.Lock()
				if replyData, ok := waitingManualReply[AdminID]; ok && replyData["report_id"] == reportID {
					delete(waitingManualReply, AdminID)
				}
				stateMutex.Unlock()

				sendMsg(AdminID, fmt.Sprintf("⚠️ Пользователь [id%d|Игрок] достиг лимита (3/3)!\n\nВыберите срок ЧС (бана):", targetUser), getBanTimeKB(targetUser, reportID))
				
				stateMutex.Lock()
				delete(activeReports, reportID)
				delete(usersInReport, targetUser)
				stateMutex.Unlock()

				sendEventAnswer(eventID, userID, peerID, "Выберите срок бана")
				return
			} else {
				sendMsg(AdminID, fmt.Sprintf("⚠️ Пользователь [id%d|Игрок] получил предупреждение (%d/3). Репорт #%d удален.", targetUser, newWarns, reportID), nil)
				spamText := fmt.Sprintf("🚫 **ВАШ РЕПОРТ ОТКЛОНЕН!**\n\nПричина: СПАМ.\nВаш счет: %d/3.\n⚠️ **При 3-х предупреждениях вы будете автоматически отправлены в ЧС!**\n\nКто выдал: [id%d|Администратор].", newWarns, AdminID)
				sendMsg(targetUser, spamText, nil)

				stateMutex.Lock()
				delete(activeReports, reportID)
				delete(usersInReport, targetUser)
				stateMutex.Unlock()
				sendEventAnswer(eventID, userID, peerID, "Спам обработан")
				return
			}
		} else if cmd == "set_ban" {
			timeFloat, _ := payload["time"].(float64)
			banSeconds := int(timeFloat)
			
			w, _, up := getUserData(targetUser)
			_ = w
			banUntil := int(time.Now().Unix()) + banSeconds
			updateUser(targetUser, 0, banUntil, up) // Сбрасываем варны

			banText := fmt.Sprintf("⛔ **ВЫ БЫЛИ АВТОМАТИЧЕСКИ ЗАБЛОКИРОВАНЫ!**\n\nПричина: Систематический спам (3/3).\nКто выдал: [id%d|Администратор].", AdminID)
			sendMsg(targetUser, banText, nil)
			sendMsg(AdminID, fmt.Sprintf("⛔ Пользователь [id%d|Игрок] отправлен в ЧС. Репорт закрыт.", targetUser), getMainKB())
			sendEventAnswer(eventID, userID, peerID, "Бан выдан")
			return
		} else if cmd == "cancel_ban" {
			sendMsg(AdminID, fmt.Sprintf("✅ Вы отменили бан для [id%d|Игрока].", targetUser), getMainKB())
			sendEventAnswer(eventID, userID, peerID, "Бан отменен")
			return
		}
	}

	// ОЦЕНКА ИГРОКОМ
	if cmd == "rate_report" {
		stateMutex.Lock()
		inReport := usersInReport[userID]
		stateMutex.Unlock()
		if inReport {
			stateMutex.Lock()
			waitingForRating[userID] = reportID
			stateMutex.Unlock()
			sendMsg(peerID, "⭐ **Оцените работу администратора!**\n\nПожалуйста, напишите оценку от 1 до 10 одним числом (например: 10).", getMainKB())
			sendEventAnswer(eventID, userID, peerID, "Ожидаю оценку...")
		} else {
			sendEventAnswer(eventID, userID, peerID, "Этот репорт уже закрыт!")
		}
		return
	}

	// ЗАКРЫТИЕ ИГРОКОМ
	if cmd == "close_report" {
		stateMutex.Lock()
		inReport := usersInReport[userID]
		stateMutex.Unlock()
		if inReport {
			stateMutex.Lock()
			delete(activeReports, reportID)
			delete(usersInReport, userID)
			delete(waitingForRating, userID)
			stateMutex.Unlock()

			sendMsg(peerID, "✅ **Ваш вопрос успешно закрыт!**\n\nСпасибо за обращение! Если что-то ещё понадобится, мы всегда на связи 👇", getMainKB())
			sendMsg(AdminID, fmt.Sprintf("🔒 Игрок [id%d|Игрок] самостоятельно закрыл репорт #%d.", userID, reportID), nil)
			sendEventAnswer(eventID, userID, peerID, "Вопрос закрыт")
		} else {
			sendEventAnswer(eventID, userID, peerID, "Этот репорт уже закрыт!")
		}
		return
	}
}

// ===== ОБРАБОТКА ФОТО =====
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
	isVideo, isPhoto := false, false

	for _, att := range attachments {
		if att.Type == "photo" {
			isPhoto = true
			sizes := att.Photo.Sizes
			if len(sizes) > 0 {
				links = append(links, sizes[len(sizes)-1].URL)
			}
		} else if att.Type == "doc" {
			isPhoto = true
			links = append(links, att.Doc.URL)
		} else if att.Type == "video" {
			isVideo = true
			links = append(links, fmt.Sprintf("https://vk.com/video%d_%d", att.Video.OwnerID, att.Video.ID))
		}
	}

	if mode == "video" {
		if isPhoto && !isVideo {
			sendMsg(peerID, "❌ **Это не видео!**", getMainKB())
		} else if isVideo && len(links) > 0 {
			addUpload(userID)
			shortLink := shortenLink(links[0])
			sendMsg(peerID, fmt.Sprintf("🎬 **Ссылка:**\n%s", shortLink), getMainKB())
		} else {
			sendMsg(peerID, "❌ Отправь видео!", getMainKB())
		}
		stateMutex.Lock()
		delete(waitingMode, peerID)
		stateMutex.Unlock()
		return
	}

	if len(links) == 0 {
		sendMsg(peerID, "❌ Фото не найдены!", getMainKB())
		return
	}

	addUpload(userID)
	resText := ""

	if mode == "one" || len(links) == 1 {
		shortLink := shortenLink(links[0])
		resText = fmt.Sprintf("🌿 **Твоя фотография загружена!**\n\n🔗 Ссылка: %s\n\n💾 **Как сохранить:**\n1. Скопируй ссылку.\n2. Вставь её в браузер (Safari).\n3. Зажми картинку и выбери «Сохранить».", shortLink)
	} else {
		resText = "🌿 **Твои фотографии загружены!**\n\n"
		for i, link := range links {
			shortLink := shortenLink(link)
			resText += fmt.Sprintf("🔗 Фото %d: %s\n\n", i+1, shortLink)
			time.Sleep(1 * time.Second)
		}
		resText += "💾 *Скопируй ссылки и открой в браузере.*"
	}

	sendMsg(peerID, resText, getMainKB())
	stateMutex.Lock()
	delete(waitingMode, peerID)
	stateMutex.Unlock()
}

// ===== ФОНОВЫЙ ПРОЦЕСС =====
func autoUnbanChecker() {
	for {
		time.Sleep(5 * time.Second)
		now := int(time.Now().Unix())
		var toUnban []int

		usersMutex.Lock()
		for u, data := range users {
			if data.BanUntil > 0 && data.BanUntil <= now {
				data.BanUntil = 0
				users[u] = data
				toUnban = append(toUnban, u)
			}
		}
		usersMutex.Unlock()

		if len(toUnban) > 0 {
			saveDB()
			for _, u := range toUnban {
				unbanText := "🎉 **ПРИВЕТСТВУЕМ СНОВА!** 🎉\n\nС вас был автоматически снят ЧС (Черный список).\n⏳ Время наказания истекло.\n\n⚠️ **Пожалуйста, больше не нарушайте правила.**"
				sendMsg(u, unbanText, getMainKB())
			}
		}
	}
}

// ===== УТИЛИТЫ =====
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

func sendEventAnswer(eventID string, userID, peerID int, text string) {
	b := params.NewMessagesSendMessageEventAnswerBuilder()
	b.EventID(eventID)
	b.UserID(userID)
	b.PeerID(peerID)
	b.EventData(fmt.Sprintf(`{"type":"show_snackbar","text":"%s"}`, text))
	vk.MessagesSendMessageEventAnswer(b.Params)
}

// ===== КЛАВИАТУРЫ =====
var emptyPayload = make(map[string]interface{})

func getMainKB() *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(false)
	kb.AddRow().AddTextButton("📸 Загрузить фото", emptyPayload, "positive").AddTextButton("📸 Несколько фото", emptyPayload, "positive")
	kb.AddRow().AddTextButton("🎬 Загрузка видео", emptyPayload, "primary").AddTextButton("📊 Статистика", emptyPayload, "secondary")
	kb.AddRow().AddTextButton("📖 Помощь", emptyPayload, "negative")
	return kb
}

func getHelpKB() *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(false)
	kb.AddRow().AddTextButton("📩 Связь с администрацией", emptyPayload, "primary")
	kb.AddRow().AddTextButton("⬅️ Назад", emptyPayload, "secondary")
	return kb
}

func getChoiceKB() *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(false)
	kb.AddRow().AddTextButton("📋 Выбор по шаблонам", emptyPayload, "primary").AddTextButton("✍️ Свой вопрос", emptyPayload, "positive")
	kb.AddRow().AddTextButton("⬅️ Назад", emptyPayload, "secondary")
	return kb
}

func getTemplatesKB() *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(false)
	kb.AddRow().AddTextButton("❌ Фото не загрузилось", emptyPayload, "secondary").AddTextButton("❌ Ссылка не открывается", emptyPayload, "secondary")
	kb.AddRow().AddTextButton("❌ Видео не скачивается", emptyPayload, "secondary").AddTextButton("❌ На iPhone не сохраняется", emptyPayload, "secondary")
	kb.AddRow().AddTextButton("⬅️ Назад", emptyPayload, "secondary")
	return kb
}

// ИНЛАЙН-КНОПКИ
func getAdminReportKB(reportID, targetUserID int) *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(true)
	kb.AddRow()
	pReply := map[string]interface{}{"cmd": "admin_reply", "report_id": reportID, "target_id": targetUserID}
	pSpam := map[string]interface{}{"cmd": "admin_spam", "report_id": reportID, "target_id": targetUserID}
	kb.AddCallbackButton("✍️ Ответить", pReply, "positive")
	kb.AddCallbackButton("🚫 Спам", pSpam, "negative")
	return kb
}

func getRatingKB(targetUserID, reportID int) *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(true)
	kb.AddRow()
	pRate := map[string]interface{}{"cmd": "rate_report", "report_id": reportID, "target_id": targetUserID}
	pClose := map[string]interface{}{"cmd": "close_report", "report_id": reportID, "target_id": targetUserID}
	kb.AddCallbackButton("⭐ Оценить работу", pRate, "positive")
	kb.AddCallbackButton("❌ Закрыть вопрос", pClose, "negative")
	return kb
}

func getBanTimeKB(targetUser, reportID int) *object.MessagesKeyboard {
	kb := object.NewMessagesKeyboard(true)
	kb.AddRow()
	p1 := map[string]interface{}{"cmd": "set_ban", "target_id": targetUser, "report_id": reportID, "time": 60}
	p2 := map[string]interface{}{"cmd": "set_ban", "target_id": targetUser, "report_id": reportID, "time": 3600}
	kb.AddCallbackButton("1 Мин", p1, "secondary")
	kb.AddCallbackButton("1 Час", p2, "primary")
	
	kb.AddRow()
	p3 := map[string]interface{}{"cmd": "set_ban", "target_id": targetUser, "report_id": reportID, "time": 86400}
	p4 := map[string]interface{}{"cmd": "set_ban", "target_id": targetUser, "report_id": reportID, "time": 604800}
	kb.AddCallbackButton("1 День", p3, "primary")
	kb.AddCallbackButton("7 Дней", p4, "negative")
	
	kb.AddRow()
	p5 := map[string]interface{}{"cmd": "cancel_ban", "target_id": targetUser, "report_id": reportID}
	kb.AddCallbackButton("❌ Отмена (Разбан)", p5, "secondary")
	return kb
}
