// --------------------------------------------------
// File: ~/RAG_Chatbot/frontend/src/ChatSidebar.js
// Description: 사이드바 기능 
// --------------------------------------------------

import React from "react";
import "./ChatWindow.css"; 

export default function ChatSidebar({ sessions, onNewChat, onSelectSession, onDeleteSession, currentSessionId }) {
  return (
    <div className="session-list">
      {/* ===== 새 채팅 버튼 ===== */}
      <div className="new-chat-btn" onClick={onNewChat}>새 채팅</div>

			{/* ===== 세션 목록 스크롤 영역 ===== */}
      <div style={{ overflowY: "auto", flex: 1 }}>
        {sessions.map((s) => (
          <div
            key={s.session_id}
            className={`session-item ${s.session_id === currentSessionId ? "active" : ""}`}
          >
	          {/* ===== 세션 선택 영역 ===== */}
            <div style={{ flex: 1, cursor: "pointer" }} onClick={() => onSelectSession(s.session_id)}>
              {s.name || s.session_id}
            </div>

            {/* ===== 세션 삭제 버튼 ===== */}
            <button className="delete-btn" onClick={() => onDeleteSession(s.session_id)}>X</button>
          </div>
        ))}
      </div>
    </div>
  );
}
