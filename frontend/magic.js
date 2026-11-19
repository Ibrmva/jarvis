
/* =========================================================
   JARVIS GENERATIVE MAGIC MODE
   CDN Three.js + Safari-friendly camera + MediaPipe
========================================================= */

let THREE = null;
let graphicsReady = null;

const $ = (id) => document.getElementById(id);

const stage = $("magic-stage");
const canvas = $("magic-renderer");
const video = $("magic-video");

const cameraButton = $("magic-camera-toggle");
const galaxyButton = $("magic-galaxy-button");
const stormButton = $("magic-storm-button");

const magicForm = $("magic-form");
const magicInput = $("magic-input");
const magicSend = $("magic-send");

const statusEl = $("magic-status");
const placeholder = $("magic-placeholder");
const effectLabel = $("magic-effect-label");
const gestureFeedback = $("magic-gesture-feedback");
const interpreterText = $("magic-interpreter-text");

const requiredElements = [
  stage,
  canvas,
  video,
  cameraButton,
  galaxyButton,
  stormButton,
  magicForm,
  magicInput,
  magicSend,
  statusEl,
  placeholder,
  effectLabel,
  gestureFeedback,
  interpreterText
];

if (requiredElements.some((element) => !element)) {
  console.error("Magic Mode HTML elements are missing.", {
    stage,
    canvas,
    video,
    cameraButton,
    galaxyButton,
    stormButton,
    magicForm,
    magicInput,
    magicSend,
    statusEl,
    placeholder,
    effectLabel,
    gestureFeedback,
    interpreterText
  });

  throw new Error(
    "Magic Mode HTML elements are missing. Check index.html."
  );
}

/* =========================================================
   CONFIGURATION
========================================================= */

const DEFAULT_CONFIG = {
  effect: "galaxy",
  palette: "cosmic",
  intensity: 0.7,
  particle_count: 6000,
  rotation_speed: 0.5,
  colors: ["#72a7ff", "#a78bfa", "#55e6ff"]
};

const MIN_PARTICLES = 1000;
const MAX_PARTICLES = 8000;

let currentConfig = { ...DEFAULT_CONFIG };

/* =========================================================
   THREE.JS STATE
========================================================= */

let renderer = null;
let scene = null;
let camera = null;

let particleSystem = null;
let particleGeometry = null;
let particleMaterial = null;

let basePositions = null;
let positions = null;
let velocities = null;

let animationFrame = null;
let resizeObserver = null;

let galaxyCenter = null;
let targetCenter = null;

/* =========================================================
   CAMERA STATE
========================================================= */

let cameraStream = null;
let cameraActive = false;
let cameraStarting = false;

let handLandmarker = null;
let trackingAvailable = false;
let trackingFrame = null;
let trackingBusy = false;
let lastVideoTime = -1;

/* =========================================================
   INTERACTION STATE
========================================================= */

let galaxyScale = 1;
let targetScale = 1;

let galaxyRotation = 0;
let targetRotation = 0;

let energy = 0.7;
let targetEnergy = 0.7;

let magicBusy = false;

const handState = {
  count: 0,
  distance: 0.5
};

/* =========================================================
   UI HELPERS
========================================================= */

function setStatus(message) {
  statusEl.textContent = String(message).toUpperCase();
}

function setFeedback(message) {
  gestureFeedback.textContent = message;
}

function setInterpreter(message) {
  interpreterText.textContent = message;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function describeError(error) {
  return `${error?.name || "Error"}: ${error?.message || String(error)}`;
}

function speakMagic(message) {
  if (!("speechSynthesis" in window)) return;

  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(message);
  utterance.lang = "en-US";
  utterance.rate = 1;
  utterance.pitch = 1;

  window.speechSynthesis.speak(utterance);
}

/* =========================================================
   THREE.JS CDN LOADER

   The handler is registered before this loader runs.
   Three.js is NOT loaded from npm or node_modules.
========================================================= */

async function loadThreeJS() {
  if (THREE) return THREE;

  if (graphicsReady) return graphicsReady;

  graphicsReady = (async () => {
    setStatus("Loading graphics engine");
    setInterpreter("Loading Three.js from the CDN…");

    try {
      const module = await import(
        "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"
      );

      if (!module || !module.WebGLRenderer) {
        throw new Error(
          "Three.js loaded, but WebGLRenderer was not found."
        );
      }

      THREE = module;

      galaxyCenter = new THREE.Vector3(0, 0, 0);
      targetCenter = new THREE.Vector3(0, 0, 0);

      initializeThree();

      setStatus("Graphics ready");
      setInterpreter("Three.js graphics engine initialized.");

      console.info("JARVIS Magic: Three.js loaded successfully.");

      return THREE;

    } catch (error) {
      graphicsReady = null;

      console.error("Three.js CDN loading failed:", error);

      setStatus("Graphics engine unavailable");

      setInterpreter(
        `Three.js could not load from jsDelivr. Check your internet connection or CDN access. ${describeError(error)}`
      );

      throw new Error(
        `Three.js CDN loading failed: ${describeError(error)}`
      );
    }
  })();

  return graphicsReady;
}

/* =========================================================
   THREE.JS INITIALIZATION
========================================================= */

function initializeThree() {
  if (renderer) return;

  if (!THREE) {
    throw new Error("Three.js has not loaded yet.");
  }

  try {
    scene = new THREE.Scene();
    scene.background = null;

    camera = new THREE.PerspectiveCamera(
      55,
      Math.max(stage.clientWidth, 1) /
        Math.max(stage.clientHeight, 1),
      0.1,
      100
    );

    camera.position.set(0, 0, 11);

    renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: false,
      powerPreference: "low-power"
    });

    renderer.setPixelRatio(
      Math.min(window.devicePixelRatio || 1, 1.25)
    );

    renderer.setSize(
      Math.max(stage.clientWidth, 1),
      Math.max(stage.clientHeight, 1)
    );

    renderer.setClearColor(0x000000, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 0.5));

    const light = new THREE.PointLight(0x7aaaff, 2, 30);
    light.position.set(0, 2, 5);
    scene.add(light);

    if ("ResizeObserver" in window) {
      resizeObserver = new ResizeObserver(resizeRenderer);
      resizeObserver.observe(stage);
    } else {
      window.addEventListener("resize", resizeRenderer);
    }

    animate();

    console.info("JARVIS Magic: Three.js renderer initialized.");

  } catch (error) {
    console.error("Three.js initialization failed:", error);

    setStatus("Graphics error");
    setInterpreter(describeError(error));

    throw error;
  }
}

/* =========================================================
   PARTICLE DATA
========================================================= */

function createParticleData(count) {
  const safeCount = clamp(
    Number(count) || 6000,
    MIN_PARTICLES,
    MAX_PARTICLES
  );

  basePositions = new Float32Array(safeCount * 3);
  positions = new Float32Array(safeCount * 3);
  velocities = new Float32Array(safeCount * 3);

  for (let i = 0; i < safeCount; i++) {
    const index = i * 3;

    const radius = 0.3 + Math.random() * 4.5;
    const angle = Math.random() * Math.PI * 2;
    const armOffset = Math.sin(angle * 3) * 0.4;
    const spread = (Math.random() - 0.5) * 0.5;

    basePositions[index] =
      Math.cos(angle) * radius + armOffset + spread;

    basePositions[index + 1] =
      (Math.random() - 0.5) * 0.5;

    basePositions[index + 2] =
      Math.sin(angle) * radius + spread;

    positions[index] = basePositions[index];
    positions[index + 1] = basePositions[index + 1];
    positions[index + 2] = basePositions[index + 2];
  }

  return safeCount;
}

function disposeParticles() {
  if (particleSystem && scene) {
    scene.remove(particleSystem);
  }

  particleGeometry?.dispose();
  particleMaterial?.dispose();

  particleSystem = null;
  particleGeometry = null;
  particleMaterial = null;
}

/* =========================================================
   GALAXY
========================================================= */

function createGalaxy() {
  if (!renderer || !scene || !THREE) {
    throw new Error("Graphics engine is not initialized.");
  }

  disposeParticles();

  const count = createParticleData(
    currentConfig.particle_count
  );

  particleGeometry = new THREE.BufferGeometry();

  particleGeometry.setAttribute(
    "position",
    new THREE.BufferAttribute(positions, 3)
  );

  const palette =
    Array.isArray(currentConfig.colors) &&
    currentConfig.colors.length
      ? currentConfig.colors
      : DEFAULT_CONFIG.colors;

  const colors = palette.map(
    (color) => new THREE.Color(color)
  );

  const colorAttribute = new Float32Array(count * 3);

  for (let i = 0; i < count; i++) {
    const color = colors[
      Math.floor(Math.random() * colors.length)
    ];

    const index = i * 3;

    colorAttribute[index] = color.r;
    colorAttribute[index + 1] = color.g;
    colorAttribute[index + 2] = color.b;
  }

  particleGeometry.setAttribute(
    "color",
    new THREE.BufferAttribute(colorAttribute, 3)
  );

  particleMaterial = new THREE.PointsMaterial({
    size: 0.035,
    vertexColors: true,
    transparent: true,
    opacity: 0.95,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    sizeAttenuation: true
  });

  particleSystem = new THREE.Points(
    particleGeometry,
    particleMaterial
  );

  scene.add(particleSystem);

  console.info(`JARVIS Magic: Galaxy created with ${count} particles.`);
}

/* =========================================================
   WINTER STORM
========================================================= */

function createWinterStorm() {
  if (!renderer || !scene || !THREE) {
    throw new Error("Graphics engine is not initialized.");
  }

  disposeParticles();

  const count = createParticleData(
    currentConfig.particle_count
  );

  for (let i = 0; i < count; i++) {
    const index = i * 3;

    basePositions[index] =
      (Math.random() - 0.5) * 9;

    basePositions[index + 1] =
      (Math.random() - 0.5) * 7;

    basePositions[index + 2] =
      (Math.random() - 0.5) * 5;

    positions[index] = basePositions[index];
    positions[index + 1] = basePositions[index + 1];
    positions[index + 2] = basePositions[index + 2];

    velocities[index] =
      (Math.random() - 0.5) * 0.008;

    velocities[index + 1] =
      -0.005 - Math.random() * 0.012;

    velocities[index + 2] =
      (Math.random() - 0.5) * 0.008;
  }

  particleGeometry = new THREE.BufferGeometry();

  particleGeometry.setAttribute(
    "position",
    new THREE.BufferAttribute(positions, 3)
  );

  const colors = new Float32Array(count * 3);

  for (let i = 0; i < count; i++) {
    const index = i * 3;
    const shade = 0.75 + Math.random() * 0.25;

    colors[index] = 0.75 * shade;
    colors[index + 1] = 0.9 * shade;
    colors[index + 2] = shade;
  }

  particleGeometry.setAttribute(
    "color",
    new THREE.BufferAttribute(colors, 3)
  );

  particleMaterial = new THREE.PointsMaterial({
    size: 0.045,
    vertexColors: true,
    transparent: true,
    opacity: 0.95,
    blending: THREE.AdditiveBlending,
    depthWrite: false
  });

  particleSystem = new THREE.Points(
    particleGeometry,
    particleMaterial
  );

  scene.add(particleSystem);

  console.info(`JARVIS Magic: Winter Storm created with ${count} particles.`);
}

/* =========================================================
   APPLY EFFECT
========================================================= */

function applyEffect(config) {
  if (!renderer || !scene || !THREE) {
    throw new Error("Graphics engine is not ready.");
  }

  currentConfig = {
    ...currentConfig,
    ...config
  };

  currentConfig.particle_count = clamp(
    Number(currentConfig.particle_count) || 6000,
    MIN_PARTICLES,
    MAX_PARTICLES
  );

  currentConfig.intensity = clamp(
    Number(currentConfig.intensity) || 0.7,
    0.1,
    1
  );

  currentConfig.rotation_speed = clamp(
    Number(currentConfig.rotation_speed) || 0.5,
    0.1,
    2
  );

  targetEnergy = currentConfig.intensity;

  galaxyScale = 1;
  targetScale = 1;

  galaxyRotation = 0;
  targetRotation = 0;

  targetCenter.set(0, 0, 0);

  if (currentConfig.effect === "winter_storm") {
    createWinterStorm();
    effectLabel.textContent = "WINTER STORM";
  } else {
    currentConfig.effect = "galaxy";
    createGalaxy();
    effectLabel.textContent = "GALAXY MODE";
  }

  placeholder.hidden = true;

  setStatus(cameraActive ? "Camera active" : "Effect active");

  console.info("JARVIS Magic: Effect applied.", currentConfig);
}

/* =========================================================
   ANIMATION
========================================================= */

function animate() {
  animationFrame = requestAnimationFrame(animate);

  if (!renderer || !scene || !camera) return;

  galaxyScale += (targetScale - galaxyScale) * 0.06;
  galaxyRotation += (targetRotation - galaxyRotation) * 0.06;
  energy += (targetEnergy - energy) * 0.05;

  galaxyCenter.lerp(targetCenter, 0.06);

  if (particleSystem) {
    particleSystem.scale.setScalar(galaxyScale);
    particleSystem.position.copy(galaxyCenter);

    if (
      currentConfig.effect === "galaxy" &&
      positions &&
      basePositions
    ) {
      const count = positions.length / 3;
      const spread = 0.8 + energy * 0.8;

      for (let i = 0; i < count; i++) {
        const index = i * 3;

        positions[index] =
          basePositions[index] * spread;

        positions[index + 1] =
          basePositions[index + 1] * spread;

        positions[index + 2] =
          basePositions[index + 2] * spread;
      }

      particleSystem.rotation.y +=
        0.0015 * currentConfig.rotation_speed +
        galaxyRotation * 0.0002;

      particleSystem.rotation.z += 0.0003;

      particleGeometry.attributes.position.needsUpdate = true;

    } else if (positions && velocities) {
      const count = positions.length / 3;

      for (let i = 0; i < count; i++) {
        const index = i * 3;

        positions[index] += velocities[index];
        positions[index + 1] += velocities[index + 1];
        positions[index + 2] += velocities[index + 2];

        if (positions[index + 1] < -4) {
          positions[index + 1] = 4;
        }

        if (positions[index] < -5) {
          positions[index] = 5;
        }

        if (positions[index] > 5) {
          positions[index] = -5;
        }
      }

      particleGeometry.attributes.position.needsUpdate = true;
    }

    particleMaterial.size = 0.025 + energy * 0.025;
  }

  renderer.render(scene, camera);
}

/* =========================================================
   RESIZE
========================================================= */

function resizeRenderer() {
  if (!renderer || !camera) return;

  const width = stage.clientWidth;
  const height = stage.clientHeight;

  if (!width || !height) return;

  camera.aspect = width / height;
  camera.updateProjectionMatrix();

  renderer.setSize(width, height, false);
}

/* =========================================================
   AI EFFECT INTERPRETER
========================================================= */

async function interpretCommand(prompt) {
  if (magicBusy) return false;

  magicBusy = true;
  magicSend.disabled = true;

  setStatus("Preparing graphics");
  setInterpreter("JARVIS is preparing the visual engine…");

  try {
    await loadThreeJS();

    setStatus("Interpreting");
    setInterpreter("JARVIS is interpreting your visual request…");

    const response = await fetch(
      "/api/magic/interpret",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          prompt,
          current_config: currentConfig
        })
      }
    );

    let data;

    try {
      data = await response.json();
    } catch {
      throw new Error(
        `Invalid server response. HTTP ${response.status}`
      );
    }

    if (!response.ok) {
      throw new Error(
        data.detail || `Request failed. HTTP ${response.status}`
      );
    }

    if (!data.config) {
      throw new Error(
        "The interpreter did not return an effect configuration."
      );
    }

    applyEffect(data.config);

    const effectName =
      data.config.effect === "winter_storm"
        ? "winter storm"
        : "galaxy";

    setInterpreter(
      `Effect: ${effectName} · Palette: ${data.config.palette} · Intensity: ${data.config.intensity}`
    );

    setFeedback(
      cameraActive
        ? "Move your hands to interact with the effect."
        : "Activate the camera to control the effect with your hands."
    );

    speakMagic(`Creating your ${effectName}.`);

    return true;

  } catch (error) {
    console.error("Magic interpreter error:", error);

    setStatus("Magic error");
    setInterpreter(describeError(error));
    setFeedback("Check the graphics engine and try again.");

    return false;

  } finally {
    magicBusy = false;
    magicSend.disabled = false;
  }
}

/* =========================================================
   CHAT COMMAND DETECTION
========================================================= */

function isMagicCommand(text) {
  const value = String(text || "").toLowerCase();

  const hasEffect =
    /\b(galaxy|universe|winter storm|snowstorm|snow storm|magic mode)\b/.test(value);

  const hasCommand =
    /\b(create|make|generate|change|switch|turn|activate|build|transform)\b/.test(value);

  return hasEffect && hasCommand;
}

/* =========================================================
   GLOBAL JARVIS COMMAND HANDLER

   This is registered BEFORE Three.js is loaded.
========================================================= */

window.jarvisMagicHandleCommand = async function (message) {
  console.info("JARVIS Magic: Command received:", message);

  if (!isMagicCommand(message)) {
    return false;
  }

  const success = await interpretCommand(message);

  if (success) {
    magicInput.value = "";
  }

  return success;
};

console.info("JARVIS Magic: Global command handler registered.");

/* =========================================================
   MAGIC PROMPT CONTROLS
========================================================= */

magicForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const prompt = magicInput.value.trim();

  if (!prompt) return;

  if (await interpretCommand(prompt)) {
    magicInput.value = "";
  }
});

galaxyButton.addEventListener("click", () => {
  interpretCommand("Create a galaxy around my hands.");
});

stormButton.addEventListener("click", () => {
  interpretCommand("Change the current effect to a winter storm.");
});

/* =========================================================
   MEDIAPIPE HAND TRACKER
========================================================= */

async function loadHandTracker() {
  if (handLandmarker) return handLandmarker;

  setFeedback("Loading hand tracking model…");

  const vision = await import(
    "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/+esm"
  );

  const fileset =
    await vision.FilesetResolver.forVisionTasks(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm"
    );

  const modelUrl =
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

  const createTracker = (delegate) =>
    vision.HandLandmarker.createFromOptions(
      fileset,
      {
        baseOptions: {
          modelAssetPath: modelUrl,
          delegate
        },
        runningMode: "VIDEO",
        numHands: 2,
        minHandDetectionConfidence: 0.55,
        minHandPresenceConfidence: 0.5,
        minTrackingConfidence: 0.5
      }
    );

  try {
    handLandmarker = await createTracker("GPU");

  } catch (gpuError) {
    console.warn(
      "MediaPipe GPU failed. Retrying with CPU.",
      gpuError
    );

    handLandmarker = await createTracker("CPU");
  }

  return handLandmarker;
}

/* =========================================================
   HAND ANALYSIS
========================================================= */

function distance2D(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function isFingerExtended(landmarks, tip, pip) {
  return landmarks[tip].y < landmarks[pip].y;
}

function analyzeHand(landmarks) {
  const pinch =
    distance2D(landmarks[4], landmarks[8]) < 0.055;

  const extended = [
    isFingerExtended(landmarks, 8, 6),
    isFingerExtended(landmarks, 12, 10),
    isFingerExtended(landmarks, 16, 14),
    isFingerExtended(landmarks, 20, 18)
  ];

  const extendedCount =
    extended.filter(Boolean).length;

  return {
    landmarks,
    palm: landmarks[9],
    pinch,
    fist: extendedCount <= 1,
    open: extendedCount >= 3
  };
}

/* =========================================================
   GESTURE CONTROLS
========================================================= */

function updateGestureControls(hands) {
  if (!hands.length) {
    handState.count = 0;

    targetScale = 1;
    targetRotation = 0;
    targetEnergy = currentConfig.intensity;
    targetCenter.set(0, 0, 0);

    setFeedback("Show your hands to the camera.");
    return;
  }

  handState.count = hands.length;

  const first = hands[0];
  const second = hands[1] || null;

  const palmA = first.palm;
  const palmB = second ? second.palm : null;

  const centerX = second
    ? (palmA.x + palmB.x) / 2
    : palmA.x;

  const centerY = second
    ? (palmA.y + palmB.y) / 2
    : palmA.y;

  targetCenter.set(
    (0.5 - centerX) * 5,
    (0.5 - centerY) * 3,
    0
  );

  if (second) {
    const distance = distance2D(palmA, palmB);

    handState.distance = distance;

    targetScale = THREE.MathUtils.clamp(
      0.55 + distance * 2.2,
      0.55,
      2.0
    );

    if (first.open && second.open) {
      setFeedback("Both palms open · Galaxy expanding");
      targetScale = Math.min(2.0, targetScale + 0.2);

    } else if (first.fist && second.fist) {
      setFeedback("Both fists closed · Galaxy collapsing");
      targetScale = 0.25;

    } else {
      setFeedback(
        "Two hands detected · Move closer or farther apart"
      );
    }

    targetRotation = (palmB.x - palmA.x) * 2;

  } else {
    targetScale = 1;
    targetRotation = 0;

    setFeedback(
      "One hand detected · Move to guide the galaxy"
    );
  }

  const pinching = hands.some((hand) => hand.pinch);

  if (pinching) {
    targetEnergy = Math.min(
      1,
      currentConfig.intensity + 0.25
    );

    setFeedback("Pinch detected · Increasing energy");

  } else if (
    hands.length === 2 &&
    first.fist &&
    second.fist
  ) {
    targetEnergy = 0.15;

  } else {
    targetEnergy = currentConfig.intensity;
  }
}

/* =========================================================
   HAND TRACKING LOOP
========================================================= */

function handTrackingLoop() {
  if (!cameraActive || !handLandmarker) return;

  if (trackingBusy) {
    trackingFrame = requestAnimationFrame(handTrackingLoop);
    return;
  }

  if (
    video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
    video.currentTime !== lastVideoTime
  ) {
    trackingBusy = true;
    lastVideoTime = video.currentTime;

    try {
      const result = handLandmarker.detectForVideo(
        video,
        performance.now()
      );

      const hands = (result.landmarks || []).map(analyzeHand);

      updateGestureControls(hands);

    } catch (error) {
      console.error("Hand tracking error:", error);

      setFeedback(
        `Hand tracking error: ${describeError(error)}`
      );

    } finally {
      trackingBusy = false;
    }
  }

  trackingFrame = requestAnimationFrame(handTrackingLoop);
}

/* =========================================================
   CAMERA ERROR EXPLANATIONS
========================================================= */

function explainCameraError(error) {
  const explanations = {
    NotAllowedError:
      "Camera permission denied. Allow camera access for this website in Safari and macOS settings.",

    PermissionDeniedError:
      "Camera permission denied. Allow camera access for this website in Safari and macOS settings.",

    NotFoundError:
      "No camera found. Check that your MacBook camera is available.",

    DevicesNotFoundError:
      "No camera found. Check that your MacBook camera is available.",

    NotReadableError:
      "Camera is busy or unavailable. Close FaceTime, Zoom, Teams, or other camera apps.",

    TrackStartError:
      "macOS could not start the camera. Close other camera apps and retry.",

    OverconstrainedError:
      "Requested camera settings are unsupported. Retry with default settings.",

    SecurityError:
      "Browser blocked camera access. Use localhost or HTTPS.",

    AbortError:
      "Camera startup was interrupted. Reload the page and retry."
  };

  return explanations[error?.name] ||
    error?.message ||
    "The browser could not initialize the camera.";
}

/* =========================================================
   WAIT FOR VIDEO
========================================================= */

async function waitForVideoReady() {
  if (
    video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
    video.videoWidth > 0
  ) {
    await video.play();
    return;
  }

  await new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup();

      reject(
        new Error(
          "Camera opened, but video did not become ready within 10 seconds."
        )
      );
    }, 10000);

    const onReady = async () => {
      cleanup();

      try {
        await video.play();
        resolve();
      } catch (error) {
        reject(error);
      }
    };

    const onError = () => {
      cleanup();

      reject(
        video.error ||
        new Error("Camera video element reported an error.")
      );
    };

    const cleanup = () => {
      window.clearTimeout(timeout);

      video.removeEventListener("loadeddata", onReady);
      video.removeEventListener("canplay", onReady);
      video.removeEventListener("error", onError);
    };

    video.addEventListener("loadeddata", onReady, { once: true });
    video.addEventListener("canplay", onReady, { once: true });
    video.addEventListener("error", onError, { once: true });
  });
}

/* =========================================================
   CAMERA START
========================================================= */

async function activateMagicCamera() {
  if (cameraActive || cameraStarting) return;

  if (!window.isSecureContext) {
    throw new Error(
      "Camera requires HTTPS or localhost. Open http://127.0.0.1:8000."
    );
  }

  if (
    !navigator.mediaDevices ||
    typeof navigator.mediaDevices.getUserMedia !== "function"
  ) {
    throw new Error(
      "Camera API unavailable. Use a current version of Safari on localhost or HTTPS."
    );
  }

  cameraStarting = true;
  cameraButton.disabled = true;

  try {
    setStatus("Requesting camera");
    setFeedback("Waiting for camera permission…");
    setInterpreter("Requesting access to your MacBook camera…");

    try {
      cameraStream =
        await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: {
            width: { ideal: 640 },
            height: { ideal: 480 }
          }
        });

    } catch (firstError) {
      console.warn(
        "First camera request failed. Retrying with default settings.",
        firstError
      );

      cameraStream =
        await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: true
        });
    }

    video.muted = true;
    video.autoplay = true;
    video.playsInline = true;

    video.setAttribute("playsinline", "");

    video.srcObject = cameraStream;
    video.classList.add("camera-visible");

    await waitForVideoReady();

    cameraActive = true;
    lastVideoTime = -1;

    placeholder.hidden = true;

    cameraButton.textContent = "◉ Deactivate Camera";
    cameraButton.classList.remove("primary");
    cameraButton.classList.add("active");

    setStatus("Camera active");

    setFeedback("Camera connected. Loading hand tracking…");

    setInterpreter(
      `Camera connected (${video.videoWidth} × ${video.videoHeight}). Loading hand tracking…`
    );

    try {
      await loadHandTracker();

      trackingAvailable = true;

      setStatus("Camera and tracking active");

      setFeedback(
        "Hand tracking active · Show your hands to the camera."
      );

      setInterpreter(
        "Camera and hand tracking are ready."
      );

      handTrackingLoop();

    } catch (trackingError) {
      trackingAvailable = false;

      console.error(
        "MediaPipe initialization failed:",
        trackingError
      );

      setStatus("Camera active · Tracking unavailable");

      setFeedback(
        "Camera works, but hand tracking could not load."
      );

      setInterpreter(
        `CAMERA IS WORKING. MediaPipe failed: ${describeError(trackingError)}. Check internet access and reload the page.`
      );
    }

  } catch (error) {
    console.error("Camera initialization failed:", error);

    stopMagicCamera();

    const detail =
      `${error?.name || "CameraError"}: ${explainCameraError(error)}`;

    setStatus("Camera error");
    setFeedback(detail);
    setInterpreter(detail);

    throw error;

  } finally {
    cameraStarting = false;
    cameraButton.disabled = false;
  }
}

/* =========================================================
   CAMERA STOP
========================================================= */

function stopMagicCamera() {
  cameraActive = false;
  cameraStarting = false;
  trackingAvailable = false;
  trackingBusy = false;

  if (trackingFrame !== null) {
    cancelAnimationFrame(trackingFrame);
    trackingFrame = null;
  }

  if (cameraStream) {
    cameraStream.getTracks().forEach((track) => {
      track.stop();
    });

    cameraStream = null;
  }

  video.pause();
  video.srcObject = null;
  video.classList.remove("camera-visible");

  cameraButton.textContent = "✧ Activate Camera";
  cameraButton.classList.remove("active");
  cameraButton.classList.add("primary");
  cameraButton.disabled = false;

  if (targetCenter && THREE) {
    targetScale = 1;
    targetRotation = 0;
    targetEnergy = currentConfig.intensity;
    targetCenter.set(0, 0, 0);
  }

  setStatus("Camera off");

  setFeedback(
    "Camera is off · Nothing is being captured"
  );
}

/* =========================================================
   CAMERA BUTTON
========================================================= */

cameraButton.addEventListener("click", async () => {
  if (cameraActive || cameraStarting) {
    stopMagicCamera();
    return;
  }

  try {
    await activateMagicCamera();

  } catch (error) {
    console.error("Camera button failed:", error);
  }
});

/* =========================================================
   WORKSPACE NAVIGATION
========================================================= */

window.addEventListener("jarvis-view-change", () => {
  const magicView = $("magic-view");

  if (!magicView?.classList.contains("active")) {
    stopMagicCamera();
  }

  requestAnimationFrame(resizeRenderer);
});

/* =========================================================
   PAGE CLEANUP
========================================================= */

window.addEventListener("pagehide", () => {
  stopMagicCamera();

  if (animationFrame !== null) {
    cancelAnimationFrame(animationFrame);
    animationFrame = null;
  }

  resizeObserver?.disconnect();

  window.removeEventListener("resize", resizeRenderer);

  disposeParticles();

  handLandmarker?.close();
  handLandmarker = null;

  renderer?.dispose();
  renderer = null;
});

/* =========================================================
   INITIALIZATION

   Register the handler first, then load Three.js.
========================================================= */

setStatus("Loading graphics engine");

setFeedback(
  "Camera is off · Nothing is being captured"
);

setInterpreter(
  "JARVIS Magic Mode is initializing…"
);

loadThreeJS().catch((error) => {
  console.error("Magic Mode startup failed:", error);
});
