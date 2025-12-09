# --------------------------------------------------
# File: ~/RAG_Chatbot/Backend/main.py
# Description: FastAPI 기반 RAG 서버 메인 Entry Point (전략 기반 청킹 + CSV 정보 조회 최적화 + 기존 기능 100% 유지)
# --------------------------------------------------

from fastapi import FastAPI, UploadFile, File, Query, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import json
from datetime import datetime
import uuid
import threading
import time

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from file_handler import pdf_to_text_with_page, csv_to_text, apply_chunk_strategy
from vector_store import save_faiss, search_faiss, load_faiss_into_memory

# ===== 서버 시작 시 FAISS 로드 =====
load_faiss_into_memory()
app = FastAPI()


# ===== CORS =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== 디렉터리 =====
BASE_DIR = os.path.join(os.path.expanduser("~"), "RAG_Chatbot")
UPLOAD_DIR = os.path.join(BASE_DIR, "input")
CHAT_HISTORY_DIR = os.path.join(BASE_DIR, "chat_history_sessions")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(CHAT_HISTORY_DIR, exist_ok=True)


# ===== 세션 저장 =====
def get_session_file(session_id: str):
    return os.path.join(CHAT_HISTORY_DIR, f"{session_id}.json")

def save_chat_history(question=None, answer=None, source=None, session_id=None, system_message=None):
    record = {"timestamp": datetime.now().isoformat()}
    if system_message: record["system_message"] = system_message
    if question: record["question"] = question
    if answer: record["answer"] = answer
    if source: record["source"] = source

    session_file = get_session_file(session_id)
    history = []
    if os.path.exists(session_file):
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            pass

    history.append(record)
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ===== 요청 모델 =====
class Question(BaseModel):
    question: str

class SystemMessage(BaseModel):
    message: str
    session_id: str


@app.get("/")
def read_root():
    return {"status": "ok"}


# ===== 파일 업로드 + 임베딩 =====
@app.post("/upload_file")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            f.write(await file.read())

        chunks = []
        if file.filename.lower().endswith(".pdf"):
            pages = pdf_to_text_with_page(file_path, file.filename)
            for p in pages:
                for c in apply_chunk_strategy(p["text"], file.filename):
                    chunks.append({"page_no": p["page_no"], **c})
        else:
            text = csv_to_text(file_path)
            for c in apply_chunk_strategy(text, file.filename):
                chunks.append({"page_no": "-", **c})

        save_faiss(chunks, file_name=file.filename)
        return {"filename": file.filename, "status": "업로드 + 임베딩 완료", "chunks": len(chunks)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ===== WATCHER =====
class FileWatcher(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory: return
        _, ext = os.path.splitext(event.src_path)
        if ext.lower() not in [".pdf", ".csv"]: return

        print(f"[WATCHER] 새 파일 감지: {event.src_path}")
        time.sleep(0.5)

        try:
            filename = os.path.basename(event.src_path)
            chunks = []

            if filename.lower().endswith(".pdf"):
                pages = pdf_to_text_with_page(event.src_path, filename)
                for p in pages:
                    for c in apply_chunk_strategy(p["text"], filename):
                        chunks.append({"page_no": p["page_no"], **c})
            else:
                text = csv_to_text(event.src_path)
                for c in apply_chunk_strategy(text, filename):
                    chunks.append({"page_no": "-", **c})

            save_faiss(chunks, file_name=filename)
            print(f"[WATCHER] {filename} 자동 임베딩 완료 (chunks={len(chunks)})")
        except Exception as e:
            print(f"[WATCHER] 자동 임베딩 오류: {e}")

def start_watcher():
    observer = Observer()
    observer.schedule(FileWatcher(), UPLOAD_DIR, recursive=False)
    observer.start()
    print(f"[WATCHER] input 폴더 감시 시작: {UPLOAD_DIR}")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

threading.Thread(target=start_watcher, daemon=True).start()


# ===== 세션 API =====
@app.post("/new_chat_session")
def new_chat_session():
    session_id = str(uuid.uuid4())
    with open(get_session_file(session_id), "w", encoding="utf-8") as f:
        json.dump([], f)
    return {"session_id": session_id}


@app.get("/list_chat_sessions")
def list_chat_sessions():
    sessions = []
    for f in os.listdir(CHAT_HISTORY_DIR):
        if f.endswith(".json"):
            sessions.append(f.replace(".json", ""))
    return {"sessions": sessions}


@app.get("/get_chat_history/{session_id}")
def get_chat_history(session_id: str):
    session_file = get_session_file(session_id)
    if os.path.exists(session_file):
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                return {"session_id": session_id, "history": json.load(f)}
        except:
            return {"session_id": session_id, "history": []}
    return {"session_id": session_id, "history": []}


@app.delete("/delete_chat_session/{session_id}")
def delete_chat_session(session_id: str):
    if not session_id or session_id == "undefined":
        return {"status": "skip", "reason": "invalid session_id"}
    session_file = get_session_file(session_id)
    if os.path.exists(session_file):
        os.remove(session_file)
        return {"status": "삭제 완료", "session_id": session_id}
    return {"status": "해당 세션 없음", "session_id": session_id}


@app.post("/save_system_message")
def save_system_message(data: SystemMessage):
    save_chat_history(system_message=data.message, session_id=data.session_id)
    return {"status": "ok"}


# ===== 답변 선택 알고리즘 (CSV 정보 조회 최적화) =====
def extract_answer(chunk: dict):
    # CSV 행 기반 JSON → 사람이 읽을 수 있는 형식으로 반환
    if "text" not in chunk or not chunk.get("text"):
        lines = []
        for k, v in chunk.items():
            if k in ["id", "page_no", "file_name", "hash"]:
                continue
            lines.append(f"{k}: {v}")
        return "\n".join(lines)

    # 일반 청킹(text 필드가 존재)
    return chunk["text"]


# ===== RAG 검색 =====
SIMILARITY_THRESHOLD = 5.0

@app.post("/rag_query")
def rag_query(q: Question, session_id: str = Query(None)):
    try:
        if not session_id or session_id == "undefined":
            session_id = str(uuid.uuid4())
            with open(get_session_file(session_id), "w", encoding="utf-8") as f:
                json.dump([], f)

        results = search_faiss(q.question, top_k=3)
        if not results or all(r["score"] > SIMILARITY_THRESHOLD for r in results):
            answer = f"문서에서 '{q.question}' 관련 내용을 찾을 수 없습니다."
            save_chat_history(q.question, answer, None, session_id)
            return {"session_id": session_id, "answer": answer, "source": None}

        best = min(results, key=lambda x: x["score"])
        answer = extract_answer(best)
        source = f"{best['file_name']} | {best.get('page_no','-')}"

        save_chat_history(q.question, answer, source, session_id)
        return {"session_id": session_id, "answer": answer, "source": source}

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
