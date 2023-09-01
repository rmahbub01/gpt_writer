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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s: %(message)s')


class MarkdownSyntax(Enum):
    HEADING = r'^#(?!#)'
    SUB_HEADING = r'^#{2,}'
    BOLD = r'^\*{2}'
    BULLET = r'\-\s+\*{0,2}[^\n]+:\*{0,2}'
    QUESTION = r'\*{2}[^\n]+\?\*{2}'
    BOLD_WITH_NUMBER = r'^\d+[^\n]+:\*{0,2}'
    ONLY_BULLET = r'^\-\.?\s+(?=[A-Z]{1})'


def format_markdown(body: str):
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
                head = re.sub(r"[-*]+", '', res, flags=re.M)
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
                head = res.replace('*', '')
                head = f'## {head.strip()}'
                body = body.replace(res, head)
        body = re.sub(r'^#*\s+introduction\n*', '', body, flags=re.M | re.I)
        body = re.sub(r'^#*\s+FAQs\n*', '## Frequently Asked Questions:\n', body, flags=re.M | re.I)
        body = re.sub(r'^#*\s+Frequently Asked Questions:?\n*', '## Frequently Asked Questions:\n', body,
                      flags=re.M | re.I)
        # remove Q: and A:
        body: str = re.sub(r'[AQ]:\s+', '', body, flags=re.M | re.I)

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
        except AttributeError as e:
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
    def create_completions(self, prompt: str, is_v2=False):
        messages = [
            {'role': 'system', 'content': prompts.SYSTEM_MSG},
            {'role': 'assistant', 'content': prompt}
        ]
        if is_v2: messages.pop(0)
        res, result = None, ''
        res = openai.ChatCompletion.create(
            model=self.model,
            messages=messages,
            temperature=0.2,
            # max_tokens = 4096
        )
        result += res.choices[0].message.content
        messages.append({'role': res.choices[0].message.role, 'content': result})
        logging.info('ChatGPT completed the request')
        return result

    def title_to_article(self, sl, keyword):
        filename = f"./documents/{sl}. {keyword.replace('/', '.')}.docx"
        body = self.create_completions(prompts.VERSION_ONE.format(keyword=keyword))
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
        os.makedirs('./documents', exist_ok=True)
        logging.info(f'[Done] SL: {sl} {keyword}')
        document.save(filename)

    def title_to_outlines(self, keyword):
        body = self.create_completions(prompts.VERSION_TWO.format(keyword=keyword), is_v2=True)
        body = re.sub(r'[A-Z\d]+\.\s*', '', body, flags=re.MULTILINE)
        logging.info(f'[Outlines Generated] {keyword}')
        return body

    def outline_to_docx(self):
        if not os.path.exists('outlines/outlines.csv'):
            raise FileNotFoundError(
                'outlines.csv not found.\nYou need to run the VERSION TWO first to generate a outlines.csv file')
        df = pd.read_csv('outlines/outlines.csv')
        keywords = df['Keywords']
        outlines = df['Outlines']
        serials = df['SL']
        for sl, keyword, outline in zip(serials, keywords, outlines):
            filename = f"./outlines/{sl}. {keyword.replace('/', '.')}.docx"
            body = self.create_completions(prompts.VERSION_THREE.format(outlines=outlines))
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
            os.makedirs('./outlines', exist_ok=True)
            # do more stuff to document
            logging.info(f'[Done] SL: {sl} {keyword}')
            document.save(filename)


# helper functions
def writer_v1(article: Article, reader: Reader):
    for i, keyword in zip(reader.read_serials(), reader.read_keywords()):
        # saving title to docx file
        article.title_to_article(i, keyword)


def writer_v2(artile: Article, reader: Reader):
    for i, keyword in zip(reader.read_serials(), reader.read_keywords()):
        outlines = article.title_to_outlines(keyword)
        temp = {
            'SL': i,
            'Keywords': keyword,
            'Outlines': outlines,
        }
        os.makedirs('outlines', exist_ok=True)
        df = pd.DataFrame(temp, columns=['SL', 'Keywords', 'Outlines'], index=['SL'])
        if int(i) == 1:
            df.to_csv('./outlines/outlines.csv', index=False, header=True)
        else:
            df.to_csv('./outlines/outlines.csv', mode='a', index=False, header=False)


def writer_v3(article: Article):
    article.outline_to_docx()


if __name__ == '__main__':
    intput_text = """Choose Version:\n[1] Press 1 for v1\n[2] Press 2 for v2\n[3] Press 3 for v3\n[4] Press q for quit\nEnter your option: """

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
