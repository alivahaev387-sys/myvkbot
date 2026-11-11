const { VK, Keyboard } = require('vk-io');
const sqlite3 = require('sqlite3').verbose();
const fs = require('fs');
const path = require('path');

console.log("=========================================");
console.log("ВЕРСИЯ NODE.JS:", process.version);
console.log("=========================================");

// ===== НАСТРОЙКИ =====
const TOKEN = "vk1.a.BvMZnZvhxLsOu5bIQ1IUIIoYMEW3T88NqEAcRZ17Yj-T46O-viFXkUPWky-4XBwNZAKsWhcwqAt3TDMqQmcKva0ckucYDEUvFKa_p_LJ9ig-zNIPv7cHSZV9KP4S8XLgO0m32YWDLuqfz-rqgrrhoFKZ0mexTvf71NQ5G1JVI0H7QtuL4HGdtQkAvT7Up8xnC-vaO3QTue9x8V5a3u1-DuwMwEXIvfB4OgnVo0_FXGI";
const GROUP_ID = 243089386;
const ADMIN_ID = 200005093141;
const BONUS_CD = 600; 
const FORTUNA_CD = 600;

const vk = new VK({ 
    token: TOKEN, 
    apiVersion: '5.131',
    pollingGroupId: GROUP_ID 
});

const DATA_DIR = './data';
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR);
const DB_FILE = path.join(DATA_DIR, 'game.db');

// ===== БАЗА ДАННЫХ =====
const db = new sqlite3.Database(DB_FILE);
const dbRun = (query, params = []) => new Promise((res, rej) => db.run(query, params, function(e) { e ? rej(e) : res(this); }));
const dbGet = (query, params = []) => new Promise((res, rej) => db.get(query, params, (e, r) => e ? rej(e) : res(r)));
const dbAll = (query, params = []) => new Promise((res, rej) => db.all(query, params, (e, r) => e ? rej(e) : res(r)));

async function initDB() {
    await dbRun("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, balance INTEGER DEFAULT 1000)");
    await dbRun("CREATE TABLE IF NOT EXISTS active_duels (msg_id TEXT PRIMARY KEY, challenger TEXT, bet INTEGER, peer_id TEXT)");
    await dbRun("CREATE TABLE IF NOT EXISTS bonus_cd (user_id TEXT PRIMARY KEY, last_used INTEGER)");
    await dbRun("CREATE TABLE IF NOT EXISTS fortune_cd (user_id TEXT PRIMARY KEY, last_used INTEGER)");
    await dbRun("CREATE TABLE IF NOT EXISTS promos (code TEXT PRIMARY KEY, amount INTEGER, limit_count INTEGER, used_by TEXT DEFAULT '')");
    await dbRun("CREATE TABLE IF NOT EXISTS games (game_id TEXT PRIMARY KEY, user_id TEXT, bet INTEGER, mines TEXT, opened TEXT, multiplier REAL)");
    // П.1: Добавлена таблица для ЧС
    await dbRun("CREATE TABLE IF NOT EXISTS blacklist (user_id TEXT PRIMARY KEY, reason TEXT)");
    console.log("--- БАЗА ДАННЫХ ГОТОВА ---");
}
initDB();

// ===== ХЕЛПЕРЫ =====
async function getBalance(userId) {
    const row = await dbGet("SELECT balance FROM users WHERE user_id = ?", [String(userId)]);
    if (!row) {
        await dbRun("INSERT INTO users (user_id, balance) VALUES (?, 1000)", [String(userId)]);
        return 1000;
    }
    return row.balance;
}

async function updateBalance(userId, amount) {
    const bal = await getBalance(userId);
    await dbRun("UPDATE users SET balance = ? WHERE user_id = ?", [bal + amount, String(userId)]);
}

async function getFullName(userId) {
    try {
        const [user] = await vk.api.users.get({ user_ids: userId });
        return `[id${userId}|${user.first_name} ${user.last_name || ''}]`;
    } catch { return `Игрок`; }
}

function formatMoney(num) { return num.toLocaleString('ru-RU'); }

// ===== КЛАВИАТУРЫ =====
const mainKb = Keyboard.builder()
    .textButton({ label: '💼 Работа', payload: 'work', color: Keyboard.POSITIVE_COLOR })
    .textButton({ label: '🎰 Рулетка', payload: 'roulette', color: Keyboard.PRIMARY_COLOR })
    .row()
    .textButton({ label: '👤 Профиль', payload: 'profile', color: Keyboard.SECONDARY_COLOR })
    .textButton({ label: '🏆 Топ', payload: 'top', color: Keyboard.SECONDARY_COLOR });

const getDuelKb = (duelId) => Keyboard.builder().inline().callbackButton({
    label: '⚔️ Сразиться',
    payload: { cmd: 'duel_accept', duel_id: duelId },
    color: Keyboard.POSITIVE_COLOR
}).toString();

const getMinesCountKb = (gameId) => {
    const kb = Keyboard.builder().inline();
    let count = 0;
    for (let i = 2; i <= 8; i++) {
        kb.callbackButton({ label: `${i} 💣`, payload: { cmd: 'mines_set', gameId: String(gameId), count: String(i) }, color: Keyboard.SECONDARY_COLOR });
        count++;
        if (count % 4 === 0 && i !== 8) kb.row();
    }
    return kb.toString();
};

const getMinesFieldKb = (gameId, opened, mines, isGameOver = false) => {
    const kb = Keyboard.builder().inline();
    for (let i = 1; i <= 9; i++) {
        if (opened.includes(i)) {
            kb.callbackButton({ 
                label: mines.includes(i) ? '💥' : '💎', 
                payload: { cmd: 'none' }, 
                color: mines.includes(i) ? Keyboard.NEGATIVE_COLOR : Keyboard.POSITIVE_COLOR 
            });
        } else {
            kb.callbackButton({ 
                label: String(i), 
                payload: isGameOver ? { cmd: 'none' } : { cmd: 'mines_click', gameId: String(gameId), cell: String(i) }, 
                color: Keyboard.SECONDARY_COLOR 
            });
        }
        if (i % 3 === 0) kb.row();
    }
    
    if (!isGameOver) {
        kb.callbackButton({ label: '💰 Забрать', payload: { cmd: 'mines_cashout', gameId: String(gameId) }, color: Keyboard.POSITIVE_COLOR });
    }
    
    return kb.toString();
};

// ===== ОБРАБОТКА СООБЩЕНИЙ =====
vk.updates.on('message_new', async (message) => {
    if (message.isOutbox) return;
    if (message.senderId < 0) return;

    try {
        const text = message.text ? message.text.trim().toLowerCase() : '';
        if (!text) return;

        // Проверка на ЧС (только если человек пытается использовать команду)
        if (text.startsWith('/')) {
            const isBlacklisted = await dbGet("SELECT reason FROM blacklist WHERE user_id = ?", [String(message.senderId)]);
            if (isBlacklisted) {
                return await message.reply(`🚫 **Доступ запрещен!**\n\nВы находитесь в черном списке бота.\n📝 **Причина:** ${isBlacklisted.reason}\n\nЕсли вы считаете, что это ошибка, обратитесь к владельцу.`, { disable_mentions: 1 });
            }
        }

        if (!text.startsWith('/') && text !== '💼 работа') return;

        const cleanText = text.replace(/\//g, '').trim();
        const parts = cleanText.split(/\s+/);
        const userId = message.senderId;
        const peerId = message.peerId;
        const isLs = peerId === userId;

        const balance = await getBalance(userId);

        const replyParams = (kb = undefined) => {
            const p = { disable_mentions: 1 };
            if (kb) p.keyboard = kb;
            return p;
        };

        // --- КОМАНДЫ ---
        if (text.includes('начать') || text.includes('start')) {
            return await message.reply("👋 Привет! Я игровой бот. Выбирай действие на клавиатуре или напиши /help.", replyParams(isLs ? mainKb : undefined));
        }

        if (text.includes('help') || text.includes('помощь') || text.includes('команды')) {
            const helpText = "📖 Команды:\n🎰 /рулетка [цвет/чет] [ставка]\n🎲 /фортуна (100$)\n💣 /мины [ставка]\n⚔️ /duel [сумма]\n💸 /transfer [сумма] (ответом на сообщение)\n🎁 /бонус\n🎁 /promo [код]\n📜 /промолист\n👤 /профиль\n🏆 /топ";
            return await message.reply(helpText, replyParams(isLs ? mainKb : undefined));
        }

        if (text === '💼 работа') {
            const earned = Math.floor(Math.random() * 400) + 100;
            await updateBalance(userId, earned);
            return await message.reply(`✅ Ты заработал ${earned}$!\n💰 Баланс: ${formatMoney(await getBalance(userId))}$`, replyParams(isLs ? mainKb : undefined));
        }

        if (cleanText === 'профиль' || cleanText === 'баланс') {
            return await message.reply(`👤 Профиль:\n💰 Баланс: ${formatMoney(balance)}$\n🆔 ID: ${userId}`, replyParams(isLs ? mainKb : undefined));
        }

        if (cleanText === 'топ') {
            const rows = await dbAll("SELECT user_id, balance FROM users WHERE balance > 2 ORDER BY balance DESC LIMIT 20");
            if (rows.length === 0) return await message.reply("🏆 Топ пуст.", replyParams(isLs ? mainKb : undefined));

            const userIds = rows.map(r => r.user_id);
            let usersInfo = [];
            try { usersInfo = await vk.api.users.get({ user_ids: userIds.join(','), fields: 'deactivated' }); } catch (e) {}

            let topText = "🏆 Топ 10 богачей:\n\n";
            let count = 0;
            for (const r of rows) {
                if (count >= 10) break;
                const uInfo = usersInfo.find(u => u.id == r.user_id);
                if (uInfo && !uInfo.deactivated) {
                    count++;
                    topText += `${count}. [id${uInfo.id}|${uInfo.first_name} ${uInfo.last_name || ''}] — ${formatMoney(r.balance)}$\n`;
                }
            }
            return await message.reply(topText, replyParams(isLs ? mainKb : undefined));
        }

        if (cleanText.startsWith('рулетка') || cleanText.startsWith('рул')) {
            if (parts.length >= 3) {
                const choice = parts[1];
                const betStr = parts[parts.length - 1];
                let bet = ['вб', 'всё', 'все'].includes(betStr) ? balance : parseInt(betStr);

                if (isNaN(bet) || bet < 10 || bet > balance) return await message.reply(`❌ Мин. ставка 10, у тебя ${formatMoney(balance)}$`, replyParams());

                const res = Math.floor(Math.random() * 37);
                const redNumbers = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36];
                
                let cName = redNumbers.includes(res) ? "Красное" : (res === 0 ? "Зеро" : "Черное");
                let cEmoji = redNumbers.includes(res) ? "🔴" : (res === 0 ? "🟢" : "⚫");
                let eName = res === 0 ? "Ноль" : (res % 2 === 0 ? "Четное" : "Нечетное");

                let win = (parseInt(choice) === res) || 
                          (["красное", "красный", "кр"].includes(choice) && redNumbers.includes(res)) ||
                          (["черное", "черный", "чр"].includes(choice) && !redNumbers.includes(res) && res !== 0) ||
                          (["чет", "четное"].includes(choice) && res % 2 === 0 && res !== 0) ||
                          (["нечет", "нечетное"].includes(choice) && res % 2 !== 0);

                if (win) {
                    await updateBalance(userId, bet);
                    return await message.reply(`🎰 Выпало: ${res} ${cEmoji} (${cName}, ${eName})\n\n✅ Выигрыш: +${bet}$\n💰 Баланс: ${formatMoney(await getBalance(userId))}$`, replyParams(isLs ? mainKb : undefined));
                } else {
                    await updateBalance(userId, -bet);
                    return await message.reply(`🎰 Выпало: ${res} ${cEmoji} (${cName}, ${eName})\n\n😔 Проигрыш: -${bet}$\n💰 Баланс: ${formatMoney(await getBalance(userId))}$`, replyParams(isLs ? mainKb : undefined));
                }
            } else {
                return await message.reply("❌ Формат: /рулетка красное 500", replyParams());
            }
        }

        if (cleanText === 'фортуна') {
            const currentTime = Math.floor(Date.now() / 1000);
            const row = await dbGet("SELECT last_used FROM fortune_cd WHERE user_id = ?", [String(userId)]);
            const lastUse = row ? row.last_used : 0;

            if (currentTime - lastUse < FORTUNA_CD) {
                const remaining = FORTUNA_CD - (currentTime - lastUse);
                return await message.reply(`⏳ Фортуна доступна через ${Math.floor(remaining / 60)} мин. ${remaining % 60} сек.`, replyParams());
            }
            if (balance < 100) return await message.reply("❌ Фортуна стоит 100$.", replyParams());

            await updateBalance(userId, -100);
            await dbRun("REPLACE INTO fortune_cd (user_id, last_used) VALUES (?, ?)", [String(userId), currentTime]);

            const prize = [0, 50, 100, 200, 500, 1000, 5000][Math.floor(Math.random() * 7)];
            await updateBalance(userId, prize);
            
            return await message.reply(`🎰 Выпало: ${formatMoney(prize)}$!\n💰 Баланс: ${formatMoney(await getBalance(userId))}$`, replyParams(isLs ? mainKb : undefined));
        }

        if (cleanText.startsWith('мины')) {
            let bet = 100;
            if (parts.length >= 2) {
                if (['все', 'вб', 'всё'].includes(parts[1])) bet = balance;
                else if (!isNaN(parts[1])) bet = parseInt(parts[1]);
            }

            if (bet < 10 || bet > balance) return await message.reply(`❌ Мин. ставка 10, у тебя ${formatMoney(balance)}$`, replyParams());

            const gameId = String(Math.floor(Math.random() * 90000) + 10000);
            await dbRun("INSERT INTO games (game_id, user_id, bet, mines, opened, multiplier) VALUES (?, ?, ?, '[]', '[]', 1.0)", [gameId, String(userId), bet]);

            return await message.reply(`💣 Мины\nСтавка: ${bet}$\n\nВыберите количество мин (2-8):`, replyParams(getMinesCountKb(gameId)));
        }

        if (cleanText.startsWith('transfer') || cleanText.startsWith('перевод')) {
            if (parts.length >= 2 && !isNaN(parts[1]) && message.hasReplyMessage) {
                const amount = parseInt(parts[1]);
                const targetId = message.replyMessage.senderId;

                if (targetId === userId) return await message.reply("❌ Нельзя перевести деньги самому себе.", replyParams());
                if (targetId < 0) return await message.reply("❌ Нельзя переводить сообществам.", replyParams());
                if (amount < 50 || amount > 5000000) return await message.reply("❌ Сумма перевода должна быть от 50 до 5 000 000$", replyParams());
                if (balance < amount) return await message.reply("❌ У тебя недостаточно средств.", replyParams());

                await updateBalance(userId, -amount);
                await updateBalance(targetId, amount);

                const targetName = await getFullName(targetId);
                return await message.reply(`💸 Ты успешно перевел ${formatMoney(amount)}$ игроку ${targetName}.\n💰 Твой баланс: ${formatMoney(await getBalance(userId))}$`, replyParams());
            } else {
                return await message.reply("❌ Формат: /transfer [сумма] (ответом на сообщение)", replyParams());
            }
        }

        if (cleanText.startsWith('duel')) {
            if (parts.length === 2 && !isNaN(parts[1])) {
                const bet = parseInt(parts[1]);
                if (bet < 50 || bet > 2000) return await message.reply("❌ Ставка от 50 до 2000.", replyParams());
                if (balance < bet) return await message.reply("❌ Не хватает монет.", replyParams());

                const duelId = String(Math.floor(Math.random() * 90000) + 10000);
                await dbRun("REPLACE INTO active_duels (msg_id, challenger, bet, peer_id) VALUES (?, ?, ?, ?)", [duelId, String(userId), bet, String(peerId)]);

                return await message.reply(`⚔️ Дуэль!\n👤 Создатель: ${await getFullName(userId)}\n💰 Ставка: ${bet}$\n\n⚡ Нажми кнопку ниже!`, replyParams(getDuelKb(duelId)));
            } else {
                return await message.reply("❌ Формат: /duel [сумма]", replyParams());
            }
        }

        if (cleanText === 'бонус') {
            const currentTime = Math.floor(Date.now() / 1000);
            const row = await dbGet("SELECT last_used FROM bonus_cd WHERE user_id = ?", [String(userId)]);
            const lastUse = row ? row.last_used : 0;

            if (currentTime - lastUse < BONUS_CD) {
                const remaining = BONUS_CD - (currentTime - lastUse);
                return await message.reply(`⏳ Бонус доступен через ${Math.floor(remaining / 60)} мин. ${remaining % 60} сек.`, replyParams());
            }

            const bonusAmount = [100000, 200000, 500000][Math.floor(Math.random() * 3)];
            await updateBalance(userId, bonusAmount);
            await dbRun("REPLACE INTO bonus_cd (user_id, last_used) VALUES (?, ?)", [String(userId), currentTime]);
            
            return await message.reply(`🎁 Бонус получен! ✨\n+${formatMoney(bonusAmount)}$\n💰 Баланс: ${formatMoney(await getBalance(userId))}$`, replyParams(isLs ? mainKb : undefined));
        }

        // ===== АДМИНСКИЕ КОМАНДЫ =====
        if (userId === ADMIN_ID) {
            // П.2: Команда ЧС
            if (cleanText.startsWith('чсб')) {
                if (!message.hasReplyMessage) {
                    return await message.reply("❌ Ответьте (реплаем) на сообщение пользователя, которого хотите занести в ЧС.", replyParams());
                }
                const targetId = message.replyMessage.senderId;
                if (targetId === ADMIN_ID) return await message.reply("❌ Вы не можете занести себя в ЧС.", replyParams());
                
                // Получаем причину из команды (всё, что после "чсб")
                const reason = parts.slice(1).join(' ') || 'Без указания причины';
                
                await dbRun("REPLACE INTO blacklist (user_id, reason) VALUES (?, ?)", [String(targetId), reason]);
                const targetName = await getFullName(targetId);
                return await message.reply(`✅ Пользователь ${targetName} успешно занесен в ЧС бота.\n📝 Причина: ${reason}`, replyParams());
            }

            // Бонус: Разбан
            if (cleanText.startsWith('разчсб')) {
                if (!message.hasReplyMessage) {
                    return await message.reply("❌ Ответьте на сообщение пользователя, которого хотите разбанить.", replyParams());
                }
                const targetId = message.replyMessage.senderId;
                await dbRun("DELETE FROM blacklist WHERE user_id = ?", [String(targetId)]);
                const targetName = await getFullName(targetId);
                return await message.reply(`✅ Пользователь ${targetName} успешно удален из ЧС бота.`, replyParams());
            }

            if (cleanText === 'cp') {
                await dbRun("DELETE FROM promos");
                return await message.reply("✅ Все активные промокоды были успешно удалены.", replyParams());
            }

            if (cleanText.startsWith('деньги')) {
                if (parts.length === 2 && !isNaN(parts[1]) && message.hasReplyMessage) {
                    const amount = parseInt(parts[1]);
                    const targetId = message.replyMessage.senderId;
                    await updateBalance(targetId, amount);
                    return await message.reply(`💰 Владелец выдал ${formatMoney(amount)}$ игроку ${await getFullName(targetId)}!`, replyParams());
                } else {
                    return await message.reply("❌ Формат: /деньги [сумма] (ответом на сообщение)", replyParams());
                }
            }

            if (cleanText.startsWith('создать')) {
                if (parts.length === 4 && !isNaN(parts[2]) && !isNaN(parts[3])) {
                    await dbRun("REPLACE INTO promos (code, amount, limit_count, used_by) VALUES (?, ?, ?, '')", [parts[1], parseInt(parts[2]), parseInt(parts[3])]);
                    return await message.reply(`✅ Промокод \`${parts[1]}\` создан!`, replyParams());
                } else {
                    return await message.reply("❌ Формат: /создать [код] [сумма] [лимит]", replyParams());
                }
            }
        }

        if (cleanText === 'промолист') {
            const rows = await dbAll("SELECT code, amount, limit_count, used_by FROM promos");
            if (rows.length === 0) return await message.reply("❌ Активных промокодов нет.", replyParams());
            
            let promoList = "🎁 Активные промокоды:\n\n";
            for (const r of rows) {
                const usedCount = r.used_by ? r.used_by.split(",").length : 0;
                promoList += `▪️ \`${r.code}\` — ${r.amount}$ (${usedCount}/${r.limit_count})\n`;
            }
            return await message.reply(promoList, replyParams());
        }

        if (cleanText.startsWith('promo')) {
            if (parts.length === 2) {
                const row = await dbGet("SELECT amount, limit_count, used_by FROM promos WHERE code = ?", [parts[1]]);
                
                if (!row) return await message.reply("❌ Промокод не существует или исчерпан.", replyParams());
                
                const usedBy = row.used_by ? row.used_by.split(",") : [];
                if (usedBy.length >= row.limit_count) {
                    await dbRun("DELETE FROM promos WHERE code = ?", [parts[1]]);
                    return await message.reply("❌ Промокод больше не действителен.", replyParams());
                }
                
                if (usedBy.includes(String(userId))) return await message.reply("❌ Ты уже активировал этот промокод!", replyParams());
                
                usedBy.push(String(userId));
                await updateBalance(userId, row.amount);
                
                if (usedBy.length >= row.limit_count) {
                    await dbRun("DELETE FROM promos WHERE code = ?", [parts[1]]);
                    return await message.reply(`✅ Активирован! +${row.amount}$\n⚠️ Промокод удален (лимит исчерпан).`, replyParams());
                } else {
                    await dbRun("UPDATE promos SET used_by = ? WHERE code = ?", [usedBy.join(","), parts[1]]);
                    return await message.reply(`✅ Активирован! +${row.amount}$\nОсталось: ${row.limit_count - usedBy.length}`, replyParams());
                }
            } else {
                return await message.reply("❌ Формат: /promo [код]", replyParams());
            }
        }

        return;

    } catch (error) {
        console.error("ОШИБКА ПРИ ОБРАБОТКЕ:", error);
    }
});

// ===== ОБРАБОТКА КНОПОК =====
vk.updates.on('message_event', async (context) => {
    try {
        const payload = context.eventPayload;
        const userId = context.userId;
        
        if (payload.cmd === 'duel_accept') {
            const duelId = payload.duel_id;
            const row = await dbGet("SELECT challenger, bet FROM active_duels WHERE msg_id = ?", [duelId]);
            
            if (row) {
                if (String(userId) === row.challenger) return await context.answer({ type: 'show_snackbar', text: '❌ Нельзя драться с собой!' });
                if (await getBalance(userId) < row.bet) return await context.answer({ type: 'show_snackbar', text: '❌ Не хватает денег!' });
                
                const winnerId = Math.random() < 0.5 ? parseInt(row.challenger) : userId;
                const loserId = winnerId === userId ? parseInt(row.challenger) : userId;
                const prize = Math.floor(row.bet * 1.8);
                
                await updateBalance(winnerId, prize);
                await updateBalance(loserId, -row.bet);
                await dbRun("DELETE FROM active_duels WHERE msg_id = ?", [duelId]);
                
                const winnerName = await getFullName(winnerId);
                const loserName = await getFullName(loserId);
                const msgText = `⚔️ Дуэль завершена!\n\n🏆 Победитель: ${winnerName}\n❌ Проигравший: ${loserName}\n\n💰 Выигрыш: ${prize}$`;
                
                await context.answer({ type: 'show_snackbar', text: '⚔️ Дуэль завершена!' });
                
                await vk.api.messages.edit({
                    peer_id: context.peerId,
                    conversation_message_id: context.conversationMessageId,
                    message: msgText,
                    keyboard: ""
                });
                return;
            }
        }

        if (payload.cmd === 'mines_set') {
            const gameId = String(payload.gameId);
            const count = Number(payload.count);
            
            const row = await dbGet("SELECT bet FROM games WHERE game_id = ? AND user_id = ?", [gameId, String(userId)]);
            if (row) {
                const minesArr = [];
                while(minesArr.length < count) {
                    const r = Math.floor(Math.random() * 9) + 1;
                    if (!minesArr.includes(r)) minesArr.push(r);
                }
                const minesStr = JSON.stringify(minesArr);
                await dbRun("UPDATE games SET mines = ?, opened = '[]', multiplier = 1.0 WHERE game_id = ?", [minesStr, gameId]);
                
                const msgText = `💣 Мины\nСтавка: ${row.bet}$ | Мин: ${count} из 9\n\nВыбери клетку, чтобы открыть алмаз 💎`;
                
                await context.answer();
                
                await vk.api.messages.edit({
                    peer_id: context.peerId,
                    conversation_message_id: context.conversationMessageId,
                    message: msgText,
                    keyboard: getMinesFieldKb(gameId, [], minesArr)
                });
                return;
            }
        }

        if (payload.cmd === 'mines_click') {
            const gameId = String(payload.gameId);
            const cell = Number(payload.cell);
            
            const row = await dbGet("SELECT bet, mines, opened, multiplier FROM games WHERE game_id = ? AND user_id = ?", [gameId, String(userId)]);
            
            if (row) {
                const bet = row.bet;
                const mines = JSON.parse(row.mines);
                const opened = JSON.parse(row.opened);
                
                if (opened.includes(cell)) return await context.answer({ type: 'show_snackbar', text: '❌ Клетка уже открыта!' });

                opened.push(cell);

                if (mines.includes(cell)) {
                    await updateBalance(userId, -bet);
                    await dbRun("DELETE FROM games WHERE game_id = ?", [gameId]);
                    
                    const msgText = `💥 Вы попали на мину!\n\nПроигрыш: -${bet}$\nБаланс: ${formatMoney(await getBalance(userId))}$`;
                    
                    await context.answer({ type: 'show_snackbar', text: '💥 БУМ! Вы проиграли.' });
                    
                    await vk.api.messages.edit({
                        peer_id: context.peerId,
                        conversation_message_id: context.conversationMessageId,
                        message: msgText,
                        keyboard: getMinesFieldKb(gameId, Array.from({length: 9}, (_, i) => i + 1), mines, true)
                    });
                    return;
                }

                let newMult = 1.0;
                for (let i = 0; i < opened.length; i++) {
                    newMult *= (9 - i) / (9 - mines.length - i);
                }
                newMult = Math.round(newMult * 0.95 * 100) / 100;
                
                await dbRun("UPDATE games SET opened = ?, multiplier = ? WHERE game_id = ?", [JSON.stringify(opened), newMult, gameId]);
                
                const winAmount = Math.floor(bet * newMult);
                const msgText = `💣 Мины\nСтавка: ${bet}$ | Мин: ${mines.length} из 9\n\nОткрыто алмазов: ${opened.length} | Коэф: x${newMult}\nВыигрыш сейчас: ${winAmount}$`;
                
                await context.answer({ type: 'show_snackbar', text: `💎 Алмаз! x${newMult}` });
                
                await vk.api.messages.edit({
                    peer_id: context.peerId,
                    conversation_message_id: context.conversationMessageId,
                    message: msgText,
                    keyboard: getMinesFieldKb(gameId, opened, mines)
                });
                return;
            } else {
                return await context.answer({ type: 'show_snackbar', text: '❌ Игра не найдена или уже завершена.' });
            }
        }

        if (payload.cmd === 'mines_cashout') {
            const gameId = String(payload.gameId);
            const row = await dbGet("SELECT bet, multiplier, mines FROM games WHERE game_id = ? AND user_id = ?", [gameId, String(userId)]);
            
            if (row) {
                if (!row.mines || row.mines === '[]') {
                    return await context.answer({ type: 'show_snackbar', text: '❌ Игра еще не началась!' });
                }

                const winAmount = Math.floor(row.bet * row.multiplier);
                await updateBalance(userId, winAmount);
                await dbRun("DELETE FROM games WHERE game_id = ?", [gameId]);
                
                const msgText = `💰 Вы забрали выигрыш: ${winAmount}$!\nБаланс: ${formatMoney(await getBalance(userId))}$`;
                
                await vk.api.messages.edit({
                    peer_id: context.peerId,
                    conversation_message_id: context.conversationMessageId,
                    message: msgText,
                    keyboard: ""
                });
                return await context.answer({ type: 'show_snackbar', text: `💰 Вы забрали ${winAmount}$!` });
            } else {
                return await context.answer({ type: 'show_snackbar', text: '❌ Игра не найдена или уже завершена.' });
            }
        }

    } catch (e) {
        console.error("Ошибка в кнопках:", e);
    }
});

// ===== ЗАПУСК =====
console.log("ПОПЫТКА ЗАПУСКА БОТА...");
vk.updates.startPolling().then(() => {
    console.log("--- БОТ УСПЕШНО ЗАПУЩЕН (LONGPOLL) ---");
}).catch(err => {
    console.error("ОШИБКА ПРИ СТАРТЕ:", err);
});
