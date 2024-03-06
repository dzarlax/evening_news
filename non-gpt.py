#!/usr/bin/env python
# coding: utf-8
import datetime
import json
import os
import sys
from typing import Optional
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import pandas as pd
import requests
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from telegraph import Telegraph
from transformers import T5Tokenizer, T5ForConditionalGeneration

model = T5ForConditionalGeneration.from_pretrained("google/flan-t5-base")
tokenizer = T5Tokenizer.from_pretrained("google/flan-t5-base")

if len(sys.argv) > 1:
    # Значение первого аргумента сохраняется в переменную
    infra = sys.argv[1]
    # Теперь вы можете использовать переменную в вашем скрипте
    print(f"Переданное значение переменной: {infra}")
else:
    infra = 'prod'
    print("Аргумент не был передан.")


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


def fetch_and_parse_rss_feed(url: str) -> pd.DataFrame:
    response = requests.get(url)
    root = ET.fromstring(response.content)
    data = [{'headline': item.find('title').text,
             'link': item.find('link').text,
             'pubDate': datetime.datetime.strptime(item.find('pubDate').text, '%a, %d %b %Y %H:%M:%S %z').date(),
             'description': item.find('description').text} for item in root.findall('.//item')]
    return pd.DataFrame(data)


def generate_summary_batch(input_texts: list, tokenizer: T5Tokenizer, model: T5ForConditionalGeneration, batch_size: int = 4) -> list:
    summaries = []
    for i in range(0, len(input_texts), batch_size):
        batch_texts = input_texts[i:i+batch_size]
        batch_prompts = ["Answer with one best category for news headline " + text for text in batch_texts]
        input_ids = tokenizer(batch_prompts, return_tensors="pt", padding=True, truncation=True, max_length=512).input_ids
        outputs = model.generate(input_ids, max_length=50, num_return_sequences=1)
        batch_summaries = [tokenizer.decode(output, skip_special_tokens=True) for output in outputs]
        summaries.extend(batch_summaries)
    return summaries


def deduplication(data):
    # Вычисление TF-IDF и косинусного сходства
    tfidf_vectorizer = TfidfVectorizer()
    tfidf_matrix = tfidf_vectorizer.fit_transform(data['headline'])
    cosine_sim_matrix = cosine_similarity(tfidf_matrix)

    # Идентификация групп новостей
    threshold = 0.5
    graph = csr_matrix(cosine_sim_matrix > threshold)
    n_components, labels = connected_components(csgraph=graph, directed=False, return_labels=True)
    data['group_id'] = labels

    # Группировка данных по group_id и агрегация ссылок в списки
    links_aggregated = data.groupby('group_id')['link'].apply(list).reset_index()

    # Определение новости с самым длинным заголовком в каждой группе
    longest_headlines = data.loc[data.groupby('group_id')['headline'].apply(lambda x: x.str.len().idxmax())]

    # Объединение результатов, чтобы к каждой новости добавить список ссылок
    result = pd.merge(longest_headlines, links_aggregated, on='group_id', how='left')

    # Переименовываем колонки для ясности
    result.rename(columns={'link_x': 'link', 'link_y': 'links'}, inplace=True)

    # Удаление дубликатов, не включая столбец 'links'
    cols_for_deduplication = [col for col in result.columns if col != 'links']
    result = result.drop_duplicates(subset=cols_for_deduplication)
    return result


def escape_html(text):
    """Заменяет специальные HTML символы на их экранированные эквиваленты."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def format_html_telegram(row):
    # Экранирование специальных HTML символов в заголовке
    headline = escape_html(row['headline'])
    # Формирование списка форматированных ссылок для HTML из списка URL
    links_formatted = ['<a href="{0}">{1}</a>'.format('https://dzarlax.dev/rss/articles/article.html?link=' + link, urlparse(link).netloc) for link in row['links']]
    # Формирование строки HTML для заголовка и списка ссылок
    links_html = '\n'.join(links_formatted)
    return f"{headline}\n{links_html}\n"


def send_telegram_message(message, chat_id, telegram_token):
    send_message_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    response = requests.post(send_message_url, data={
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    })
    return response.json()


def html4tg(result):
    # Подготовка сообщения для Telegram с использованием HTML
    html_output_telegram = ""
    for category, group in result.groupby('category'):
        category_html = category.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        html_output_telegram += f"<b>{category_html}</b>\n"
        html_output_telegram += '\n'.join(group.apply(format_html_telegram, axis=1))
    return html_output_telegram


def create_telegraph_page_with_library(result, access_token, author_name="Dzarlax", author_url="https://dzarlax.dev"):
    telegraph = Telegraph(access_token=access_token)
    # Подготовка контента страницы в HTML, используя только разрешенные теги
    content_html = ""
    for category, group in result.groupby('category'):
        # Используем <h3> для заголовков категорий, т.к. <h2> в списке запрещённых
        content_html += f"<h3>{category}</h3>\n"

        for _, row in group.iterrows():
            article_title = row['headline']
            # Формирование списка ссылок в <ul>
            links_html = ''.join([f'<li><a href=https://dzarlax.dev/rss/articles/article.html?link={link}>{urlparse(link).netloc}</a></li>' for link in row['links']])
            # Заголовки статей оборачиваем в <p> и добавляем к ним список ссылок
            content_html += f"<p>{article_title}</p>\n<ul>{links_html}</ul>\n"

    # Создание страницы на Telegra.ph
    response = telegraph.create_page(
        title="Новости за " + str(datetime.datetime.now().date()),
        html_content=content_html,
        author_name=author_name,
        author_url=author_url
    )
    return response['url']


# Подготовка и отправка сообщения
def prepare_and_send_message(result, chat_id, telegram_token, telegraph_access_token, service_chat_id):
    if len(html4tg(result)) <= 4096:
        # Если длина сообщения не превышает 4096 символов, отправляем напрямую через Telegram
        response = send_telegram_message(html4tg(result), chat_id, telegram_token)
        if response.get('ok'):
            send_telegram_message("Сообщение успешно отправлено", service_chat_id, telegram_token)
        else:
            send_telegram_message("Произошла ошибка при отправке", service_chat_id, telegram_token)
    else:
        telegraph_url = create_telegraph_page_with_library(result, telegraph_access_token)
        message = f"Сегодня много новостей, поэтому они спрятаны по ссылочке: {telegraph_url}"
        response = send_telegram_message(message, chat_id, telegram_token)
        if response.get('ok'):
            send_telegram_message("Сообщение успешно отправлено", service_chat_id, telegram_token)
        else:
            send_telegram_message("Произошла ошибка при отправке", service_chat_id, telegram_token)
    return response


def job():
    if infra == 'prod':
        chat_id = load_config("TELEGRAM_CHAT_ID")
    elif infra == 'test':
        chat_id = load_config("TEST_TELEGRAM_CHAT_ID")

    service_chat_id = load_config("TEST_TELEGRAM_CHAT_ID")
    telegram_token = load_config("TELEGRAM_BOT_TOKEN")
    telegraph_access_token = load_config("TELEGRAPH_ACCESS_TOKEN")

    # Получаем данные фида
    data = fetch_and_parse_rss_feed("https://s3.dzarlax.dev/feed_300.xml")

    # Преобразование и фильтрация данных
    data['today'] = datetime.datetime.now().date()
    data = data[data['pubDate'] == data['today']].drop(columns=['today', 'pubDate'])
    data['category'] = generate_summary_batch(data['headline'].tolist(), tokenizer, model, batch_size=4)
    result = deduplication(data)

    response = prepare_and_send_message(result, chat_id, telegram_token, telegraph_access_token, service_chat_id)
    print(response)


job()
