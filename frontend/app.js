
const SESSION_KEY = "jarvis_session_id";

let sessionId = localStorage.getItem(SESSION_KEY);

if (!sessionId) {
  sessionId = crypto.randomUUID();
  localStorage.setItem(SESSION_KEY, sessionId);
}

const messagesEl = document.getElementById("messages");
const welcomeEl = document.getElementById("welcome");
const form = document.getElementById("chat-form");
const input = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");
const micButton = document.getElementById("mic-button");
const micIcon = document.getElementById("mic-icon");
const voiceStatus = document.getElementById("voice-status");

const statusDot = document.getElementById("status-dot");
const connectionLabel = document.getElementById("connection-label");
const modelLabel = document.getElementById("model-label");
const modelMode = document.getElementById("model-mode");

let audioContext = null;
let mediaStream = null;
let audioSource = null;
let processor = null;
let silentGain = null;
let audioChunks = [];
let recordingStartedAt = 0;
let isRecording = false;

const MAX_RECORDING_SECONDS = 60;

// Voice output
const SPEECH_ENABLED = true;

function setVoiceStatus(message, state = "") {
  voiceStatus.textContent = message;
  voiceStatus.className = `voice-status ${state}`.trim();
}

// Detect whether the response is Russian or English.
function detectSpeechLanguage(text) {
  const russianCharacters = (text.match(/[а-яё]/gi) || []).length;
  const latinCharacters = (text.match(/[a-z]/gi) || []).length;

  return russianCharacters > latinCharacters ? "ru-RU" : "en-US";
}

// Speak JARVIS's answer using the browser's local speech engine.
function speakReply(text) {
  if (!SPEECH_ENABLED || !("speechSynthesis" in window)) {
    setVoiceStatus("Voice output is not supported by this browser.", "error");
    return;
  }

  const cleanText = text
    .replace(/```[\s\S]*?```/g, " Code omitted. ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/https?:\/\/\S+/g, "")
    .trim();

  if (!cleanText) return;

  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(cleanText);
  const language = detectSpeechLanguage(cleanText);

  utterance.lang = language;
  utterance.rate = 1;
  utterance.pitch = 1;
  utterance.volume = 1;

  const voices = window.speechSynthesis.getVoices();

  const preferredVoice = voices.find(voice =>
    voice.lang.toLowerCase().startsWith(language.slice(0, 2).toLowerCase())
  );

  if (preferredVoice) {
    utterance.voice = preferredVoice;
  }

  utterance.onstart = () => {
    setVoiceStatus(
      language === "ru-RU" ? "JARVIS is speaking in Russian…" : "JARVIS is speaking in English…",
      "speaking"
    );
  };

  utterance.onend = () => {
    setVoiceStatus("Microphone ready · English and Russian", "success");
  };

  utterance.onerror = event => {
    console.error("Speech output error:", event);
    setVoiceStatus("Answer received, but voice playback failed.", "error");
  };

  window.speechSynthesis.speak(utterance);
}

function addMessage(role, content, model = null, tier = null, reason = null) {
  welcomeEl.style.display = "none";

  const wrapper = document.createElement("div");
  wrapper.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "assistant" ? "J" : "Y";

  const contentWrap = document.createElement("div");
  contentWrap.className = "message-content";

  const label = document.createElement("div");
  label.className = "message-label";
  label.textContent = role === "assistant"
    ? `JARVIS${model ? ` · ${model}` : ""}`
    : "YOU";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;

  contentWrap.append(label, bubble);

  if (role === "assistant" && reason) {
    const meta = document.createElement("div");
    meta.className = "route-meta";
    meta.textContent = `${tier || "model"} route · ${reason}`;
    contentWrap.append(meta);
  }

  wrapper.append(avatar, contentWrap);
  messagesEl.appendChild(wrapper);
  wrapper.scrollIntoView({ behavior: "smooth", block: "end" });
}

function showTyping() {
  const el = document.createElement("div");
  el.id = "typing-indicator";
  el.className = "typing";
  el.textContent = "JARVIS is selecting a model and thinking…";
  messagesEl.appendChild(el);
}

function hideTyping() {
  document.getElementById("typing-indicator")?.remove();
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();

    if (data.status === "ok") {
      statusDot.classList.add("online");
      connectionLabel.textContent = "Ollama online";
      modelLabel.textContent =
        `Fast: ${data.fast_model_available ? "ready" : "missing"} · ` +
        `Advanced: ${data.advanced_model_available ? "ready" : "missing"}`;
    } else if (data.status === "models_missing") {
      connectionLabel.textContent = "Models not installed";
      modelLabel.textContent = `Run ollama pull ${data.fast_model}`;
    } else {
      connectionLabel.textContent = "Ollama offline";
      modelLabel.textContent = data.detail || "Open Ollama";
    }
  } catch {
    connectionLabel.textContent = "Backend unavailable";
    modelLabel.textContent = "Start the JARVIS server";
  }
}

async function loadHistory() {
  try {
    const response = await fetch(`/api/history/${sessionId}`);

    if (!response.ok) return;

    const data = await response.json();

    data.messages.forEach(message => {
      addMessage(message.role, message.content, message.model);
    });
  } catch (error) {
    console.error("Could not load history", error);
  }
}

async function sendMessage(message) {
  if (!message || sendButton.disabled) return;

  // Stop any previous spoken response.
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }

  addMessage("user", message);

  input.value = "";
  input.style.height = "auto";

  sendButton.disabled = true;
  micButton.disabled = true;

  showTyping();
  setVoiceStatus("JARVIS is thinking…", "processing");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        message,
        model_mode: modelMode.value
      })
    });

    const data = await response.json();

    hideTyping();

    if (!response.ok) {
      throw new Error(data.detail || "JARVIS could not process that request.");
    }

    addMessage(
      "assistant",
      data.reply,
      data.model,
      data.tier,
      data.routing_reason
    );

    // Automatically speak every successful assistant response.
    speakReply(data.reply);

  } catch (error) {
    hideTyping();

    const errorMessage = `I encountered a problem: ${error.message}`;
    addMessage("assistant", errorMessage);

    setVoiceStatus(error.message, "error");

  } finally {
    sendButton.disabled = false;
    micButton.disabled = false;
    checkHealth();
  }
}

form.addEventListener("submit", async event => {
  event.preventDefault();

  const message = input.value.trim();

  if (!message || sendButton.disabled) return;

  await sendMessage(message);
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
});

input.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

document.querySelectorAll(".suggestion").forEach(button => {
  button.addEventListener("click", () => {
    input.value = button.textContent;
    form.requestSubmit();
  });
});

document.getElementById("new-chat").addEventListener("click", () => {
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }

  sessionId = crypto.randomUUID();
  localStorage.setItem(SESSION_KEY, sessionId);

  messagesEl.replaceChildren();
  welcomeEl.style.display = "block";
  input.focus();
});

document.getElementById("clear-chat").addEventListener("click", async () => {
  if (!confirm("Clear this conversation from the local JARVIS database?")) {
    return;
  }

  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }

  await fetch(`/api/history/${sessionId}`, { method: "DELETE" });

  messagesEl.replaceChildren();
  welcomeEl.style.display = "block";
});

// Convert mono Float32 audio samples into a standard PCM WAV file.
function encodeWav(samples, sampleRate) {
  const bytesPerSample = 2;
  const dataSize = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  function writeString(offset, value) {
    for (let i = 0; i < value.length; i++) {
      view.setUint8(offset + i, value.charCodeAt(i));
    }
  }

  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * bytesPerSample, true);
  view.setUint16(32, bytesPerSample, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, dataSize, true);

  let offset = 44;

  for (let i = 0; i < samples.length; i++) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    const pcm = sample < 0 ? sample * 0x8000 : sample * 0x7fff;

    view.setInt16(offset, pcm, true);
    offset += 2;
  }

  return new Blob([buffer], { type: "audio/wav" });
}

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext) {
    throw new Error(
      "Your browser does not support microphone recording. Try a recent version of Safari or Chrome."
    );
  }

  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    }
  });

  audioContext = new AudioContext();
  await audioContext.resume();

  audioSource = audioContext.createMediaStreamSource(mediaStream);
  processor = audioContext.createScriptProcessor(4096, 1, 1);
  silentGain = audioContext.createGain();
  silentGain.gain.value = 0;

  audioChunks = [];
  recordingStartedAt = Date.now();
  isRecording = true;

  processor.onaudioprocess = event => {
    if (!isRecording) return;

    const channel = event.inputBuffer.getChannelData(0);
    audioChunks.push(new Float32Array(channel));

    if ((Date.now() - recordingStartedAt) / 1000 >= MAX_RECORDING_SECONDS) {
      stopRecording();
    }
  };

  audioSource.connect(processor);
  processor.connect(silentGain);
  silentGain.connect(audioContext.destination);

  micButton.classList.add("recording");
  micButton.setAttribute("aria-label", "Stop recording");
  micIcon.textContent = "■";

  setVoiceStatus("Listening… Speak in English or Russian.", "recording");
}

async function stopRecording() {
  if (!isRecording) return;

  isRecording = false;

  const chunks = audioChunks;
  const sampleRate = audioContext.sampleRate;

  processor?.disconnect();
  audioSource?.disconnect();
  silentGain?.disconnect();

  mediaStream?.getTracks().forEach(track => track.stop());

  try {
    await audioContext.close();
  } catch (error) {
    console.warn("Audio context close warning:", error);
  }

  audioContext = null;
  mediaStream = null;
  audioSource = null;
  processor = null;
  silentGain = null;
  audioChunks = [];

  micButton.classList.remove("recording");
  micButton.disabled = true;
  sendButton.disabled = true;
  micIcon.textContent = "…";
  micButton.setAttribute("aria-label", "Processing recording");

  setVoiceStatus("Processing your speech locally…", "processing");

  try {
    const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);

    if (totalLength === 0) {
      throw new Error("No audio was captured. Please try again.");
    }

    const samples = new Float32Array(totalLength);
    let offset = 0;

    for (const chunk of chunks) {
      samples.set(chunk, offset);
      offset += chunk.length;
    }

    const wavBlob = encodeWav(samples, sampleRate);
    const formData = new FormData();

    formData.append("audio", wavBlob, "recording.wav");

    const response = await fetch("/api/transcribe", {
      method: "POST",
      body: formData
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Speech recognition failed.");
    }

    if (!data.text || !data.text.trim()) {
      throw new Error("I couldn't recognize speech. Please try again.");
    }

    const recognizedText = data.text.trim();

    const languageNames = {
      en: "English",
      ru: "Russian"
    };

    const language = languageNames[data.language] || data.language || "unknown";

    setVoiceStatus(
      `Recognized ${language}. Sending to JARVIS…`,
      "success"
    );

    // Automatically send recognized speech to the AI.
    await sendMessage(recognizedText);

  } catch (error) {
    console.error("Transcription error:", error);
    setVoiceStatus(error.message, "error");
  } finally {
    micButton.disabled = false;
    sendButton.disabled = false;
    micIcon.textContent = "🎙";
    micButton.setAttribute("aria-label", "Start microphone recording");
  }
}

micButton.addEventListener("click", async () => {
  if (isRecording) {
    await stopRecording();
    return;
  }

  if (sendButton.disabled) return;

  try {
    await startRecording();
  } catch (error) {
    console.error("Microphone error:", error);

    setVoiceStatus(
      error.message || "Could not access the microphone.",
      "error"
    );

    mediaStream?.getTracks().forEach(track => track.stop());
    mediaStream = null;

    micButton.classList.remove("recording");
    micIcon.textContent = "🎙";
  }
});

// Load available browser voices.
if ("speechSynthesis" in window) {
  window.speechSynthesis.getVoices();

  window.speechSynthesis.onvoiceschanged = () => {
    window.speechSynthesis.getVoices();
  };
}

checkHealth();
loadHistory();
setInterval(checkHealth, 15000);
