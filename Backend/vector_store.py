# --------------------------------------------------
# File: ~/RAG_Chatbot/Backend/vector_store.py
# Description: FAISS 기반 벡터 DB + 전략 기반 청킹 대응 완전 지원
# --------------------------------------------------

import faiss
import json
import os
import hashlib
import numpy as np
from sentence_transformers import SentenceTransformer

# 경로 설정
BASE_DIR = os.path.join(os.path.expanduser("~"), "RAG_Chatbot")
DB_DIR = os.path.join(BASE_DIR, "faiss_db")
os.makedirs(DB_DIR, exist_ok=True)

FAISS_PATH = os.path.join(DB_DIR, "vector.index")
METADATA_PATH = os.path.join(DB_DIR, "metadata.json")
MODEL_NAME = "BAAI/bge-m3"

# 전역 변수
faiss_index = None
metadata = []
embedder = None


# ===== Embedding 모델 & FAISS 로드 =====
def load_faiss_into_memory():
    global faiss_index, metadata, embedder

    print("🔵 Loading embedding model on CPU...")
    embedder = SentenceTransformer(MODEL_NAME, device="cpu")
    print("🟢 Embedding model loaded.")

    # Load FAISS
    if os.path.exists(FAISS_PATH):
        try:
            faiss_index = faiss.read_index(FAISS_PATH)
            print(f"🟢 FAISS index loaded. Total vectors: {faiss_index.ntotal}")
        except Exception as e:
            print(f"❌ Failed to load FAISS index: {e}")
            faiss_index = None
    else:
        print("⚪ No FAISS index found. Starting fresh.")
        faiss_index = None

    # Load metadata
    if os.path.exists(METADATA_PATH):
        try:
            with open(METADATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                metadata[:] = data if isinstance(data, list) else []
            print(f"🟢 Metadata loaded. Total chunks = {len(metadata)}")
        except Exception as e:
            print(f"❌ Metadata load error: {e}")
            metadata[:] = []
    else:
        metadata[:] = []
        print("⚪ No metadata found. Starting fresh.")


# ===== Metadata 저장 =====
def save_metadata():
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


# ===== chunk → 임베딩 문자열 변환 =====
def extract_text_for_embedding(chunk: dict) -> str:
    """
    CSV 레코드처럼 text 필드가 없는 chunk도 지원하도록
    가장 긴 문자열을 대표 텍스트로 선택.
    """
    if "text" in chunk and isinstance(chunk["text"], str) and chunk["text"].strip():
        return chunk["text"]

    # 문자열 필드들 중 가장 긴 값 선택
    values = [v for v in chunk.values() if isinstance(v, str)]
    if values:
        return max(values, key=len)

    # 문자열 필드가 하나도 없으면 JSON을 문자열로 변환
    return json.dumps(chunk, ensure_ascii=False)


# ===== 임베딩 생성 =====
def embed_texts(text_list):
    embeddings = embedder.encode(text_list, convert_to_numpy=True, batch_size=16)
    return embeddings.astype("float32")


# ===== 벡터 / 메타데이터 저장 =====
def save_faiss(chunks, file_name: str):
    """
    chunks = apply_chunk_strategy() 결과 그대로 들어옴
    JSON 구조가 모두 다르더라도 저장 가능해야 함
    """
    global faiss_index, metadata

    if chunks is None or len(chunks) == 0:
        print(f"⚠ 저장할 청크 없음: {file_name}")
        return

    existing_hashes = {m.get("hash", "") for m in metadata}

    embedding_texts = []
    new_meta = []

    for c in chunks:
        embed_text = extract_text_for_embedding(c)
        h = hashlib.md5(embed_text.encode("utf-8")).hexdigest()

        if h in existing_hashes:
            continue

        embedding_texts.append(embed_text)
        new_meta.append({
            "id": len(metadata) + len(new_meta),
            "file_name": file_name,
            **c,               # 🔥 청크 JSON 전체 그대로 보존
            "hash": h
        })

    if not embedding_texts:
        print("⚪ 모든 청크가 중복 — 저장 생략")
        return

    vectors = embed_texts(embedding_texts)
    dim = vectors.shape[1]

    if faiss_index is None or faiss_index.ntotal == 0:
        index = faiss.IndexFlatL2(dim)
        index.add(vectors)
        faiss_index = index
    else:
        existing_vectors = faiss_index.reconstruct_n(0, faiss_index.ntotal)
        index = faiss.IndexFlatL2(dim)
        index.add(existing_vectors)
        index.add(vectors)
        faiss_index = index

    metadata.extend(new_meta)

    faiss.write_index(faiss_index, FAISS_PATH)
    save_metadata()

    print(f"🟢 저장 완료 — 파일: {file_name}, 새 청크: {len(new_meta)}, 전체: {faiss_index.ntotal}")


# ===== 전체 재인덱싱 =====
def rebuild_faiss_from_metadata(new_metadata):
    global metadata, faiss_index

    cleaned = []
    for i, m in enumerate(new_metadata):
        row = dict(m)
        row["id"] = i
        cleaned.append(row)

    metadata = cleaned

    if not metadata:
        dim = embedder.get_sentence_embedding_dimension()
        faiss_index = faiss.IndexFlatL2(dim)
        faiss.write_index(faiss_index, FAISS_PATH)
        save_metadata()
        print("🟢 빈 인덱스로 초기화됨")
        return

    text_list = [extract_text_for_embedding(m) for m in metadata]
    vectors = embedder.encode(text_list, convert_to_numpy=True).astype("float32")

    dim = vectors.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(vectors)
    faiss_index = index

    faiss.write_index(faiss_index, FAISS_PATH)
    save_metadata()

    print(f"🟢 전체 재인덱싱 완료 — 총 벡터: {faiss_index.ntotal}")


# ===== 검색 =====
def search_faiss(query, top_k=3):
    global metadata, faiss_index

    if faiss_index is None:
        raise RuntimeError("FAISS index not initialized!")

    q_vec = embedder.encode([query], convert_to_numpy=True).astype("float32")
    D, I = faiss_index.search(q_vec, top_k)

    results = []
    for idx, score in zip(I[0], D[0]):
        if 0 <= idx < len(metadata):
            chunk = metadata[idx]
            results.append({**chunk, "score": float(score)})

    return results
