import logging
import os
import re
from enum import Enum

import openai
import pandas as pd
from docx import Document
from docx.shared import Pt, RGBColor
from htmldocx import HtmlToDocx
from markdown2 import Markdown
from tenacity import (retry, stop_after_attempt,  # for exponential backoff
                      wait_random_exponential)

import prompts
import configs

# configure the logger
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s') # noqa


class MarkdownSyntax(Enum):
    HEADING = r'^#(?!#)'
    SUB_HEADING = r'^#{2,}'
    BOLD = r'^\*{2}'
    BULLET = r'\-\s+\*{0,2}[^\n]+:\*{0,2}'
    QUESTION = r'\*{2}[^\n]+\?\*{2}'
    BOLD_WITH_NUMBER = r'^\d+[^\n]+:\*{0,2}'
    ONLY_BULLET = r'^\-\.?\s+(?=[A-Z]{1})'


def format_markdown(body):
    for regex in MarkdownSyntax:
        if regex == MarkdownSyntax.HEADING:
            body = re.sub(regex.value, '\n#', body, flags=re.M)
        if regex == MarkdownSyntax.SUB_HEADING:
            body = re.sub(regex.value, '\n##', body, flags=re.M)
        if regex == MarkdownSyntax.BOLD:
            body = re.sub(regex.value, '\n**', body, flags=re.M)
        if regex == MarkdownSyntax.ONLY_BULLET:
            body = re.sub(regex.value, '\n - ', body, flags=re.M)
        if regex == MarkdownSyntax.BULLET:
            result = re.findall(regex.value, body, flags=re.M)
            for res in result:
                head = re.sub(r'[\-\*]+', '', res, flags=re.M)  # noqa
                head = f'\n- **{head.strip()}**'
                body = body.replace(res, head)
        if regex == MarkdownSyntax.BOLD_WITH_NUMBER:
            result = re.findall(regex.value, body, flags=re.M)
            for res in result:
                head = res.replace('*', '')
                head = f'\n**{head.strip()}** '
                body = body.replace(res, head)
        if regex == MarkdownSyntax.QUESTION:
            result = re.findall(regex.value, body, flags=re.M)
            for res in result:
                question = re.sub(r'\*+', r'', res, flags=re.M)
                body = body.replace(res, f'## {question}')
        body = re.sub(r"^#*\s+introduction:?\n*", '', body, flags=re.M | re.I)
        body = re.sub(r'^#+\s+FAQs\n*', '## Frequently Asked Questions:\n', body, flags=re.M | re.I)
        body = re.sub(r"^#+\s+Frequently Asked Questions:?\n*", '## Frequently Asked Questions:\n', body,
                      flags=re.M | re.I)
        body = body.replace('(FAQs)', '')
        body = body.replace('FAQs', '')
        # remove Q: and A:
        body = re.sub(r'[AQ]:\s+', '', body, flags=re.M | re.I)

    return body


def log_attempt_number(retry_state):
    """return the result of the last call attempt"""
    logging.error(f"Retrying: {retry_state.outcome.exception()}...")


def html_to_document(html):
    document = Document()
    new_parser = HtmlToDocx()
    new_parser.add_html_to_document(html, document)
    for style in document.styles:
        try:
            font = style.font
            if 'Heading 1' in style.name:
                font.name = 'Arial'
                font.size = Pt(20)
                font.color.rgb = RGBColor(0, 0, 0)
            elif 'Heading 2' in style.name:
                font.name = 'Arial'
                font.size = Pt(18)
                font.color.rgb = RGBColor(0, 0, 0)
            elif 'Heading 3' in style.name:
                font.name = 'Arial'
                font.size = Pt(16)
                font.color.rgb = RGBColor(0, 0, 0)
            else:
                font.name = 'Arial'
                font.size = Pt(13)
                font.color.rgb = RGBColor(0, 0, 0)
        except AttributeError:
            pass
    return document


# reader class to read csv file
class Reader:
    def __init__(self, filename):
        self.df = pd.read_csv(filename, encoding='utf-8', encoding_errors='ignore')

    # reads keywords and return list of keywords   
    def read_keywords(self):
        return self.df['Keywords'].to_list()

    # read titles and return list of titles
    def read_titles(self):
        return self.df['Title'].to_list()

    def read_serials(self):
        return self.df['SL'].to_list()


# send requests to OpenAi to generate texts
class Article:
    def __init__(self, model=configs.MODEL):
        openai.api_key = configs.OPENAI_API_KEY
        self.model = model
        self.markdown = Markdown()

    # ref: https://beta.openai.com/docs/api-reference/completions
    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(10), after=log_attempt_number)
    def create_completions(self, messages: list):
        res, result = None, ''
        res = openai.ChatCompletion.create(
            model=self.model,
            messages=messages,
            temperature=configs.TEMPERATURE,
            max_tokens=configs.MAX_TOKENS
        )
        result += res.choices[0].message.content
        messages.append({'role': res.choices[0].message.role, 'content': result})
        logging.info('ChatGPT completed the request')
        return result

    def title_to_article(self, sl, keyword, title):
        messages = [
            {'role': 'system', 'content': prompts.SYSTEM_MSG},
            {'role': 'assistant', 'content': prompts.VERSION_ONE.format(title=title)}
        ]
        filename = f"./documents/{sl}. {keyword.replace('/', '.')}.docx"
        body = self.create_completions(messages)
        # make the directory 'documents' if not exists
        os.makedirs('./documents', exist_ok=True)
        if configs.DEBUG:
            with open(filename.replace('.docx', '.md'), 'w', encoding='utf-8') as f:
                f.write(body)
        body = format_markdown(body)
        # base level=2 sets headings to start at `h2`
        html = self.markdown.convert(body)
        html = re.sub(r'<br>\s*(?=<)', '', html, flags=re.M)
        html = html.replace('<br />', '')
        document = html_to_document(html)
        # saving the document file
        logging.info(f'[Done] SL: {sl} {keyword}')
        document.save(filename)

    def title_to_outlines(self, keyword, title):
        messages = [
            {'role': 'assistant', 'content': prompts.VERSION_TWO.format(title=title)}
        ]
        body = self.create_completions(messages)
        body = re.sub(r'[A-Z\d]+\.\s*', '- ', body, flags=re.M)
        logging.info(f'[Outlines Generated] {keyword}')
        return body

    def outline_to_docx(self):
        if not os.path.exists('outlines/outlines.csv'):
            raise FileNotFoundError(
                'outlines.csv not found.\nYou need to run the VERSION TWO first to generate a outlines.csv file')
        df = pd.read_csv('outlines/outlines.csv', encoding='utf-8', encoding_errors='ignore')
        serials = df['SL'].to_list()
        keywords = df['Keywords'].to_list()
        titles = df['Title'].to_list()
        outlines = df['Outlines'].to_list()
        for sl, keyword, title, outline in zip(serials, keywords, titles, outlines):
            messages = [
                {'role': 'system', 'content': prompts.SYSTEM_MSG},
                {'role': 'assistant', 'content': prompts.VERSION_THREE.format(title=title, outlines=outlines)}
            ]
            filename = f"./outlines/{sl}. {keyword.replace('/', '.')}.docx"
            body = self.create_completions(messages)
            # make the directory 'outlines' if not exists
            os.makedirs('./outlines', exist_ok=True)
            if configs.DEBUG:
                with open(filename.replace('.docx', '.md'), 'w', encoding='utf-8') as f:
                    f.write(body)
            body = format_markdown(body)
            # base level=2 sets headings to start at `h2`
            html = self.markdown.convert(body)
            html = re.sub(r'<br>\s*(?=<)', '', html, flags=re.M)
            html = html.replace('<br />', '')
            document = html_to_document(html)
            # saving the document file
            # do more stuff to document
            logging.info(f'[Done] SL: {sl} {keyword}')
            document.save(filename)


# helper functions
def writer_v1(article: Article, reader: Reader):
    for sl, keyword, title in zip(reader.read_serials(), reader.read_keywords(), reader.read_titles()):
        # saving title to docx file
        article.title_to_article(sl, keyword, title)


def writer_v2(article: Article, reader: Reader):
    for sl, keyword, title in zip(reader.read_serials(), reader.read_keywords(), reader.read_titles()):
        outlines = article.title_to_outlines(keyword, title)
        temp = {
            'SL': sl,
            'Keywords': keyword,
            'Title': title,
            'Outlines': outlines,
        }
        os.makedirs('outlines', exist_ok=True)
        df = pd.DataFrame(temp, columns=['SL', 'Keywords', 'Title', 'Outlines'], index=['SL'])
        if int(sl) == 1:
            df.to_csv('./outlines/outlines.csv', index=False, header=True)
        else:
            df.to_csv('./outlines/outlines.csv', mode='a', index=False, header=False)


def writer_v3(article: Article):
    article.outline_to_docx()


if __name__ == '__main__':
    intput_text = """Choose Version:\n[1] Press 1 for v1\n[2] Press 2 for v2\n[3] Press 3 for v3\n[4] Press q for quit\nEnter your option: """  # noqa

    article = Article()
    reader = Reader("keywords.csv")
    while True:
        option = input(intput_text)

        if option.isdigit() and int(option) == 1:
            writer_v1(article, reader)
            break
        if option.isdigit() and int(option) == 2:
            writer_v2(article, reader)
            break
        if option.isdigit() and int(option) == 3:
            writer_v3(article)
            break
        if option.lower() == 'q':
            logging.warning("Exiting the program.")
            break
