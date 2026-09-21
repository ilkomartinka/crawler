import requests
from bs4 import BeautifulSoup
import json
import time
from urllib.parse import urljoin, urlparse


# Start directly in the news section
START_URL = "https://www.idnes.cz/zpravy"
DOMAIN = "idnes.cz"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

COOKIES = {
    "dCMP": "mafra=1111,all=1,reklama=1,part=0,cpex=1,google=1,gemius=1,id5=1,next=0000,onlajny=0000,jenzeny=0000,"
            "databazeknih=0000,autojournal=0000,skodahome=0000,skodaklasik=0000,groupm=1,piano=1,seznam=1,geozo=0,"
            "czaid=1,click=1,verze=2,"
}

visited = set()
queue = [START_URL]

def is_valid_url(url):
    parsed = urlparse(url)
    if DOMAIN not in parsed.netloc:
        return False
    
    bad_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.mp4', '.css', '.js']
    if any(url.lower().endswith(ext) for ext in bad_extensions):
        return False
        
    # Ignore discussion forums, galleries, etc.
    if '/diskuse' in url or '/foto' in url:
        return False
        
    return True

def parse_article(soup, url):
    # 1. Title
    title_tag = soup.find('h1')
    if not title_tag:
        return None # Not an article
    title = title_tag.text.strip()

    # 2. Content
    content_div = soup.find('div', id='art-text')
    if not content_div:
        content_div = soup.find('div', class_='bbtext')
    if not content_div:
        content_div = soup.find('div', class_='opener')
        
    if not content_div:
        return None # No text found

    # Extract clean paragraphs
    paragraphs = content_div.find_all('p')
    if paragraphs:
        content = "\n".join([p.text.strip() for p in paragraphs])
    else:
        content = content_div.text.strip()

    if len(content) < 50:
        return None # Too short, probably not an article

    # 3. Metadata
    date_tag = soup.find('meta', property='article:published_time')
    date_iso = date_tag['content'] if date_tag else ""

    category_tag = soup.find('meta', attrs={'name': 'keywords'})
    category = category_tag['content'] if category_tag else ""

    # 4. Comments and Photos
    comments_count = 0
    moot = soup.find('a', id='moot-linkinc')
    if moot and moot.text.strip().isdigit():
        comments_count = int(moot.text.strip())

    photos_count = len(soup.find_all('img'))

    return {
        "url": url,
        "title": title,
        "category": category,
        "comments": comments_count,
        "photos": photos_count,
        "date": date_iso,
        "content": content
    }

def run_crawler():
    with open("idnes_data.jsonl", "a", encoding="utf-8") as file:
        while queue:
            url = queue.pop(0)
            
            if url in visited:
                continue
                
            print(f"Checking: {url}")
            
            try:
                response = requests.get(url, headers=HEADERS, cookies=COOKIES, timeout=10)
                visited.add(url)
                
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                article_data = parse_article(soup, url)
                
                if article_data:
                    json_line = json.dumps(article_data, ensure_ascii=False)
                    file.write(json_line + "\n")
                    file.flush() # Save immediately!
                    print(f"  [+] SUCCESS! Saved article: {article_data['title'][:40]}...")
                
                # Find new links
                for a_tag in soup.find_all('a', href=True):
                    new_url = urljoin(url, a_tag['href'])
                    new_url = new_url.split('#')[0]
                    
                    if is_valid_url(new_url) and new_url not in visited:
                        # Smart sorting: if it looks like an article (has .A in URL), put it FIRST in queue
                        if ".A" in new_url:
                            queue.insert(0, new_url)
                        else:
                            queue.append(new_url)
                            
            except Exception as e:
                print(f"Error processing {url}: {e}")
            
            time.sleep(0.5)

if __name__ == "__main__":
    run_crawler()
