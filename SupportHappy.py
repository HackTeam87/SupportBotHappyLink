import logging
import os
import re
import time
from datetime import datetime

import pymysql
import requests
from dotenv import load_dotenv
from telebot import TeleBot, types
from tabulate import tabulate



# Запуск бота
# sudo systemctl stop happylink_bot.service

# =====================================
#        Загрузка переменных среды
# =====================================
load_dotenv()

# =====================================
#        Глобальные настройки
# =====================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
URL = os.getenv('VITE_SERVICE_API_URL')
KEY = os.getenv('VITE_SERVICE_API_KEY')

# Время задержки отправки сообщения
MESSAGE_DELAY_TIME = 1.1


# Настройка логирования
logging.basicConfig(
    filename='/tmp/SupportBot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Инициализация бота
bot = TeleBot(BOT_TOKEN, threaded=False)

# =====================================
#        Функции для работы с БД
# =====================================
def get_db_connection():
    return pymysql.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4'
    )

def get_user_by_phone(phone_number: str, telegram_id: int) -> bool | None:
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            user_exists = cursor.execute(
                '''
                SELECT c.id, c.agreement, cp.value phone
                FROM clients c
                LEFT JOIN client_contacts cp 
                    ON cp.agreement_id = c.id
                    AND cp.main = 1
                    AND cp.type = 'PHONE'
                WHERE cp.type = 'PHONE'
                  AND cp.value LIKE %s
                LIMIT 1
                ''',
                ("%" + phone_number)
            )
            if user_exists:
                cursor.execute(
                    '''
                    UPDATE clients
                    LEFT JOIN client_contacts
                        ON clients.id = client_contacts.agreement_id
                        AND client_contacts.main = 1
                        AND client_contacts.type = 'PHONE'
                    SET clients.telegram_chat_id=%s
                    WHERE client_contacts.value LIKE %s
                    ''',
                    (telegram_id, "%" + phone_number)
                )
                connection.commit()
                return True
            return False
    except pymysql.MySQLError as e:
        logging.error(f"Ошибка базы данных: {e}")
        return None
    finally:
        connection.close()

def get_user_by_telegram_id(telegram_id: int):
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                '''
                SELECT cp.value phone, c.id, c.name
                FROM clients c
                LEFT JOIN client_contacts cp
                    ON cp.agreement_id = c.id
                    AND cp.main = 1
                    AND cp.type = 'PHONE'
                WHERE c.telegram_chat_id=%s
                ''',
                (telegram_id,)
            )
            user_data = cursor.fetchone()
            return user_data
    except pymysql.MySQLError as e:
        logging.error(f"Ошибка базы данных: {e}")
        return None
    finally:
        connection.close()


# =====================================
#  Игнорирование нетекстовых сообщений
# =====================================
# Обработчик неподдерживаемых типов сообщений
@bot.message_handler(content_types=['animation', 'audio', 'document', 'photo', 'sticker', 'video', 'video_note', 'voice', 'location', 'dice', 'poll'])
def unsupported_message_handler(message: types.Message):
    user_id = message.chat.id

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    button_start = types.KeyboardButton("/start")
    markup.add(button_start)

    # Отправляем сообщение пользователю
    bot.send_message(
        user_id,
        "На жаль, я не підтримую цей тип повідомлень. "
        "Будь ласка, скористайтеся текстовими повідомленнями.",
        reply_markup=markup
    )

    # Логируем неподдерживаемое сообщение
    logging.info(f"Користувач {user_id} надіслав неподтримуване повідомлення типу {message.content_type}.")
        

# =====================================
#        Вспомогательные функции
# =====================================
def sanitize_input(input_text: str) -> str:
    return re.sub(r"[<>'\";]", "", input_text)


# =====================================
#        Менюшки
# =====================================

def get_phone_keyboard() -> types.ReplyKeyboardMarkup:
    keyboard = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    button = types.KeyboardButton("📞 Надіслати номер телефону", request_contact=True)
    keyboard.add(button)
    return keyboard

def get_main_menu() -> types.ReplyKeyboardMarkup:
    menu = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    menu.add(
        types.KeyboardButton("💳 Баланс"),
        types.KeyboardButton("💯 Платежі"),
        types.KeyboardButton("💰 Оплата"),
        types.KeyboardButton("👤 Кабінет"),
        types.KeyboardButton("📞 Підтримка")
    )
    return menu

def get_pay_menu() -> types.InlineKeyboardMarkup:
    menu = types.InlineKeyboardMarkup()
    menu.add(
        types.InlineKeyboardButton(
            '💳 EasyPay',
            url='https://easypay.ua/ua/catalog/internet/happylink'
        ),
        types.InlineKeyboardButton(
            '🏦 Privat24',
            url=(
                'https://next.privat24.ua/payments/form/'
                '%7B%22token%22%3A%22b9b67f5b-1f2c-47c4-bb1f-be8d48609dc0%22%7D'
            )
        ),
    )
    menu.add(
        types.InlineKeyboardButton('📊 Реквізити', callback_data='show_requisites_handler')
    )
    return menu

# =====================================
#  Логика состояний; для поддержки
# =====================================
user_state = {}

def set_user_state(chat_id: int, state: str | None):
    user_state[chat_id] = state

def get_user_state(chat_id: int) -> str | None:
    return user_state.get(chat_id, None)

# =====================================
#        Обработчики команд бота
# =====================================
@bot.message_handler(commands=['start'])
def start_handler(message: types.Message):
    bot.send_message(
        message.chat.id,
        "Будь ласка, надішліть номер телефону, пов'язаний з вашим договором.",
        reply_markup=get_phone_keyboard()
    )
    logging.info(f"Пользователь {message.chat.id} отправил /start")

@bot.message_handler(content_types=['contact'])
def contact_handler(message: types.Message):
    user_id = message.chat.id
    phone_number = message.contact.phone_number

    logging.info(f"Пользователь {user_id} отправил номер телефона: {phone_number}")

    try:
        result = get_user_by_phone(phone_number, user_id)
        if result is True:
            time.sleep(MESSAGE_DELAY_TIME)
            bot.send_message(
                user_id,
                (
                    "<b>Ваш номер телефону знайдено!</b>\n"
                    "Що ви хотіли б зробити?"
                ),
                parse_mode="HTML",
                reply_markup=get_main_menu()
            )
        elif result is False:
            bot.send_message(
                user_id,
                "Ваш номер телефону не знайдено. "
                "Спробуйте ще раз або зв'яжіться з підтримкою."
            )
        else:
            bot.send_message(user_id, "Сталася помилка. Спробуйте пізніше.")
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        bot.send_message(user_id, "Сталася помилка. Спробуйте пізніше.")



@bot.message_handler(func=lambda msg: msg.text == "💳 Баланс")
def bill_handler(message: types.Message):
    user_id = message.chat.id

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
            '''
            SELECT
                c.agreement,
                c.balance,
                REPLACE(GROUP_CONCAT(DISTINCT bill_prices.name ORDER BY bill_prices.name SEPARATOR ', '), ' ', '\n') AS tariff,
                 CONCAT(
                    REPLACE(ac.name, ' ', '\n'), ', ',
                    REPLACE(s.name, ' ', '\n'), ', ',
                    REPLACE(ah.name, ' ', '\n'), ', кв. ',
                    REPLACE(c.apartment, ' ', '\n')
                ) AS address
            FROM clients c
            JOIN addr_houses ah ON ah.id = c.house
            JOIN addr_streets s ON s.id = ah.street
            JOIN addr_cities ac ON ac.id = s.city
            JOIN client_prices ON client_prices.agreement = c.id AND client_prices.time_stop IS NULL
            JOIN bill_prices ON bill_prices.id = client_prices.price
            WHERE c.telegram_chat_id=%s
            GROUP BY c.agreement, c.balance, address, c.telegram_chat_id
            ORDER BY client_prices.id DESC
            LIMIT 10;
            ''',
            (user_id,)
            )

            bill_records = cursor.fetchall()
            if bill_records:
                headers = [ "Баланс", "Тариф", "Адреса"]
                table = [
                    [
                        f"₴{row[1]:.2f}",
                        f"{row[2]}",
                        f"{row[3]}",
                    ]
                    for row in bill_records
                ]

                table_text = tabulate(table, headers=headers, tablefmt="grid")

                # Получаем "Договір" и добавляем его в сообщение перед таблицей
                agreement = bill_records[0][0]

                time.sleep(MESSAGE_DELAY_TIME)
                bot.send_message(
                    user_id,
                    text=f"Договір# {agreement}\n<pre>{table_text}</pre>",
                    parse_mode="HTML"
                )
            else:
                time.sleep(MESSAGE_DELAY_TIME)
                bot.send_message(
                    user_id,
                    "<b>Не має активних послуг</b>. \n Будь ласка, зверніться до підтримки.",
                    parse_mode="HTML"
                )
    except pymysql.MySQLError as e:
        logging.error(f"Помилка бази даних: {e}")
        bot.send_message(user_id, "Сталася помилка. Спробуйте пізніше.")
    finally:
        connection.close()


@bot.message_handler(func=lambda msg: msg.text == "💯 Платежі") 
def show_payment_handler(message: types.Message):
    user_id = message.chat.id

    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                '''
                SELECT p.money,
                       CAST(time AS DATE) time,
                       p.comment,
                       p.payment_type,
                       c.agreement
                FROM paymants p
                JOIN clients c ON p.agreement = c.id
                WHERE c.telegram_chat_id=%s
                ORDER BY time DESC
                LIMIT 12;
                ''',
                (user_id,)
            )
            payment_records = cursor.fetchall()
            if payment_records:
                headers = ["Сума", "Дата", "Опис"]
                table = [
                    [
                        f'\u20b4{row[0]}',
                        row[1].strftime("%Y-%m-%d"),
                        row[2] if row[2] else ''
                    ]
                    for row in payment_records
                ]
                # Получаем "Договір" и добавляем его в сообщение перед таблицей
                agreement = payment_records[0][4]
                table_text = tabulate(table, headers=headers, tablefmt="grid")

                time.sleep(MESSAGE_DELAY_TIME)
                bot.send_message(
                    user_id,
                    text=f"Договір# {agreement}\n останні 12 платежів \n<pre>{table_text}</pre>",
                    parse_mode="HTML"
                )
            else:
                bot.send_message(
                    user_id,
                    "Платежі не знайдено. Будь ласка, зверніться до підтримки."
                )
    except pymysql.MySQLError as e:
        logging.error(f"Помилка бази даних: {e}")
        bot.send_message(user_id, "Сталася помилка. Спробуйте пізніше.")
    finally:
        connection.close()



@bot.message_handler(func=lambda msg: msg.text == "👤 Кабінет")
def lc_handler(message: types.Message):
    user_id = message.chat.id

    time.sleep(MESSAGE_DELAY_TIME)
    bot.send_message(
        user_id,
        'Натисніть на посилання, щоб відкрити:\n [👤 особистий кабінет](https://my.happylink.net.ua/)',
        parse_mode="MarkdownV2"
        
    )
    logging.info(f"Користувач {user_id} натиснув '👤 Кабінет'.")



@bot.message_handler(func=lambda msg: msg.text == "💰 Оплата")
def pay_handler(message: types.Message):
    user_id = message.chat.id

    time.sleep(MESSAGE_DELAY_TIME)
    bot.send_message(
        user_id,
        "*💰 Оберіть зручний спосіб оплати:*",
        parse_mode="MarkdownV2",
        reply_markup=get_pay_menu()
    )
    logging.info(f"Користувач {user_id} натиснув 'Поповнити рахунок'.")



@bot.callback_query_handler(func=lambda call: call.data == 'show_requisites_handler')
def show_requisites_handler(call: types.CallbackQuery):
    user_id = call.message.chat.id

    try:
        data = {
            "Рекомендована сума для оплати": "[Абонплата] грн/міс",
            "Отримувач": "ТОВ \"Хеппілінк Україна\"",
            "IBAN": "UA113052990000026002035033913",
            "РНОКПП": "45589308",
            "В АТ КБ": "«ПриватБанк»",
            "Призначення платежу": "Оплата за інтернет, особовий рахунок № [Ваш рахунок]"
        }
        table_text = "\n".join([f"{key}: {value}" for key, value in data.items()])

        time.sleep(MESSAGE_DELAY_TIME)
        bot.send_message(
            user_id,
            f"<b>Платіжна інформація:</b>\n\n{table_text}",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Помилка: {e}")
        bot.send_message(user_id, "Сталася помилка. Спробуйте пізніше.")



# =====================================
#   Блок 📞 Підтримка;
# =====================================
@bot.message_handler(func=lambda msg: msg.text == "📞 Підтримка")
def contact_support_handler(message: types.Message):
    user_id = message.chat.id
    # Устанавливаем состояние, что мы ждём ввода текста для поддержки
    set_user_state(user_id, "support_waiting_text")

    # Создаём клавиатуру, которая позволит вернуться в главное меню
    support_menu = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    # Кнопка возврата
    back_button = types.KeyboardButton("↩️ Повернутись до головного меню")
    support_menu.add(back_button)
    
    time.sleep(MESSAGE_DELAY_TIME)
    msg = bot.send_message(
        user_id,
        "Введіть, будь ласка, текст повідомлення для підтримки "
        "або поверніться до головного меню:",
        reply_markup=support_menu
    )
    bot.register_next_step_handler(msg, process_support_message)

def process_support_message(message: types.Message):
    user_id = message.chat.id
    state = get_user_state(user_id)

    # Если пользователь нажал кнопку &laquo;↩️ Повернутись до головного меню&raquo;
    if message.text == "↩️ Повернутись до головного меню":
        set_user_state(user_id, None)

        time.sleep(MESSAGE_DELAY_TIME)
        bot.send_message(
            user_id,
            "Ви повернулися до головного меню.",
            reply_markup=get_main_menu()
        )
        return

    # Проверяем, не нажал ли пользователь вместо текста одну из кнопок главного меню
    main_menu_texts = {
        "💳 Баланс",
        "💯 Платежі",
        "💰 Оплата",
        "👤 Кабінет",
        "📞 Підтримка"
    }
    if message.text in main_menu_texts and state == "support_waiting_text":

        time.sleep(MESSAGE_DELAY_TIME)
        bot.send_message(
            user_id,
            "Ви натиснули кнопку меню, проте ми очікуємо текст повідомлення.\n"
            "Будь ласка, введіть текст для підтримки або поверніться до головного меню:"
        )
        bot.register_next_step_handler(message, process_support_message)
        return

    # Если действительно пришёл текст для техподдержки
    user_data = get_user_by_telegram_id(user_id)

    if not user_data:

        time.sleep(MESSAGE_DELAY_TIME)
        bot.send_message(user_id, "Не вдалося знайти ваш запис у базі.")
        set_user_state(user_id, None)
        return

    phone, agreement_id, name = user_data
    now = datetime.now()
    dt_string = now.strftime("%d.%m.%Y %H:%M:%S")

    headers = {
        'Content-type': 'application/json',
        'X-Auth-Key': KEY
    }
    body = {
        "agreement_id": agreement_id,
        "reason_id": 10,
        "phone": phone,
        "destination_time": dt_string,
        "comment": "\n" + sanitize_input(message.text)
    }

    try:
        response = requests.post(URL, json=body, headers=headers)
        logging.info(f"Сервис вернул: {response.text}")
    except Exception as e:
        logging.error(f"Ошибка при отправке заявки: {e}")

        time.sleep(MESSAGE_DELAY_TIME)
        bot.send_message(
            user_id,
            "Виникла помилка при відправці заявки. Спробуйте пізніше."
        )
        set_user_state(user_id, None)
        return
    
    time.sleep(MESSAGE_DELAY_TIME)
    bot.send_message(
        user_id,
        "<b>Повідомлення отримано!</b>\nОчікуйте, ми зв’яжемося з вами.",
        parse_mode="HTML",
        reply_markup=get_main_menu()
    )
    set_user_state(user_id, None)

# =====================================
#          Точка входа (main)
# =====================================
def main():
    logging.info("Бот запущен")
    print("Бот запущен")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
