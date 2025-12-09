// --------------------------------------------------
// File: ~/RAG_Chatbot/frontend/src/ChatWindow.js
// Description: 채팅창 컴포넌트 구현
// --------------------------------------------------

import React, { useState, useRef, useEffect } from "react";
import "./ChatWindow.css";
import { queryRag, newChatSession, deleteChatSession, listChatSessions, getChatHistory, saveSystemMessage } from "./api";
import ChatSidebar from "./ChatSidebar";
import { FAQ_CATEGORIES } from "./faq";

/* ===== ChatWindow 컴포넌트 ===== */
function ChatWindow({ closeChat }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState(null);
  const [sessions, setSessions] = useState([]);
  const messagesEndRef = useRef(null);

	/* ===== 메시지 자동 스크롤 ===== */
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

	/* ===== 초기 세션 목록 로드 ===== */
  useEffect(() => {
    fetchSessions();
  }, []);

  const fetchSessions = async () => {
    try {
      const data = await listChatSessions();
      const ids = data.sessions || [];
      const sessionObjs = [];

      for (let id of ids) {
        try {
          const h = await getChatHistory(id);
          const history = h.history || [];
          let name = "새 세션";
          let lastTimestamp = Date.now();

          if (history.length > 0) {
            const firstItem = history.find(item => item.question || item.system_message);
            const firstQ = firstItem?.question || firstItem?.system_message || "";
            name = firstQ.split(" ").slice(0, 4).join(" ") || id;
            const lastItem = history[history.length - 1];
            lastTimestamp = new Date(lastItem.timestamp).getTime();
          }

          sessionObjs.push({ session_id: id, name, lastTimestamp });
        } catch (err) {
          sessionObjs.push({ session_id: id, name: id, lastTimestamp: Date.now() });
        }
      }

      sessionObjs.sort((a, b) => b.lastTimestamp - a.lastTimestamp);
      setSessions(sessionObjs);
    } catch (err) {
      console.error(err);
    }
  };

	/* ===== 새 채팅 세션 생성 ===== */
  const handleNewChat = async () => {
    try {
      const res = await newChatSession();
      const sid = res.session_id;
      setSessionId(sid);

      const initialMsg = {
        sender: "bot",
        text: "저는 온누리 상품권 관련 챗봇입니다. 무엇을 도와드릴까요?",
        buttons: ["업무조회", "가맹점조회"]
      };

      setMessages([initialMsg]);

      await saveSystemMessage(initialMsg.text, sid, initialMsg.buttons);

      const newSession = { session_id: sid, name: "새 세션", lastTimestamp: Date.now() };
      setSessions(prev => [newSession, ...prev]);
    } catch (err) {
      console.error(err);
    }
  };

	/* ===== 세션 삭제 ===== */
  const handleDeleteSession = async (sid) => {
    try {
      await deleteChatSession(sid);
      setSessions(prev => prev.filter(s => s.session_id !== sid));
      if (sid === sessionId) {
        setSessionId(null);
        setMessages([]);
      }
    } catch (err) {
      console.error(err);
    }
  };

	/* ===== 세션 선택 ===== */
  const handleSelectSession = async (sid) => {
    try {
      setSessionId(sid);
      const res = await getChatHistory(sid);
      const history = res.history || [];
      const msgs = [];
      for (let item of history) {
        if (item.system_message) msgs.push({ sender: "bot", text: item.system_message, buttons: item.buttons });
        if (item.question) msgs.push({ sender: "user", text: item.question });
        if (item.answer) msgs.push({ sender: "bot", text: item.answer });
      }
      setMessages(msgs);
    } catch (err) {
      console.error(err);
    }
  };

	/* ===== 메시지 전송 ===== */
  const sendMessage = async (questionText) => {
    const userText = questionText || input;
    if (!userText.trim()) return;

    setInput("");
    setMessages(prev => [...prev, { sender: "user", text: userText }]);

    try {
      const res = await queryRag(userText, sessionId);
      const sid = res.session_id || sessionId;
      if (!sessionId && sid) setSessionId(sid);

      const answer = res.answer || "답변을 가져올 수 없습니다.";

      setMessages(prev => [
        ...prev,
        { sender: "bot", text: answer }
      ]);

      const timestamp = Date.now();
      setSessions(prev => {
        const found = prev.find(s => s.session_id === sid);
        const keyword = userText.split(" ").slice(0, 4).join(" ");
        if (found) {
          return prev.map(s =>
            s.session_id === sid ? { ...s, name: s.name === "새 세션" ? keyword : s.name, lastTimestamp: timestamp } : s
          );
        } else {
          return [{ session_id: sid, name: keyword, lastTimestamp: timestamp }, ...prev];
        }
      });

      fetchSessions();
    } catch (err) {
      console.error(err);
      setMessages(prev => [...prev, { sender: "bot", text: "오류 발생" }]);
    }
  };

	/* ===== 버튼 클릭 처리 (FAQ/업무/가맹점) ===== */
  const handleButtonClick = async (text) => {
    if (!sessionId) return;

    if (text === "업무조회") {
      const userMsg = "온누리 상품권 관련 업무 조회하겠습니다.";
      const botMsg = "다음으로 무엇을 알고 싶으신가요?";
      const botButtons = FAQ_CATEGORIES.map(f => f.category);

      setMessages(prev => [
        ...prev,
        { sender: "user", text: userMsg },
        { sender: "bot", text: botMsg, buttons: botButtons }
      ]);

      await saveSystemMessage(userMsg, sessionId);
      await saveSystemMessage(botMsg, sessionId, botButtons);

    } else if (text === "가맹점조회") {
      const userMsg = "온누리 상품권 가맹점 정보 조회하겠습니다.";
      const botMsg = "아래 항목 중 한가지 이상 정보를 입력해주세요.\n가맹점코드:\n가맹점명:\n가맹주성함:\n가맹주번호:\n사업자번호:";

      setMessages(prev => [
        ...prev,
        { sender: "user", text: userMsg },
        { sender: "bot", text: botMsg }
      ]);

      await saveSystemMessage(userMsg, sessionId);
      await saveSystemMessage(botMsg, sessionId);

    } else {
      const faqItem = FAQ_CATEGORIES.find(f => f.category === text);
      if (faqItem) {
        sendMessage(faqItem.question);
      }
    }
  };

	/* ===== 렌더링 ===== */
  return (
    <div className="chat-window">
	    {/* ===== 사이드바 ===== */}
      <ChatSidebar
        sessions={sessions}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        currentSessionId={sessionId}
      />

			{/* ===== 채팅 메인 ===== */}
      <div className="chat-main">
	      {/* ---- 헤더 ---- */}
        <div className="chat-header">
          <div className="chat-title">Chatbot</div>
          <button className="close-btn" onClick={closeChat}>✕</button>
        </div>

				{/* ---- 메시지 영역 ---- */}
        <div className="chat-body">
          {messages.map((m, idx) => (
            <div key={idx} className={`chat-message ${m.sender === "user" ? "user" : "bot"}`}>
              {m.text.split("\n").map((line, i) => <div key={i}>{line}</div>)}

              {m.buttons && (
                <div style={{ display: "flex", gap: "8px", marginTop: "8px", flexWrap: "wrap" }}>
                  {m.buttons.map((btn, i) => (
                    <button
                      key={i}
                      onClick={() => handleButtonClick(btn)}
                      style={{ padding: "6px 12px", borderRadius: "8px", border: "1px solid #1976d2", background: "#e3f2fd", cursor: "pointer" }}
                    >
                      {btn}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
          <div ref={messagesEndRef}></div>
        </div>

				{/* ---- 입력 영역 ---- */}
        <div className="chat-input-box">
          <input
            type="text"
            placeholder="질문을 입력해주세요"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          />
          <button onClick={() => sendMessage()}>전송</button>
        </div>
      </div>
    </div>
  );
}

export default ChatWindow;
