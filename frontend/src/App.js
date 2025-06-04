import React, { useState } from "react";

export default function App() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [accessToken, setAccessToken] = useState(null);
  const [show2FA, setShow2FA] = useState(false);

  const [uploading, setUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(false);

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState([
    {
      role: "system",
      content: `Hi I am your trusty RFP assistant.
Please upload a document and log in to get started.`,
    },
  ]);

  // ===== LOGIN & 2FA =====
  const handleLogin = async () => {
    const res = await fetch("http://localhost:8000/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    const data = await res.json();
    if (res.ok) {
      if (data.requires_2fa) {
        setShow2FA(true);
      } else {
        setAccessToken(data.access_token);
        alert("Logged in!");
      }
    } else {
      alert(data.detail || "Login failed");
    }
  };

  const handleVerify2FA = async () => {
    const res = await fetch("http://localhost:8000/2fa/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, token }),
    });

    const data = await res.json();
    if (res.ok) {
      setAccessToken(data.access_token);
      setShow2FA(false);
      alert("2FA verified and logged in!");
    } else {
      alert(data.detail || "2FA verification failed");
    }
  };

  // ===== FILE UPLOAD =====
  const handleUpload = async (event) => {
    const file = event.target.files[0];
    if (!file || !accessToken) {
      alert("Please log in first.");
      return;
    }

    setUploading(true);
    setUploadSuccess(false);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("http://localhost:8000/upload", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();

      if (res.ok) {
        setUploadSuccess(true);
        alert("File uploaded and processed successfully.");
      } else {
        alert("Upload failed: " + (data.error || "Unknown error"));
      }
    } catch (error) {
      alert("Upload error: " + error.message);
    } finally {
      setUploading(false);
    }
  };

  // ===== CHAT =====
  const sendMessage = async () => {
    if (!input.trim()) return;

    const newMessages = [...messages, { role: "user", content: input }];
    setMessages(newMessages);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch("http://localhost:8000/chat", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ user_input: input }),
      });
      const data = await res.json();

      if (res.ok) {
        setMessages([...newMessages, { role: "assistant", content: data.response }]);
      } else {
        setMessages([
          ...newMessages,
          { role: "assistant", content: "Error: " + (data.error || "Failed to get response") },
        ]);
      }
    } catch (error) {
      setMessages([
        ...newMessages,
        { role: "assistant", content: "Error: Failed to connect to server." },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 700, margin: "auto", fontFamily: "Arial, sans-serif" }}>
      <h2>Login</h2>
      {!accessToken && (
        <>
          <input
            type="text"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            style={{ marginRight: 10 }}
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ marginRight: 10 }}
          />
          <button onClick={handleLogin}>Login</button>
        </>
      )}
      {show2FA && (
        <div style={{ marginTop: 10 }}>
          <input
            type="text"
            placeholder="Enter 2FA Code"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            style={{ marginRight: 10 }}
          />
          <button onClick={handleVerify2FA}>Verify 2FA</button>
        </div>
      )}

      {accessToken && (
        <>
          <hr />
          <h2>Upload RFP Document</h2>
          <input
            type="file"
            accept=".pdf,.doc,.docx"
            onChange={handleUpload}
            disabled={uploading || loading}
          />
          {uploading && <p>Uploading and processing document...</p>}
          {uploadSuccess && <p style={{ color: "green" }}>Document uploaded and processed!</p>}

          <hr />

          <h2>Chat with Assistant</h2>
          <div
            style={{
              border: "1px solid #ccc",
              padding: 10,
              minHeight: 300,
              overflowY: "auto",
              marginBottom: 10,
              backgroundColor: "#fafafa",
              whiteSpace: "pre-wrap",
            }}
          >
            {messages.map((msg, idx) => (
              <div
                key={idx}
                style={{
                  textAlign: msg.role === "user" ? "right" : "left",
                  margin: "10px 0",
                }}
              >
                <div
                  style={{
                    display: "inline-block",
                    backgroundColor: msg.role === "user" ? "#dcf8c6" : "#e8e8e8",
                    borderRadius: 10,
                    padding: 10,
                    maxWidth: "80%",
                    fontSize: 14,
                  }}
                >
                  {msg.content}
                </div>
              </div>
            ))}
            {loading && (
              <div style={{ fontStyle: "italic", color: "#999" }}>Assistant is typing...</div>
            )}
          </div>

          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") sendMessage();
            }}
            placeholder="Type your message..."
            style={{ width: "80%", padding: 10, fontSize: 14 }}
            disabled={loading || uploading || !uploadSuccess}
          />
          <button
            onClick={sendMessage}
            disabled={loading || uploading || !uploadSuccess}
            style={{ padding: 10, marginLeft: 10 }}
          >
            Send
          </button>
        </>
      )}
    </div>
  );
}
