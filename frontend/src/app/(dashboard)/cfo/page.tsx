"use client";

import { useState, useRef, useEffect } from "react";
import { createCFOWebSocket, type CFOMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Send, Bot, User, Trash2 } from "lucide-react";
import { cfo } from "@/lib/api";

export default function CFOPage() {
  const [messages, setMessages] = useState<CFOMessage[]>([
    {
      role: "assistant",
      content:
        "Hi! I'm your AI CFO. Ask me anything about your finances — " +
        "income trends, tax estimates, cash flow, or invoice advice.",
    },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || streaming) return;

    const userMessage = input.trim();
    setInput("");
    setStreaming(true);

    // Add user message immediately
    setMessages((prev) => [
      ...prev,
      { role: "user", content: userMessage },
      { role: "assistant", content: "" },  // placeholder for streaming
    ]);

    const token = localStorage.getItem("access_token");
    if (!token) return;

    // Open WebSocket
    const ws = createCFOWebSocket(token);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          message: userMessage,
          conversation_id: conversationId,
        })
      );
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "chunk") {
        // Append chunk to last assistant message
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            role: "assistant",
            content: updated[updated.length - 1].content + data.content,
          };
          return updated;
        });
      }

      if (data.type === "done") {
        setConversationId(data.conversation_id);
        setStreaming(false);
        ws.close();
      }

      if (data.type === "error") {
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            role: "assistant",
            content: "Sorry, something went wrong. Please try again.",
          };
          return updated;
        });
        setStreaming(false);
        ws.close();
      }
    };

    ws.onerror = () => {
      setStreaming(false);
    };
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const clearChat = async () => {
    await cfo.clearHistory();
    setMessages([
      {
        role: "assistant",
        content: "Chat cleared. How can I help you?",
      },
    ]);
    setConversationId(null);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">AI CFO</h1>
          <p className="text-slate-500 text-sm">
            Ask anything about your finances
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={clearChat}
          className="text-slate-500"
        >
          <Trash2 size={14} className="mr-2" />
          Clear
        </Button>
      </div>

      {/* Messages */}
      <Card className="flex-1 overflow-y-auto p-4 space-y-4 mb-4">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex gap-3 ${
              msg.role === "user" ? "flex-row-reverse" : ""
            }`}
          >
            {/* Avatar */}
            <div
              className={`w-8 h-8 rounded-full flex items-center
                          justify-center flex-shrink-0 ${
                            msg.role === "assistant"
                              ? "bg-violet-100"
                              : "bg-slate-200"
                          }`}
            >
              {msg.role === "assistant" ? (
                <Bot size={16} className="text-violet-600" />
              ) : (
                <User size={16} className="text-slate-600" />
              )}
            </div>

            {/* Bubble */}
            <div
              className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm
                          leading-relaxed whitespace-pre-wrap ${
                            msg.role === "assistant"
                              ? "bg-white border border-slate-200 text-slate-800"
                              : "bg-violet-600 text-white"
                          }`}
            >
              {msg.content}
              {/* Blinking cursor while streaming */}
              {streaming &&
                i === messages.length - 1 &&
                msg.role === "assistant" && (
                  <span className="inline-block w-2 h-4 bg-violet-400
                                   ml-0.5 animate-pulse rounded-sm" />
                )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </Card>

      {/* Input */}
      <div className="flex gap-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask your CFO... (Enter to send)"
          disabled={streaming}
          className="flex-1"
        />
        <Button
          onClick={sendMessage}
          disabled={streaming || !input.trim()}
          className="bg-violet-600 hover:bg-violet-700"
        >
          <Send size={16} />
        </Button>
      </div>
    </div>
  );
}