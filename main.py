from xml.etree import ElementTree as ET
import datetime
import requests
from openai import OpenAI

import os
import json
import time
from typing import Optional
from bs4 import BeautifulSoup


def load_config(key: Optional[str] = None):
    # Получение абсолютного пути к директории, где находится main.py
    current_directory = os.path.dirname(os.path.abspath(__file__))
    # Объединение этого пути с именем файла, который вы хотите открыть
    file_path = os.path.join(current_directory, "config.json")

    with open(file_path, "r") as file:
        config = json.load(file)

    if key:
        if key not in config:
            raise KeyError(f"The key '{key}' was not found in the config file.")
        return config[key]  # Возвращаем значение заданного ключа
    else:
        return config  # Возвращаем весь конфигурационный словарь


# Здесь должен быть ваш OpenAI API ключ
client = OpenAI(api_key=load_config("openai_token"))


def fetch_news_titles(url):
    response = requests.get(url)
    root = ET.fromstring(response.content)
    today = datetime.datetime.now().date()
    yesterday = today - datetime.timedelta(days=1)
    titles_today = []

    for item in root.findall('.//item'):
        pub_date = item.find('pubDate').text
        pub_date = datetime.datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %z').date()
        if pub_date == today:
            title = item.find('title').text
            link = item.find('link').text
            titles_today.append((title, link))

    titles_text = ' ;'.join([f"Заголовок: {title}, Ссылка: {link}" for title, link in titles_today])
    return titles_text


def process_titles_with_gpt(titles_text):
    prompt_text = (
            "Создайте сводку дня, обобщив следующие заголовки новостей на русском языке. Выделите номер каждой новости жирным шрифтом с помощью тега <b>. Для заголовков новостей используйте курсив с помощью тега <i>. Все ссылки на статьи должны быть представлены в виде гиперссылок, преобразованных в кнопки, с добавлением к URL 'https://dzarlax.dev/rss/articles/article.html?link=' и использованием тега <a href>, где название источника новости будет отображаться как название кнопки. Группируйте ссылки вместе с соответствующими заголовками по тематическому принципу. Разделите разные новости тегом переноса строки <br>. Обработайте все предоставленные новости без сокращений. Вот список заголовков и соответствующих ссылок: " + titles_text
    )
    response = client.chat.completions.create(  # Используйте 'completions.create' для получения ответа
        model="gpt-4-0125-preview",
        messages=[
            {"role": "system", "content": "Ты ассистент русскоязычного руководителя"},
            {"role": "user", "content": prompt_text},
        ]
    )

    # Проверьте, является ли 'response' словарём или объектом
    # Если 'response' - это словарь (как показано в вашем примере ошибки), используйте код ниже:
    if isinstance(response, dict):
        summary = response['choices'][0]['message']['content']
    # Если 'response' - это объект, попробуйте использовать точечную нотацию:
    else:
        summary = response.choices[0].message.content
    print(summary)
    return summary


def send_error(message):
    telegram_token = load_config("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = load_config("TEST_TELEGRAM_CHAT_ID")
    send_message_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    data = {
        "chat_id": telegram_chat_id,
        "text": message
    }
    response = requests.post(send_message_url, data=data)


def send_telegram_message(message):
    telegram_token = load_config("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = load_config("TELEGRAM_CHAT_ID")
    #telegram_chat_id = load_config("TEST_TELEGRAM_CHAT_ID")
    send_message_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"

    data = {
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
        "chat_id": telegram_chat_id,
        "text": message,
    }

    try:
        response = requests.post(send_message_url, data=data)
        response.raise_for_status()  # Вызовет исключение для статусов HTTP, отличных от 200

        # Возвращает JSON ответа, который должен содержать 'ok': True, если сообщение было успешно отправлено
        return response.json()
    except requests.RequestException as e:
        send_error(f"Произошла ошибка при отправке сообщения: {e}")

        # Возвращаем словарь с 'ok': False в случае неудачи, чтобы отражать результат
        return {"ok": False, "error": str(e)}


def clean_html(html):
    # Разбираем HTML
    soup = BeautifulSoup(html, 'html.parser')

    # Разрешенные теги
    allowed_tags = ['b', 'i', 'a', 'code']

    # Удаляем все теги, кроме разрешенных
    for tag in soup.find_all():
        if tag.name not in allowed_tags:
            tag.unwrap()

    # Возвращаем "очищенный" HTML
    return str(soup)


def job():
    url = load_config("feed_url")
    max_retries = 3  # Максимальное количество попыток
    retries = 0

    while retries < max_retries:
        try:
            # Загрузка и обработка заголовков новостей
            today_titles = fetch_news_titles(url)
            summary = process_titles_with_gpt(today_titles)
            cleaned_html = clean_html(summary)

            # Попытка отправки сообщения
            response = send_telegram_message(cleaned_html)
            # Проверка успешности отправки
            if response.get('ok'):
                send_error("Сообщение успешно отправлено")
                break  # Выход из цикла, если отправка успешна
            else:
                raise Exception("Telegram API не подтвердило успешную отправку")
        except Exception as e:
            send_error(f"Произошла ошибка при отправке сообщения: {e}")
            retries += 1
            if retries < max_retries:
                send_error("Попытка повторной отправки...")
                time.sleep(5)  # Задержка перед следующей попыткой
            else:
                send_error("Превышено максимальное количество попыток отправки")
                break


job()
