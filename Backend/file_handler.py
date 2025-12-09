# --------------------------------------------------
# File: ~/RAG_Chatbot/Backend/file_handler.py
# Description: PDF / CSV 텍스트 추출 + 전략 기반 청킹 엔진
# --------------------------------------------------

import fitz  # PyMuPDF
import re
import csv
import os
import json
from typing import List, Dict

BASE_DIR = os.path.join(os.path.expanduser("~"), "RAG_Chatbot")
CONFIG_PATH = os.path.join(BASE_DIR, "chunk_config.json")

# ========== 기본 CONFIG ==========
DEFAULT_CONFIG = {
    "default": {
        "strategy": "regular",
        "chunk_size": 800,
        "overlap": 80
    },
    "pdf": {},
    "csv": {}
}

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return DEFAULT_CONFIG


# ========== PDF 페이지 텍스트 추출 ==========
def pdf_to_text_with_page(pdf_path: str, file_name: str) -> List[Dict]:
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        text = page.get_text()
        text = re.sub(r"\s+", " ", text).strip()
        pages.append({
            "page_no": page.number + 1,
            "text": text,
            "file_name": file_name
        })
    doc.close()
    return pages


# ========== CSV → 텍스트 ==========
def csv_to_text(file_path: str) -> str:
    rows = []
    with open(file_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            rows.append(",".join(row))
    return "\n".join(rows)


# --------------------------------------------------
# 🔥 전략 기반 청킹 엔진
# --------------------------------------------------

def get_chunk_strategy(file_name: str):
    cfg = load_config()
    ext = "pdf" if file_name.lower().endswith(".pdf") else "csv"
    return cfg.get(ext, {}).get(file_name, cfg.get("default", {}))


# regular 전략 유지
def chunk_regular(text: str, cfg) -> List[Dict]:
    chunk_size = cfg.get("chunk_size", 800)
    overlap = cfg.get("overlap", 80)
    blocks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        blocks.append({"text": text[start:end]})
        start += max(chunk_size - overlap, 1)
    return blocks

# --------------------------------------------------
# 🔥 법률 조문 파서 (조 / 항 / 호 단위 청킹)
# --------------------------------------------------
def parse_law_structure(text: str) -> List[Dict]:
    """조 / 항 / 호 단위 분리 → chapter/title/text 구조"""
    article_pattern = r"(제\d+조)\s*\((.*?)\)"
    articles = list(re.finditer(article_pattern, text))
    results = []

    for i, match in enumerate(articles):
        chapter = match.group(1)
        title = match.group(2)
        start = match.start()
        end = articles[i + 1].start() if i + 1 < len(articles) else len(text)
        body = text[start:end].strip()

        # 항·호 단위 분리
        sub_items = re.split(r"\s+(\d+\.\s*)", body)
        if len(sub_items) > 1:
            merged = []
            buffer = ""
            for part in sub_items:
                if re.match(r"\d+\.\s*", part):
                    if buffer:
                        merged.append(buffer)
                    buffer = part
                else:
                    buffer += part
            if buffer:
                merged.append(buffer)

            for block in merged:
                results.append({
                    "chapter": chapter,
                    "title": title,
                    "text": block.strip()
                })
        else:
            results.append({
                "chapter": chapter,
                "title": title,
                "text": body
            })
    return results

# law 전략 (기존 유지)
def chunk_law(text: str) -> List[Dict]:
    return parse_law_structure(text)


# CSV 전략 (기존 유지)
def chunk_column_record(text: str, cfg) -> List[Dict]:
    mapping = cfg.get("mapping", {})
    rows = [line.split(",") for line in text.splitlines() if line.strip()]

    chunks = []
    for row in rows:
        obj = {}
        for key, idx in mapping.items():
            obj[key] = row[idx] if idx < len(row) else None
        chunks.append(obj)
    return chunks


# --------------------------------------------------
# 🔥 새로 추가: PDF 페이지를 1개의 청크로 그대로 사용
# --------------------------------------------------
def chunk_page(text: str) -> List[Dict]:
    return [{"text": text}]   # 페이지 전체를 그대로 하나의 청크로 반환


# --------------------------------------------------
# apply_chunk_strategy → 기존 유지 + page 전략 1줄만 추가
# --------------------------------------------------
def apply_chunk_strategy(raw_text: str, file_name: str) -> List[Dict]:
    cfg = get_chunk_strategy(file_name)
    strategy = cfg.get("strategy", "regular")

    if strategy == "law":
        return chunk_law(raw_text)
    elif strategy == "column_record":
        return chunk_column_record(raw_text, cfg)
    elif strategy == "page":
        return chunk_page(raw_text)         # 🔥 추가된 페이지 전략
    else:
        return chunk_regular(raw_text, cfg)


# 하위 호환 유지
def chunk_text_dynamic(text: str, file_name: str) -> List[Dict]:
    return apply_chunk_strategy(text, file_name)

chunk_text = chunk_text_dynamic
