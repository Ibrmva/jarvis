const SESSION_KEY = "jarvis_session_id";
const VOICE_ENABLED_KEY = "jarvis_voice_enabled";

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
const voiceStatusText = document.getElementById("voice-status-text");
const orbStage = document.getElementById("orb-stage");
const assistantState = document.getElementById("assistant-state");
const assistantStateLabel = document.getElementById("assistant-state-label");

const statusDot = document.getElementById("status-dot");
const connectionLabel = document.getElementById("connection-label");
const modelLabel = document.getElementById("model-label");
const modelMode = document.getElementById("model-mode");
const recentChatsEl = document.getElementById("recent-chats");
const sidebar = document.getElementById("sidebar");
const sidebarToggle = document.getElementById("sidebar-toggle");
const sidebarBackdrop = document.getElementById("sidebar-backdrop");
const mainPanel = document.querySelector(".main-panel");
const wakeWordToggle = document.getElementById("wake-word-toggle");
const wakeWordToast = document.getElementById("wake-word-toast");

let audioContext = null;
let mediaStream = null;
let audioSource = null;
let processor = null;
let silentGain = null;
let audioChunks = [];
let recordingStartedAt = 0;
let isRecording = false;
let isBusy = false;
let voiceEnabled = localStorage.getItem(VOICE_ENABLED_KEY) !== "false";
let speechVoices = [];
let wakeWordEnabled = false;
let wakeWordStarting = false;
let wakeWordActive = false;
let wakeWordSocket = null;
let wakeWordReadyReject = null;
let wakeWordRemainder = new Float32Array(0);
let wakeCaptureMode = false;
let wakeReplyInProgress = false;
let wakeSpeechStartedAt = 0;
let wakeSilenceStartedAt = 0;
let wakeSpeechCandidateFrames = 0;
let wakeAutoStopTriggered = false;
let wakeWordToastTimer = null;

const MAX_RECORDING_SECONDS = 60;
const WAKEWORD_FRAME_SAMPLES = 1280;

function setSidebarOpen(open, restoreFocus = false) {
  const isMobile = window.matchMedia("(max-width: 700px)").matches;
  if (open && !isMobile) return;

  document.body.classList.toggle("sidebar-open", open);
  sidebar.classList.toggle("is-open", open);
  sidebar.inert = isMobile && !open;
  mainPanel.inert = open;
  if (isMobile) {
    sidebar.setAttribute("aria-hidden", String(!open));
  } else {
    sidebar.removeAttribute("aria-hidden");
  }
  sidebarToggle.setAttribute("aria-expanded", String(open));
  sidebarToggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");

  if (open) {
    sidebar.querySelector("button")?.focus();
  } else if (restoreFocus && isMobile) {
    sidebarToggle.focus();
  }
}

setSidebarOpen(false);
sidebarToggle.addEventListener("click", () => {
  setSidebarOpen(!document.body.classList.contains("sidebar-open"), true);
});
sidebarBackdrop.addEventListener("click", () => setSidebarOpen(false, true));
sidebar.addEventListener("click", event => {
  if (event.target.closest("button")) setSidebarOpen(false, true);
});
modelMode.addEventListener("change", () => setSidebarOpen(false, true));
window.addEventListener("resize", () => {
  setSidebarOpen(false);
});

function setAssistantState(state, label) {
  if (orbStage) orbStage.dataset.state = state;
  if (assistantState) assistantState.dataset.state = state;
  if (assistantStateLabel && label) assistantStateLabel.textContent = label;
}

function setVoiceStatus(message, state = "") {
  voiceStatusText.textContent = message;
  voiceStatus.className = `voice-status ${state}`.trim();
}

function updateWakeWordButton(starting = false) {
  wakeWordToggle.textContent = starting
    ? "Starting…"
    : !wakeWordEnabled
      ? "Off"
      : wakeCaptureMode
        ? "Speak now"
        : wakeWordActive
          ? "Listening"
          : "Paused";
  wakeWordToggle.setAttribute("aria-pressed", String(wakeWordEnabled));
  wakeWordToggle.title = wakeWordEnabled
    ? "Disable local wake-word listening"
    : "Enable local wake-word listening";
}

function showWakeWordToast(message, duration = 3500) {
  clearTimeout(wakeWordToastTimer);
  wakeWordToast.textContent = message;
  wakeWordToast.hidden = false;
  if (duration) {
    wakeWordToastTimer = setTimeout(() => {
      wakeWordToast.hidden = true;
    }, duration);
  }
}

function releaseWakeWordAudio() {
  processor?.disconnect();
  audioSource?.disconnect();
  silentGain?.disconnect();
  mediaStream?.getTracks().forEach(track => track.stop());

  const context = audioContext;
  audioContext = null;
  mediaStream = null;
  audioSource = null;
  processor = null;
  silentGain = null;
  audioChunks = [];

  if (context && context.state !== "closed") {
    context.close().catch(error => console.warn("Audio context close warning:", error));
  }
}

function stopWakeWordListener() {
  wakeWordActive = false;
  wakeWordRemainder = new Float32Array(0);
  wakeWordReadyReject?.(new Error("Wake-word listening was disabled."));
  wakeWordReadyReject = null;
  const socket = wakeWordSocket;
  wakeWordSocket = null;
  if (socket) {
    socket.onclose = null;
    socket.close();
  }

  if (!wakeCaptureMode) releaseWakeWordAudio();
}

function stopWakeWordOnPageHide() {
  wakeWordEnabled = false;
  wakeCaptureMode = false;
  isRecording = false;
  stopWakeWordListener();
  releaseWakeWordAudio();
}

function processWakeAudio(event) {
  const samples = event.inputBuffer.getChannelData(0);

  if (wakeCaptureMode) {
    if (!isRecording) return;

    audioChunks.push(new Float32Array(samples));
    const now = Date.now();
    let energy = 0;
    for (let i = 0; i < samples.length; i++) energy += samples[i] * samples[i];
    const rms = Math.sqrt(energy / samples.length);

    if (rms > 0.008) {
      wakeSpeechCandidateFrames++;
      if (wakeSpeechCandidateFrames >= 2) {
        wakeSpeechStartedAt = now;
        wakeSilenceStartedAt = 0;
      }
    } else {
      wakeSpeechCandidateFrames = 0;
      if (wakeSpeechStartedAt && !wakeSilenceStartedAt) {
        wakeSilenceStartedAt = now;
      }
    }

    const speechEnded = wakeSpeechStartedAt && wakeSilenceStartedAt &&
      now - wakeSilenceStartedAt >= 1200;
    const noSpeechTimeout = !wakeSpeechStartedAt && now - recordingStartedAt >= 8000;
    const recordingTimeout = now - recordingStartedAt >= MAX_RECORDING_SECONDS * 1000;
    if (!wakeAutoStopTriggered && noSpeechTimeout) {
      wakeAutoStopTriggered = true;
      void discardWakeCapture();
    } else if (!wakeAutoStopTriggered && (speechEnded || recordingTimeout)) {
      wakeAutoStopTriggered = true;
      void stopRecording();
    }
    return;
  }

  if (!wakeWordActive || !wakeWordSocket || wakeWordSocket.readyState !== WebSocket.OPEN) {
    return;
  }

  const ratio = audioContext.sampleRate / 16000;
  const outputLength = Math.floor(samples.length / ratio);
  const resampled = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i++) {
    const position = i * ratio;
    const left = Math.floor(position);
    const fraction = position - left;
    resampled[i] = samples[left] * (1 - fraction) +
      samples[Math.min(left + 1, samples.length - 1)] * fraction;
  }

  const combined = new Float32Array(wakeWordRemainder.length + resampled.length);
  combined.set(wakeWordRemainder);
  combined.set(resampled, wakeWordRemainder.length);

  let offset = 0;
  while (offset + WAKEWORD_FRAME_SAMPLES <= combined.length) {
    if (wakeWordSocket.bufferedAmount > 8192) break;

    const pcm = new Int16Array(WAKEWORD_FRAME_SAMPLES);
    for (let i = 0; i < WAKEWORD_FRAME_SAMPLES; i++) {
      const sample = Math.max(-1, Math.min(1, combined[offset + i]));
      pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    }
    wakeWordSocket.send(pcm.buffer);
    offset += WAKEWORD_FRAME_SAMPLES;
  }
  wakeWordRemainder = combined.slice(offset);
}

function onWakeWordDetected() {
  if (!wakeWordEnabled || !wakeWordActive) return;

  wakeWordActive = false;
  wakeCaptureMode = true;
  wakeWordRemainder = new Float32Array(0);
  audioChunks = [];
  recordingStartedAt = Date.now();
  wakeSpeechStartedAt = 0;
  wakeSilenceStartedAt = 0;
  wakeSpeechCandidateFrames = 0;
  wakeAutoStopTriggered = false;
  isRecording = true;
  updateWakeWordButton();
  showWakeWordToast("Hey JARVIS heard you. Speak now; sending after 1.2 seconds of silence.");

  const socket = wakeWordSocket;
  wakeWordSocket = null;
  socket?.close();

  micButton.classList.add("recording");
  micIcon.innerHTML = '<path d="M7 7h10v10H7z"/>';
  micButton.setAttribute("aria-label", "Stop recording");
  setAssistantState("listening", "Hey JARVIS heard you");
  setVoiceStatus("Wake word detected. Speak now; I’ll send your message after a pause.", "recording");
}

async function startWakeWordListener() {
  if (!wakeWordEnabled || wakeWordStarting || wakeWordActive || wakeCaptureMode || isBusy) return;
  if (!navigator.mediaDevices?.getUserMedia || !(window.AudioContext || window.webkitAudioContext)) {
    throw new Error("Wake-word listening is unavailable in this browser.");
  }

  wakeWordStarting = true;
  updateWakeWordButton(true);
  setVoiceStatus("Starting the local wake-word detector…", "processing");
  let socket = null;

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });

    if (!wakeWordEnabled) {
      releaseWakeWordAudio();
      return;
    }

    socket = new WebSocket(
      `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/wake-word`
    );
    wakeWordSocket = socket;

    await new Promise((resolve, reject) => {
      const timeout = setTimeout(
        () => reject(new Error("Timed out loading the wake-word detector.")),
        120000
      );
      let initialized = false;
      const finish = callback => value => {
        clearTimeout(timeout);
        wakeWordReadyReject = null;
        callback(value);
      };
      const ready = finish(resolve);
      const failed = finish(reject);
      wakeWordReadyReject = failed;

      socket.onmessage = event => {
        const message = JSON.parse(event.data);
        if (message.type === "ready" && !initialized) {
          initialized = true;
          ready();
        } else if (message.type === "wake") {
          onWakeWordDetected();
        } else if (message.type === "error") {
          const error = new Error(message.message || "Wake-word detection failed.");
          if (!initialized) {
            failed(error);
          } else {
            wakeWordEnabled = false;
            stopWakeWordListener();
            updateWakeWordButton();
            setVoiceStatus(error.message, "error");
          }
        }
      };
      socket.onerror = () => failed(new Error("Could not connect to the local wake-word detector."));
      socket.onclose = () => {
        if (!initialized && wakeWordEnabled) {
          failed(new Error("The wake-word detector connection closed."));
        } else if (wakeWordEnabled && wakeWordActive) {
          wakeWordEnabled = false;
          wakeWordActive = false;
          wakeWordSocket = null;
          updateWakeWordButton();
          releaseWakeWordAudio();
          setVoiceStatus("Wake-word listening stopped unexpectedly.", "error");
        }
      };
    });

    if (!wakeWordEnabled || wakeWordSocket !== socket) return;

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioContextClass();
    await audioContext.resume();
    audioSource = audioContext.createMediaStreamSource(mediaStream);
    processor = audioContext.createScriptProcessor(4096, 1, 1);
    silentGain = audioContext.createGain();
    silentGain.gain.value = 0;
    processor.onaudioprocess = processWakeAudio;
    audioSource.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(audioContext.destination);

    wakeWordActive = true;
    updateWakeWordButton();
    setAssistantState("listening", "Listening for Hey JARVIS");
    setVoiceStatus("Listening locally for “Hey JARVIS”. The microphone stays on until disabled.", "recording");
  } catch (error) {
    if (socket) {
      socket.onclose = null;
      socket.close();
    }
    if (wakeWordSocket === socket) wakeWordSocket = null;
    releaseWakeWordAudio();
    throw error;
  } finally {
    wakeWordStarting = false;
    updateWakeWordButton();
  }
}

async function toggleWakeWord() {
  if (wakeWordEnabled) {
    wakeWordEnabled = false;
    stopWakeWordListener();
    updateWakeWordButton();
    setAssistantState("idle", "Standing by for your command");
    setVoiceStatus("Wake-word listening is off.");
    return;
  }

  wakeWordEnabled = true;
  updateWakeWordButton(true);
  try {
    await startWakeWordListener();
  } catch (error) {
    if (!wakeWordEnabled) return;
    wakeWordEnabled = false;
    stopWakeWordListener();
    updateWakeWordButton();
    setAssistantState("idle", "Wake-word listening unavailable");
    setVoiceStatus(error.message, "error");
  }
}

async function resumeWakeWordListener() {
  if (!wakeWordEnabled || isBusy || isRecording || document.hidden) return;
  try {
    await startWakeWordListener();
  } catch (error) {
    wakeWordEnabled = false;
    stopWakeWordListener();
    updateWakeWordButton();
    setVoiceStatus(error.message, "error");
  }
}

function stopWakeWordAfterPlayback() {
  if (wakeWordEnabled) void resumeWakeWordListener();
}

wakeWordToggle.addEventListener("click", toggleWakeWord);

document.addEventListener("visibilitychange", () => {
  if (document.hidden && wakeCaptureMode && isRecording) {
    wakeAutoStopTriggered = true;
    void stopRecording();
  } else if (document.hidden && (wakeWordActive || wakeWordStarting)) {
    stopWakeWordListener();
    updateWakeWordButton();
    setVoiceStatus("Wake-word listening paused while this tab is in the background.");
  } else if (!document.hidden && wakeWordEnabled && !wakeCaptureMode) {
    void resumeWakeWordListener();
  }
});

function setBusy(busy) {
  isBusy = busy;
  sendButton.disabled = busy;
  micButton.disabled = busy;
  if (!busy && !isRecording) {
    micIcon.innerHTML = '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3m-4 0h8"/>';
    micButton.setAttribute("aria-label", "Start microphone recording");
  }
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
  hideTyping();
  const el = document.createElement("div");
  el.id = "typing-indicator";
  el.className = "typing";
  el.textContent = "JARVIS is thinking…";
  messagesEl.appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
}

function hideTyping() {
  document.getElementById("typing-indicator")?.remove();
}

function loadSpeechVoices() {
  if (!("speechSynthesis" in window)) return;
  speechVoices = window.speechSynthesis.getVoices();
}

function detectSpeechLanguage(text) {
  const cyrillic = (text.match(/[А-Яа-яЁё]/g) || []).length;
  const latin = (text.match(/[A-Za-z]/g) || []).length;
  return cyrillic > latin ? "ru-RU" : "en-US";
}

function speakReply(text) {
  if (!voiceEnabled || !("speechSynthesis" in window) || !text) return false;

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  wakeReplyInProgress = true;
  const language = detectSpeechLanguage(text);
  utterance.lang = language;
  loadSpeechVoices();

  const matchingVoice = speechVoices.find(voice =>
    voice.lang.toLowerCase().startsWith(language.slice(0, 2).toLowerCase())
  );
  if (matchingVoice) utterance.voice = matchingVoice;

  utterance.rate = 1;
  utterance.pitch = 1;
  utterance.volume = 1;

  utterance.onstart = () => setAssistantState("speaking", "JARVIS is speaking");
  utterance.onend = () => {
    wakeReplyInProgress = false;
    setAssistantState("idle", "Standing by for your command");
    stopWakeWordAfterPlayback();
  };
  utterance.onerror = event => {
    wakeReplyInProgress = false;
    console.warn("Speech synthesis issue:", event.error);
    setAssistantState("idle", "Reply displayed · voice playback unavailable");
    stopWakeWordAfterPlayback();
  };

  window.speechSynthesis.speak(utterance);
  return true;
}

if ("speechSynthesis" in window) {
  loadSpeechVoices();
  window.speechSynthesis.onvoiceschanged = loadSpeechVoices;
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
      statusDot.classList.remove("online");
      connectionLabel.textContent = "Models not installed";
      modelLabel.textContent = `Run ollama pull ${data.fast_model || "the configured model"}`;
    } else {
      statusDot.classList.remove("online");
      connectionLabel.textContent = "Ollama offline";
      modelLabel.textContent = data.detail || "Open Ollama";
    }
  } catch (error) {
    statusDot.classList.remove("online");
    connectionLabel.textContent = "Backend unavailable";
    modelLabel.textContent = "Start the JARVIS server";
  }
}

async function loadModelOptions() {
  try {
    const response = await fetch("/api/models");
    if (!response.ok) throw new Error(`Could not load models (${response.status}).`);

    const data = await response.json();
    for (const model of data.models) {
      const option = modelMode.querySelector(`option[value="${model.id}"]`);
      if (option) option.textContent = model.label;
    }
  } catch (error) {
    console.error("Could not load model options:", error);
  }
}

async function loadHistory() {
  const requestedSessionId = sessionId;
  try {
    const response = await fetch(`/api/history/${requestedSessionId}`);
    if (!response.ok) throw new Error(`Could not load conversation (${response.status}).`);
    const data = await response.json();
    if (requestedSessionId !== sessionId) return;

    if (Array.isArray(data.messages) && data.messages.length) {
      welcomeEl.style.display = "none";
      data.messages.forEach(message => {
        addMessage(message.role, message.content, message.model);
      });
    }
  } catch (error) {
    console.error("Could not load history:", error);
  }
}

function renderRecentChats(sessions) {
  recentChatsEl.replaceChildren();

  if (!sessions.length) {
    const emptyState = document.createElement("div");
    emptyState.className = "recent-chats-empty";
    emptyState.textContent = "No conversations yet";
    recentChatsEl.append(emptyState);
    return;
  }

  sessions.forEach(session => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `conversation-item${session.session_id === sessionId ? " active" : ""}`;
    button.textContent = session.title || "Untitled conversation";
    button.title = button.textContent;
    button.setAttribute("aria-current", session.session_id === sessionId ? "page" : "false");
    button.addEventListener("click", () => openConversation(session.session_id));
    recentChatsEl.append(button);
  });
}

async function refreshRecentChats() {
  try {
    const response = await fetch("/api/sessions");
    if (!response.ok) throw new Error(`Could not load recent conversations (${response.status}).`);
    const data = await response.json();
    renderRecentChats(Array.isArray(data.sessions) ? data.sessions : []);
  } catch (error) {
    console.error("Could not load recent conversations:", error);
    recentChatsEl.replaceChildren();
    const errorState = document.createElement("div");
    errorState.className = "recent-chats-empty";
    errorState.textContent = "Could not load conversations";
    recentChatsEl.append(errorState);
  }
}

async function openConversation(nextSessionId) {
  if (isBusy || nextSessionId === sessionId) return;

  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  sessionId = nextSessionId;
  localStorage.setItem(SESSION_KEY, sessionId);
  messagesEl.replaceChildren();
  welcomeEl.style.display = "flex";
  input.value = "";
  setAssistantState("idle", "Standing by for your command");
  setVoiceStatus("Microphone ready · English and Russian");
  await loadHistory();
  await refreshRecentChats();
}

async function sendMessage(message, options = {}) {
  const cleanMessage = (message || "").trim();
  if (!cleanMessage || isBusy) return;

  const fromVoice = options.fromVoice === true;
  addMessage("user", cleanMessage);
  input.value = "";
  input.style.height = "auto";

  setBusy(true);
  setAssistantState("thinking", fromVoice ? "I heard you. Thinking…" : "Working on your request");
  if (fromVoice) setVoiceStatus("Sending your voice message to JARVIS…", "processing");
  showTyping();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        message: cleanMessage,
        model_mode: modelMode.value
      })
    });

    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(`The server returned an invalid response (${response.status}).`);
    }

    hideTyping();

    if (!response.ok) {
      throw new Error(data.detail || "JARVIS could not process that request.");
    }

    addMessage("assistant", data.reply, data.model, data.tier, data.routing_reason);
    setVoiceStatus(fromVoice ? "Voice message sent · JARVIS replied" : "Ready · English and Russian voice input", "success");
    if (fromVoice) speakReply(data.reply);
  } catch (error) {
    hideTyping();
    addMessage("assistant", `I encountered a problem: ${error.message}`);
    setVoiceStatus(error.message, "error");
    setAssistantState("idle", "Something went wrong · try again");
  } finally {
    setBusy(false);
    if (!("speechSynthesis" in window) || window.speechSynthesis.speaking === false) {
      setAssistantState("idle", "Standing by for your command");
    }
    await refreshRecentChats();
    checkHealth();
  }
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || isBusy) return;
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
    const text = button.querySelector("b")?.textContent || button.textContent;
    const prompts = {
      "Explore an idea": "Help me explore and validate a new project idea.",
      "Write some code": "Help me write or debug code. Ask me for the relevant details.",
      "Explain a concept": "Explain a complex technical concept in a clear, practical way."
    };
    input.value = prompts[text] || text;
    form.requestSubmit();
  });
});

function startNewConversation() {
  if (isBusy) return;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  sessionId = crypto.randomUUID();
  localStorage.setItem(SESSION_KEY, sessionId);
  messagesEl.replaceChildren();
  welcomeEl.style.display = "flex";
  setAssistantState("idle", "Standing by for your command");
  setVoiceStatus("Microphone ready · English and Russian");
  input.value = "";
  input.focus();
  refreshRecentChats();
}

document.getElementById("new-chat").addEventListener("click", startNewConversation);

document.getElementById("clear-chat").addEventListener("click", async () => {
  if (isBusy) return;
  if (!confirm("Clear this conversation from the local JARVIS database?")) return;

  try {
    const response = await fetch(`/api/history/${sessionId}`, { method: "DELETE" });
    if (!response.ok) throw new Error("Could not clear conversation history.");
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    messagesEl.replaceChildren();
    welcomeEl.style.display = "flex";
    setAssistantState("idle", "Standing by for your command");
    setVoiceStatus("Conversation cleared");
    await refreshRecentChats();
  } catch (error) {
    setVoiceStatus(error.message, "error");
  }
});

// Convert mono Float32 samples into a standard 16-bit PCM WAV file.
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
  if (isBusy || isRecording) return;
  if (!navigator.mediaDevices?.getUserMedia || !(window.AudioContext || window.webkitAudioContext)) {
    throw new Error("Microphone recording is unavailable in this browser. Try a recent Safari or Chrome version.");
  }

  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    }
  });

  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  audioContext = new AudioContextClass();
  await audioContext.resume();

  audioSource = audioContext.createMediaStreamSource(mediaStream);
  processor = audioContext.createScriptProcessor(4096, 1, 1);
  silentGain = audioContext.createGain();
  silentGain.gain.value = 0;

  audioChunks = [];
  recordingStartedAt = Date.now();
  isRecording = true;
  wakeCaptureMode = false;

  processor.onaudioprocess = event => {
    if (!isRecording) return;
    audioChunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    if ((Date.now() - recordingStartedAt) / 1000 >= MAX_RECORDING_SECONDS) {
      stopRecording();
    }
  };

  audioSource.connect(processor);
  processor.connect(silentGain);
  silentGain.connect(audioContext.destination);

  micButton.classList.add("recording");
  micIcon.innerHTML = '<path d="M7 7h10v10H7z"/>';
  micButton.setAttribute("aria-label", "Stop recording");
  setAssistantState("listening", "Listening to your voice");
  setVoiceStatus("Listening… Speak in English or Russian, then press the microphone to send.", "recording");
}

async function discardWakeCapture() {
  if (!wakeCaptureMode || !isRecording) return;
  isRecording = false;

  processor?.disconnect();
  audioSource?.disconnect();
  silentGain?.disconnect();
  mediaStream?.getTracks().forEach(track => track.stop());

  const context = audioContext;
  audioContext = null;
  mediaStream = null;
  audioSource = null;
  processor = null;
  silentGain = null;
  audioChunks = [];
  wakeCaptureMode = false;
  wakeSpeechStartedAt = 0;
  wakeSilenceStartedAt = 0;
  wakeSpeechCandidateFrames = 0;
  wakeAutoStopTriggered = false;

  if (context && context.state !== "closed") {
    try {
      await context.close();
    } catch (error) {
      console.warn("Audio context close warning:", error);
    }
  }

  micButton.classList.remove("recording");
  micButton.disabled = false;
  micIcon.innerHTML = '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3m-4 0h8"/>';
  micButton.setAttribute("aria-label", "Start microphone recording");
  setAssistantState("idle", wakeWordEnabled ? "Listening for Hey JARVIS" : "Standing by for your command");
  updateWakeWordButton();
  setVoiceStatus(
    wakeWordEnabled ? "No speech heard. Listening for Hey JARVIS again." : "No speech heard.",
    wakeWordEnabled ? "success" : "",
  );
  showWakeWordToast(
    wakeWordEnabled ? "No request heard; listening for Hey JARVIS again." : "No request heard.",
  );
  await resumeWakeWordListener();
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
  wakeCaptureMode = false;
  wakeSpeechStartedAt = 0;
  wakeSilenceStartedAt = 0;
  wakeSpeechCandidateFrames = 0;
  wakeAutoStopTriggered = false;
  updateWakeWordButton();
  if (wakeWordEnabled) showWakeWordToast("Sending your request to JARVIS…");

  micButton.classList.remove("recording");
  micButton.disabled = true;
  micIcon.innerHTML = '<path d="M5 12h14"/>';
  micButton.setAttribute("aria-label", "Processing recording");

  setAssistantState("thinking", "Transcribing your voice locally");
  setVoiceStatus("Processing your speech locally…", "processing");

  try {
    const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    if (totalLength === 0) throw new Error("No audio was captured. Please try again.");

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

    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(`Speech service returned an invalid response (${response.status}).`);
    }

    if (!response.ok) throw new Error(data.detail || "Speech recognition failed.");
    if (!data.text || !data.text.trim()) throw new Error("I couldn't recognize speech. Please try again.");

    const recognizedText = data.text.trim();
    const languageNames = { en: "English", ru: "Russian" };
    const language = languageNames[data.language] || data.language || "unknown";

    setVoiceStatus(`Recognized ${language}. Sending to JARVIS…`, "success");

    // Automatically submit the recognized speech. sendMessage manages its own busy state.
    await sendMessage(recognizedText, { fromVoice: true });
  } catch (error) {
    console.error("Transcription error:", error);
    setVoiceStatus(error.message, "error");
    setAssistantState("idle", "Standing by for your command");
  } finally {
    micButton.disabled = isBusy;
    if (!isBusy) {
      micIcon.innerHTML = '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3m-4 0h8"/>';
      micButton.setAttribute("aria-label", "Start microphone recording");
    }
    if (wakeWordEnabled && !wakeReplyInProgress) {
      void resumeWakeWordListener();
    }
  }
}

micButton.addEventListener("click", async () => {
  if (isBusy) return;
  if (wakeWordActive || wakeWordStarting) {
    await toggleWakeWord();
    return;
  }
  if (isRecording) {
    await stopRecording();
    return;
  }

  try {
    await startRecording();
  } catch (error) {
    console.error("Microphone error:", error);
    setVoiceStatus(error.message || "Could not access the microphone.", "error");
    setAssistantState("idle", "Microphone unavailable");
    mediaStream?.getTracks().forEach(track => track.stop());
    mediaStream = null;
    micButton.classList.remove("recording");
    micIcon.innerHTML = '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3m-4 0h8"/>';
  }
});

document.addEventListener("keydown", event => {
  if (document.body.classList.contains("sidebar-open")) {
    if (event.key === "Escape") {
      setSidebarOpen(false, true);
      return;
    }

    if (event.key === "Tab") {
      const focusable = sidebar.querySelectorAll(
        'a[href], button:not(:disabled), select:not(:disabled), textarea:not(:disabled)'
      );
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (!sidebar.contains(document.activeElement)) {
        event.preventDefault();
        first?.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    }
  }

  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    startNewConversation();
  }
});

checkHealth();
loadModelOptions();
loadHistory();
refreshRecentChats();
setInterval(checkHealth, 15000);

// =============================================
// JARVIS SNOW VISION — HAND TRACKING ONLY
// =============================================

const cameraToggle = document.getElementById("camera-toggle");
const cameraStage = document.getElementById("camera-stage");
const cameraVideo = document.getElementById("camera-video");
const snowCanvas = document.getElementById("snow-canvas");
const cameraStatus = document.getElementById("camera-status");
const cameraLabel = document.getElementById("camera-label");

let cameraStream = null;
let handTracker = null;
let cameraActive = false;
let animationFrame = null;
let lastVideoTime = -1;
let particles = [];

const connections = [
    [0, 1], [1, 2], [2, 3], [3, 4],
    [0, 5], [5, 6], [6, 7], [7, 8],
    [5, 9], [9, 10], [10, 11], [11, 12],
    [9, 13], [13, 14], [14, 15], [15, 16],
    [13, 17], [17, 18], [18, 19], [19, 20],
    [0, 17]
];

async function loadHandTracker() {
    if (handTracker) return handTracker;

    cameraStatus.textContent = "Loading hand tracking model...";

    const vision = await import(
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14"
    );

    const fileset = await vision.FilesetResolver.forVisionTasks(
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm"
    );

    handTracker = await vision.HandLandmarker.createFromOptions(
        fileset,
        {
            baseOptions: {
                modelAssetPath:
                    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
                delegate: "GPU"
            },
            runningMode: "VIDEO",
            numHands: 2,
            minHandDetectionConfidence: 0.55,
            minHandPresenceConfidence: 0.5,
            minTrackingConfidence: 0.5
        }
    );

    return handTracker;
}

function resizeCanvas() {
    const rect = cameraStage.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    snowCanvas.width = rect.width * dpr;
    snowCanvas.height = rect.height * dpr;

    const ctx = snowCanvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function createSnow(x, y, amount = 1) {
    const count = Math.round(4 * amount);

    for (let i = 0; i < count; i++) {
        particles.push({
            x,
            y,
            vx: (Math.random() - 0.5) * 3 * amount,
            vy: -Math.random() * 2 - 0.5,
            life: 50 + Math.random() * 30,
            radius: 1 + Math.random() * 2.5
        });
    }

    if (particles.length > 800) {
        particles.splice(0, particles.length - 800);
    }
}

function drawHands(results) {
    const ctx = snowCanvas.getContext("2d");
    const width = cameraStage.clientWidth;
    const height = cameraStage.clientHeight;

    ctx.clearRect(0, 0, width, height);

    const hands = results.landmarks || [];

    if (hands.length > 0) {
        cameraLabel.textContent =
            `${hands.length} HAND(S) DETECTED · CREATE MAGIC`;

        hands.forEach(landmarks => {
            const points = landmarks.map(point => ({
                x: (1 - point.x) * width,
                y: point.y * height
            }));

            // Draw glowing hand skeleton.
            ctx.save();
            ctx.strokeStyle = "rgba(170, 218, 255, 0.6)";
            ctx.lineWidth = 1.5;
            ctx.shadowColor = "#9edbff";
            ctx.shadowBlur = 8;

            connections.forEach(([a, b]) => {
                ctx.beginPath();
                ctx.moveTo(points[a].x, points[a].y);
                ctx.lineTo(points[b].x, points[b].y);
                ctx.stroke();
            });

            ctx.restore();

            // Snow comes from fingertips.
            [4, 8, 12, 16, 20].forEach(index => {
                const point = points[index];

                createSnow(point.x, point.y, 1.5);

                ctx.beginPath();
                ctx.arc(point.x, point.y, 4, 0, Math.PI * 2);
                ctx.fillStyle = "#eaf8ff";
                ctx.shadowColor = "#8bd5ff";
                ctx.shadowBlur = 16;
                ctx.fill();
            });

            // Magical glow around palm.
            const palm = points[9];

            const glow = ctx.createRadialGradient(
                palm.x, palm.y, 2,
                palm.x, palm.y, 45
            );

            glow.addColorStop(0, "rgba(139,205,255,0.3)");
            glow.addColorStop(1, "rgba(139,205,255,0)");

            ctx.fillStyle = glow;
            ctx.fillRect(
                palm.x - 45,
                palm.y - 45,
                90,
                90
            );
        });
    } else {
        cameraLabel.textContent = "SHOW YOUR HANDS TO THE CAMERA";
    }

    // Ambient falling snow.
    if (Math.random() < 0.4) {
        createSnow(Math.random() * width, -5, 0.4);
    }

    // Animate particles.
    particles = particles.filter(p => p.life > 0);

    particles.forEach(p => {
        p.x += p.vx;
        p.y += p.vy;
        p.vy += 0.02;
        p.life--;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);

        ctx.fillStyle =
            `rgba(220,242,255,${Math.min(1, p.life / 40)})`;

        ctx.shadowColor = "#9edbff";
        ctx.shadowBlur = 10;
        ctx.fill();
    });
}

function visionLoop() {
    if (!cameraActive) return;

    if (
        cameraVideo.readyState >= 2 &&
        cameraVideo.currentTime !== lastVideoTime
    ) {
        lastVideoTime = cameraVideo.currentTime;

        try {
            const results = handTracker.detectForVideo(
                cameraVideo,
                performance.now()
            );

            drawHands(results);
        } catch (error) {
            console.error("Hand tracking error:", error);
        }
    }

    animationFrame = requestAnimationFrame(visionLoop);
}

async function activateCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("Camera access is not available in this browser.");
    }

    cameraToggle.disabled = true;

    try {
        cameraStatus.textContent = "Requesting camera permission...";

        cameraStream = await navigator.mediaDevices.getUserMedia({
            audio: false,
            video: {
                facingMode: "user",
                width: { ideal: 1280 },
                height: { ideal: 720 }
            }
        });

        cameraVideo.srcObject = cameraStream;
        await cameraVideo.play();

        cameraStage.hidden = false;
        resizeCanvas();

        await loadHandTracker();

        cameraActive = true;
        lastVideoTime = -1;
        particles = [];

        cameraToggle.textContent = "✧ Deactivate Camera";
        cameraToggle.classList.add("active");

        cameraStatus.textContent =
            "Camera active · Hand tracking only";

        visionLoop();

    } catch (error) {
        stopCamera();
        throw error;

    } finally {
        cameraToggle.disabled = false;
    }
}

function stopCamera() {
    cameraActive = false;

    if (animationFrame) {
        cancelAnimationFrame(animationFrame);
    }

    animationFrame = null;

    if (cameraStream) {
        cameraStream.getTracks().forEach(track => track.stop());
    }

    cameraStream = null;

    cameraVideo.pause();
    cameraVideo.srcObject = null;

    cameraStage.hidden = true;
    particles = [];

    const ctx = snowCanvas.getContext("2d");
    ctx.clearRect(0, 0, snowCanvas.width, snowCanvas.height);

    cameraToggle.textContent = "✧ Activate Camera";
    cameraToggle.classList.remove("active");

    cameraStatus.textContent =
        "Camera is off · Nothing is being captured";
}

cameraToggle.addEventListener("click", async () => {
    if (cameraActive) {
        stopCamera();
        return;
    }

    try {
        await activateCamera();
    } catch (error) {
        console.error(error);
        cameraStatus.textContent = error.message;
    }
});

window.addEventListener("resize", () => {
    if (cameraActive) resizeCanvas();
});

window.addEventListener("pagehide", stopCamera);
window.addEventListener("pagehide", stopWakeWordOnPageHide);