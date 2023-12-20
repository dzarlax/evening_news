from xml.etree import ElementTree as ET
import datetime
import requests
from openai import OpenAI

import os
import json
from typing import Optional
from bs4 import BeautifulSoup

text_chat_id = 388128

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
            "Обобщите заголовки следующих новостей, представив их в виде короткого бюллетеня. "
            "Используйте новую строку для каждого пункта. Для новостей на похожие темы, "
            "пожалуйста, сгруппируйте ссылки рядом с соответствующими заголовками под кнопкой ссылка "
            "В начало каждой ссылки нужно добавить https://dzarlax.dev/rss/articles/article.html?link="
            "Ссылку нужно спрятать под кнопку"
            "Заголовок не должен быть кликабельным"
            "Отформатируй итоговый текст в HTML можно использовать только теги <b>, <i>, <a>,<code> "
            "Вот пары заголовков и ссылок:" + titles_text
    )
    response = client.chat.completions.create(  # Используйте 'completions.create' для получения ответа
        model="gpt-4",
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
    TELEGRAM_TOKEN = load_config("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = load_config("TEST_TELEGRAM_CHAT_ID")
    send_message_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    response = requests.post(send_message_url, data=data)

def send_telegram_message(message):
    # Place your Telegram bot's API token here
    TELEGRAM_TOKEN = load_config("TELEGRAM_BOT_TOKEN")
    # Place your own Telegram user ID here
    TELEGRAM_CHAT_ID = load_config("TELEGRAM_CHAT_ID")
    #TELEGRAM_CHAT_ID = load_config("TEST_TELEGRAM_CHAT_ID")
    send_message_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(send_message_url, data=data)
        response.raise_for_status()  # Вызывает исключение для неудачных HTTP-запросов
        if response.status_code == 200:
            send_error("Сообщение успешно отправлено")
        else:
            send_error(f"Ошибка при отправке сообщения: {response.status_code}")
    except requests.RequestException as e:
        send_error(f"Произошла ошибка при отправке сообщения: {e}")
    send_error(response.json())
    return response.json()

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
    today_titles = fetch_news_titles(url)
    summary = process_titles_with_gpt(today_titles)
    print(summary)
    cleaned_html = clean_html(summary)
    send_telegram_message(cleaned_html)
job()