from bs4 import BeautifulSoup

import os

from PIL import Image

from io import BytesIO

import cloudscraper

import re

import js2py

from playwright.sync_api import sync_playwright

from time import sleep

from base64 import b64decode

import concurrent.futures

from math import ceil
# zinmanga.com 1 | need referer | 1
# harimanga.com 1 | 1
# kunmanga.com 1 | 1
# teenmanhua.com 1 | 1
# aquamanga.com 1 | wtf | 1
# fanfox.net 1 | different search | 1
# coffeemanga.com 1 | 1
# mangachill.me 1

browser = {'browser': 'firefox','platform': 'windows', 'mobile': False}

scraper = cloudscraper.create_scraper(browser=browser)

fanfox_chapterid_pattern = re.compile(r'var chapterid *= *(\d+);')
fanfox_imagecount_pattern = re.compile(r'var imagecount *= *(\d+);')

context = js2py.EvalJs()

browser = None
browser_page = None

def get_html(url):
    if 'aquamanga.com' in url:
        browser_page.goto(url)
        while not browser_page.query_selector('.site-content'):
            sleep(1)
        html = browser_page.content()
    else:
        cookies = {
            'isAdult': '1'
        }
        html = scraper.get(url, cookies=cookies).text
    return html

def get_fanfox_chapter_images_src(chapter_url):
    html = get_html(chapter_url)
    headers = {
        'referer': chapter_url
    }
    cookies = {
        'isAdult': '1'
    }
    chapter_id = re.search(fanfox_chapterid_pattern, html).group(1)
    image_count = int(re.search(fanfox_imagecount_pattern, html).group(1))

    for i in range(1, image_count+1):
        js = scraper.get(
            f'{chapter_url}chapterfun.ashx',
            data={
                'cid': chapter_id,
                'page': i,
                'key': 'asd'},
            headers=headers,
            cookies=cookies
            ).text
        context.execute(js)
        yield {
            'name': f'{i}.jpg',
            'src': f'https:{context.d[0]}',
        }

def get_chapter_images(chapter_url):
    chapter_html = get_html(chapter_url)
    chapter_soup = BeautifulSoup(chapter_html, features='html.parser')
    # with open('images.html', 'w', encoding='utf-8') as f:
    #     f.write(chapter_soup.prettify())
    if 'fanfox.net' in chapter_url:
        chapter_url_ = chapter_url[:chapter_url.rindex('/')+1]
        for img in get_fanfox_chapter_images_src(chapter_url_):
            yield img
    else:
        images = chapter_soup.select('img[id^="image"]')

        for el in images:
            if '1stkissmanga.io' in chapter_url:
                src = el.get('data-lazy-src')
                if not src:
                    continue
            else:
                src = el.get('src')

                if not src:
                    src = el['data-src']

            yield {
                    'name': f"{int(el['id'][el['id'].rindex('-')+1:])+1}.jpg",
                    'src': src
                }

def parse_fanfox_chapter(chapter):
    chapter_count = chapter.split()[0][chapter.index('.')+1:].lstrip('0')

    if not chapter_count:
        chapter_count = '0'

    return 'Chapter ' + chapter_count.replace('.', ' ')

def get_chapters(url, referer, reverse):
    html = get_html(url)
    soup = BeautifulSoup(html, features='html.parser')
    # with open('chapter.html', 'w', encoding='utf-8') as f:
    #     f.write(soup.prettify())
    if 'fanfox.net' in referer:
        selector = 'ul.detail-main-list > li > a[href]'
    else:
        selector = '.wp-manga-chapter > a[href]'
    
    chapter_elements = soup.select(selector)
    
    if not reverse:
        chapter_elements = soup.select(selector)[::-1]
    for el in chapter_elements:
        if 'fanfox.net' in referer:
            chapter_string = el.find('p', class_='title3').string
            data = {
                'name': parse_fanfox_chapter(chapter_string),
                'href': f"{referer}{el['href']}",
            }
        else:
            data = {
                'name': el.string.strip(),
                'href': el['href'],
            }
        yield data

def chapter_dir_name(name):
    return name.lower().replace(' ', '-')

def convert_to_jpg_and_save(io, path, silent):
    img = Image.open(io).convert('RGB')
    width, height = img.size
    max_size = 2**16 - 1
    
    if width > max_size:
        ratio = width / (max_size)
        new_width = int(width * ratio)
        new_height = int(height * ratio)
        img.resize((new_width, new_height))

    if height > max_size:
        for i in range(ceil(height / (max_size))):
            subimg_path = f"{path[:path.rindex('.')]}-{i+1}{path[path.rindex('.'):]}"
            subimg = img.crop((0, max_size*i, width, min(max_size*(i+1), height)))
            subimg.save(subimg_path)
            
            if not silent:
                print(f'Saved {subimg_path}')
    else:
        img.save(path)
        if not silent:
            print(f'Saved {path}')

def get_referer(url):
    return '/'.join(url.split('/')[:3])

def download_image_and_recode(url, path, referer, silent):
    if 'aquamanga.com' in referer:
        browser_page.goto(url)
        while browser_page.query_selector('script'):
            sleep(1)
        image_element = browser_page.locator('img')
        image_b64 = image_element.evaluate("""element => {
        var cnv = document.createElement('canvas');
        cnv.width = element.naturalWidth;
        cnv.height = element.naturalHeight;
        cnv.getContext('2d').drawImage(element, 0, 0, element.naturalWidth, element.naturalHeight);
        return cnv.toDataURL().substring(22)
        }""")
        with open(path, 'wb') as f:
            f.write(b64decode(image_b64))
        return

    headers = {
        'referer': referer
    }
    cookies = {
        'isAdult': '1'
    }
    image = scraper.get(url, headers=headers, cookies=cookies, stream=True).content

    if url.endswith('.jpg'):
        with open(path, 'wb') as f:
            f.write(image)
        
        if not silent:
            print('Saved', path)
    else:
        convert_to_jpg_and_save(BytesIO(image), path, silent)
    

def parse_manga(url, parse_to_dir='./', silent=False, reverse=False, max_workers=1):
    global browser, browser_page
    if 'aquamanga.com' in url:
        playwright = sync_playwright().__enter__()
        browser = playwright.webkit.launch(headless=True)
        browser_page = browser.new_page()

    parse_to_dir = os.path.relpath(parse_to_dir)
    os.makedirs(parse_to_dir, exist_ok=True)
    
    existing_chapters_dirs = os.listdir(parse_to_dir)
    referer = get_referer(url)
    chapters = get_chapters(url, referer, reverse)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for chapter in chapters:
            futures = []
            chapter_dir = os.path.relpath(chapter_dir_name(chapter['name']))

            if chapter_dir in existing_chapters_dirs:
                continue

            chapter_dir = os.path.join(parse_to_dir, chapter_dir)
            os.makedirs(chapter_dir, exist_ok=True)

            chapter_images = get_chapter_images(chapter['href'])
            for image in chapter_images:
                image_path = os.path.join(chapter_dir, image['name'])
                futures.append(
                    executor.submit(
                        download_image_and_recode, image['src'], image_path, referer, silent
                    )
                )
            for future in concurrent.futures.as_completed(futures):
                future.result()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description=(
            'Downloads images from manga sites and saves them'
            'to appropriate chapter folder'))
    parser.add_argument('url', help='URL of manga, which has to be parsed.')
    parser.add_argument('-d', '--parse_to_dir', nargs='?', help='Path to directory, where all chapters will be parsed.', default='./')
    parser.add_argument('-s', '--silent', action='store_true', help='Silent parsing.')
    parser.add_argument('-r', '--reverse', action='store_true', help='Start parsing manga from the last chapter.')
    parser.add_argument('-w', '--max-workers', action='store', help='Number of workers', default=1, type=int)
    args = parser.parse_args()

    url = args.url
    parse_to_dir = args.parse_to_dir
    silent = args.silent
    reverse = args.reverse
    max_workers = args.max_workers

    try:
        parse_manga(url, parse_to_dir, silent, reverse, max_workers)
    except KeyboardInterrupt:
        quit()
