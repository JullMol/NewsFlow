import re
from collections import Counter

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

PROVINCES = [
    "Aceh","Sumatera Utara","Sumatera Barat","Riau","Jambi",
    "Sumatera Selatan","Bengkulu","Lampung","Bangka Belitung",
    "Kepulauan Riau","DKI Jakarta","Jakarta","Jawa Barat",
    "Jawa Tengah","DI Yogyakarta","Yogyakarta","Jawa Timur",
    "Banten","Bali","NTB","NTT","Kalimantan Barat",
    "Kalimantan Tengah","Kalimantan Selatan","Kalimantan Timur",
    "Kalimantan Utara","Sulawesi Utara","Sulawesi Tengah",
    "Sulawesi Selatan","Sulawesi Tenggara","Gorontalo",
    "Sulawesi Barat","Maluku","Maluku Utara","Papua","Papua Barat",
]
CITIES = [
    "Jakarta","Surabaya","Bandung","Medan","Semarang","Makassar",
    "Palembang","Tangerang","Depok","Bekasi","Bogor","Malang",
    "Yogyakarta","Solo","Denpasar","Manado","Pontianak",
    "Banjarmasin","Padang","Pekanbaru","Batam","Balikpapan",
    "Samarinda","Kupang","Ambon","Jayapura","Mataram","Serang",
]
COUNTRIES = [
    "Indonesia","Malaysia","Singapura","Thailand","Filipina",
    "Vietnam","China","Tiongkok","Jepang","Korea Selatan",
    "India","Australia","Amerika Serikat","AS","Rusia","Inggris",
    "Prancis","Jerman","Italia","Arab Saudi","Iran","Turki",
    "Mesir","Israel","Palestina","Ukraina","Brasil",
]
ALL_LOCATIONS = set(PROVINCES + CITIES + COUNTRIES)

KNOWN_ORGS = [
    "DPR","DPRD","MPR","MK","MA","KPK","KPU","Bawaslu",
    "TNI","Polri","BIN","BNPB","BMKG","BPOM","OJK",
    "Bank Indonesia","Kemendikbud","Kemkes","Kemenkeu",
    "PBB","WHO","UNESCO","ASEAN","FIFA",
    "PDI-P","Golkar","Gerindra","PKB","Nasdem","Demokrat",
    "PKS","PPP","PAN","PSI","PLN","Pertamina","Telkom",
    "BCA","BRI","BNI","Mandiri","Google","Microsoft","Apple",
]
ORG_PATTERNS = [
    r"PT\s+[A-Z]\w[\w\s]{2,20}",
    r"Kementerian\s+[A-Z]\w[\w\s]{2,20}",
    r"Universitas\s+[A-Z]\w[\w\s]{2,20}",
]

KNOWN_PERSONS = [
    "Joko Widodo","Jokowi","Prabowo Subianto","Prabowo",
    "Gibran Rakabuming","Megawati","Anies Baswedan","Anies",
    "Ganjar Pranowo","Ganjar","Luhut","Sri Mulyani",
    "Erick Thohir","Mahfud MD","Airlangga Hartarto",
    "Ridwan Kamil","AHY","Budi Gunawan","Retno Marsudi",
]
TITLES = [
    "Presiden","Menteri","Gubernur","Bupati","Wali Kota",
    "Walikota","Ketua","Direktur","Jenderal","Kapolri",
    "Prof","Dr","Ir",
]

def extract_entities(text: str) -> list[dict]:
    entities = []
    # Locations
    for loc in ALL_LOCATIONS:
        pat = r"\b" + re.escape(loc) + r"\b"
        m = re.findall(pat, text, re.IGNORECASE)
        if m:
            entities.append({"name": loc, "type": "LOCATION", "count": len(m)})
    # Organizations
    for org in KNOWN_ORGS:
        pat = r"\b" + re.escape(org) + r"\b"
        m = re.findall(pat, text)
        if m:
            entities.append({"name": org, "type": "ORGANIZATION", "count": len(m)})
    for pat in ORG_PATTERNS:
        for m in re.findall(pat, text):
            name = m.strip()
            if len(name) > 3 and not any(e["name"] == name for e in entities):
                entities.append({"name": name, "type": "ORGANIZATION", "count": 1})
    # Persons
    for person in KNOWN_PERSONS:
        pat = r"\b" + re.escape(person) + r"\b"
        m = re.findall(pat, text)
        if m:
            entities.append({"name": person, "type": "PERSON", "count": len(m)})
    for title in TITLES:
        pat = r"\b" + re.escape(title) + r"\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})"
        for m in re.findall(pat, text):
            name = m.strip()
            if len(name) > 2 and not any(e["name"] == name for e in entities):
                entities.append({"name": name, "type": "PERSON", "count": 1})
    return entities


def extract_article_entities(articles: list[dict]) -> list[dict]:
    print(f"[NER] Extracting entities from {len(articles)} articles")
    for article in articles:
        text = f"{article.get('title', '')}. {article.get('content', '')}"
        ents = extract_entities(text)
        article["entities"] = ents
        article["persons"] = [e["name"] for e in ents if e["type"] == "PERSON"]
        article["organizations"] = [e["name"] for e in ents if e["type"] == "ORGANIZATION"]
        article["locations"] = [e["name"] for e in ents if e["type"] == "LOCATION"]
    return articles


if __name__ == "__main__":
    test = "Presiden Prabowo menghadiri KTT ASEAN di Jakarta. DPR menyetujui anggaran."
    for e in extract_entities(test):
        print(f"  [{e['type']}] {e['name']} (x{e['count']})")