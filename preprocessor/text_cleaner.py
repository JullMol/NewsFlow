import re
import html
from bs4 import BeautifulSoup

BOILERPLATE_PATTERNS = [
    r"Baca juga:.*?(?=\.|$)",
    r"Baca Juga:.*?(?=\.|$)",
    r"BACA JUGA:.*?(?=\.|$)",
    r"Dapatkan update berita.*?(?=\.|$)",
    r"Simak breaking news.*?(?=\.|$)",
    r"Kompas\.com\s*[-–—]\s*",
    r"KOMPAS\.com\s*[-–—]\s*",
    r"Artikel ini telah tayang.*?(?=\.|$)",
    r"Lihat Foto.*?(?=\n|$)",
    r"Halaman selanjutnya.*",
    r"Halaman:\s*\d+.*",
    r"^Penulis:.*$",
    r"^Editor:.*$",
    r"^Sumber:.*$",
    r"Ikuti berita terkini.*?(?=\.|$)",
]

ENCODING_FIXES = {
    "\u00a0": " ",      
    "\u200b": "",        
    "\u200c": "",        
    "\u200d": "",        
    "\ufeff": "",        
    "\u2018": "'",       
    "\u2019": "'",       
    "\u201c": '"',       
    "\u201d": '"',       
    "\u2013": "-",       
    "\u2014": "-",       
    "\u2026": "...",     
}


def clean_html(text: str) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    clean = soup.get_text(separator=" ")
    clean = html.unescape(clean)
    return clean


def fix_encoding(text: str) -> str:
    for old, new in ENCODING_FIXES.items():
        text = text.replace(old, new)
    return text


def remove_boilerplate(text: str) -> str:
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)
    return text


def normalize_whitespace(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return text

def clean_author_name(author: str) -> str:
    if not author:
        return "Kompas.com"
    
    author = author.strip("()[]{} :,-.|/\\")
    
    author = re.sub(r'^(penulis|editor|reporter|kontributor|oleh|author|reporter/editor)\s*[:/,-]\s*', '', author, flags=re.I)
    
    author = re.sub(r'\s+[:/,-]?\s*(penulis|editor|reporter|kontributor|oleh|author|reporter/editor)$', '', author, flags=re.I)
    
    for separator in [" | ", " / ", " - ", " – ", " — "]:
        if separator in author:
            author = author.split(separator)[0]
            
    if "/" in author:
        parts = author.split("/")
        author = parts[0]
    author = re.sub(r'^(penulis|editor|reporter|kontributor|oleh|author|reporter/editor)\s*[:/,-]\s*', '', author, flags=re.I)
    author = re.sub(r'\s+[:/,-]?\s*(penulis|editor|reporter|kontributor|oleh|author|reporter/editor)$', '', author, flags=re.I)
    
    author = re.sub(r'^kontributor\s+([a-zA-Z\s]{3,30}),\s*', '', author, flags=re.I)
    
    author = re.sub(r'[\(\[][^\]\)]*[\)\]]', '', author)
    
    author = author.strip("()[]{} :,-.|/\\")
    
    lower_author = author.lower()
    
    generic_names = [
        "kompas cyber media", "kompas.com", "kompas", "redaksi", "halaman", "admin",
        "shutterstock", "freepik", "unsplash", "istock", "pexels", "dok.", "dok",
        "afp", "reuters", "antara", "ap", "getty images", "getty", "tangkapan layar",
        "tangkapan", "youtube", "instagram", "facebook", "twitter", "tiktok", "repro"
    ]
    
    if not author or lower_author in [")", "(", "]", "[", "}", "{"] or any(x in lower_author for x in generic_names):
        return "Kompas.com"
        
    return author.title()

def clean_article(article: dict) -> dict:
    if article.get("title"):
        article["title"] = normalize_whitespace(
            fix_encoding(clean_html(article["title"]))
        )
    if article.get("content"):
        content = article["content"]
        content = clean_html(content)
        content = fix_encoding(content)
        content = remove_boilerplate(content)
        content = normalize_whitespace(content)
        article["content"] = content
        article["word_count"] = len(content.split())
    if article.get("author"):
        cleaned_author = normalize_whitespace(
            fix_encoding(clean_html(article["author"]))
        )
        article["author"] = clean_author_name(cleaned_author)
    if article.get("tags"):
        article["tags"] = [
            normalize_whitespace(fix_encoding(tag))
            for tag in article["tags"]
            if tag.strip()
        ]
    return article

def clean_batch(articles: list[dict]) -> list[dict]:
    seen_urls = set()
    cleaned = []

    for article in articles:
        url = article.get("url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)

        article = clean_article(article)

        if not article.get("content") or article.get("word_count", 0) < 20:
            continue

        cleaned.append(article)

    return cleaned


if __name__ == "__main__":
    test_article = {
        "title": "  KOMPAS.com - Berita\u00a0Test\u2014Artikel  ",
        "content": (
            "KOMPAS.com - Ini adalah konten artikel berita test. "
            "Baca juga: Artikel lain yang menarik. "
            "Ini paragraf kedua dengan informasi penting.  "
            "Dapatkan update berita pilihan dan breaking news. "
            "Paragraf terakhir berisi kesimpulan."
        ),
        "author": "  John Doe  ",
        "tags": [" Tag1 ", "Tag2", ""],
        "url": "https://test.kompas.com/read/2025/01/01/123/test",
    }

    cleaned = clean_article(test_article)
    print(f"Title: '{cleaned['title']}'")
    print(f"Content: '{cleaned['content']}'")
    print(f"Author: '{cleaned['author']}'")
    print(f"Tags: {cleaned['tags']}")