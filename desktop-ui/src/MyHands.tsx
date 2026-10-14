import { useEffect, useRef } from "react";
import {
  ArrowRight,
  AudioLines,
  Camera,
  Check,
  Hand,
  MousePointer2,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";

export type CameraStatus = "off" | "starting" | "live" | "error" | "unsupported";
export type TrackerStatus = "off" | "connecting" | "live" | "error";
export type MyHandsEvent = { type: string; [key: string]: unknown };

type WireHand = {
  label?: string;
  score?: number;
  landmarks?: number[][];
};

type CameraBackdropProps = {
  active: boolean;
  deviceId: string;
  onDevices: (devices: MediaDeviceInfo[]) => void;
  onStatus: (status: CameraStatus, error?: string) => void;
  onTrackerStatus: (status: TrackerStatus, error?: string) => void;
  onTrackingEvent: (event: MyHandsEvent) => void;
};

type MyHandsPageProps = {
  cameraEnabled: boolean;
  setCameraEnabled: (next: boolean | ((previous: boolean) => boolean)) => void;
  cameraDevices: MediaDeviceInfo[];
  selectedCameraId: string;
  setSelectedCameraId: (id: string) => void;
  cameraStatus: CameraStatus;
  cameraError: string;
  trackerStatus: TrackerStatus;
  trackerError: string;
  handPresent: boolean;
  lastGesture: string;
  refreshCameraDevices: () => void;
  glassOpacity: number;
  setGlassOpacity: (value: number) => void;
  glassBlur: number;
  setGlassBlur: (value: number) => void;
  glassBloom: number;
  setGlassBloom: (value: number) => void;
};

const isHostedPreview = typeof window !== "undefined" && window.location.hostname.endsWith(".e2b.app");

const HAND_CONNECTIONS: ReadonlyArray<readonly [number, number]> = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20], [0, 17],
];

export function CameraBackdrop({
  active,
  deviceId,
  onDevices,
  onStatus,
  onTrackerStatus,
  onTrackingEvent,
}: CameraBackdropProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const pointerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let disposed = false;
    let stream: MediaStream | null = null;
    let activeTrack: MediaStreamTrack | null = null;
    let socket: WebSocket | null = null;
    let frameTimer = 0;
    let sceneTimer = 0;
    let sceneRefreshTimeout = 0;
    let activeObjectId: string | null = null;
    let encodingFrame = false;
    let latestHands: WireHand[] = [];
    let pointerPosition = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    let pinchTarget: HTMLElement | null = null;
    const mediaDevices = navigator.mediaDevices;

    const refreshDevices = async () => {
      if (!mediaDevices?.enumerateDevices) return;
      try {
        const devices = await mediaDevices.enumerateDevices();
        if (!disposed) onDevices(devices);
      } catch {
        // Device enumeration is advisory and should not interrupt an active stream.
      }
    };

    const getVideoGeometry = () => {
      const canvas = overlayRef.current;
      const video = videoRef.current;
      const bounds = canvas?.getBoundingClientRect();
      const width = bounds?.width || window.innerWidth;
      const height = bounds?.height || window.innerHeight;
      const sourceWidth = video?.videoWidth || 640;
      const sourceHeight = video?.videoHeight || 360;
      const scale = Math.max(width / sourceWidth, height / sourceHeight);
      const drawWidth = sourceWidth * scale;
      const drawHeight = sourceHeight * scale;
      return {
        originX: bounds?.left || 0,
        originY: bounds?.top || 0,
        width,
        height,
        drawWidth,
        drawHeight,
        offsetX: (width - drawWidth) / 2,
        offsetY: (height - drawHeight) / 2,
      };
    };

    const toScreenPoint = (x: number, y: number) => {
      const geometry = getVideoGeometry();
      return {
        x: geometry.originX + geometry.offsetX + x * geometry.drawWidth,
        y: geometry.originY + geometry.offsetY + y * geometry.drawHeight,
      };
    };

    const drawWireframe = () => {
      const canvas = overlayRef.current;
      const context = canvas?.getContext("2d");
      if (!canvas || !context) return;

      const geometry = getVideoGeometry();
      const pixelRatio = window.devicePixelRatio || 1;
      const width = geometry.width;
      const height = geometry.height;
      if (!width || !height) return;
      const pixelWidth = Math.round(width * pixelRatio);
      const pixelHeight = Math.round(height * pixelRatio);
      if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
        canvas.width = pixelWidth;
        canvas.height = pixelHeight;
      }
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      context.clearRect(0, 0, width, height);

      latestHands.forEach((hand, handIndex) => {
        const landmarks = hand.landmarks;
        if (!Array.isArray(landmarks) || landmarks.length < 21) return;
        const points = landmarks.slice(0, 21).map((point) => {
          if (!Array.isArray(point) || point.length < 2) return null;
          const x = Number(point[0]);
          const y = Number(point[1]);
          if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
          // The camera preview is mirrored, so mirror the landmarks to the same coordinates.
          return { x: geometry.offsetX + (1 - x) * geometry.drawWidth, y: geometry.offsetY + y * geometry.drawHeight };
        });
        if (points.some((point) => point === null)) return;

        const color = hand.label?.toLowerCase() === "left" || handIndex === 0
          ? "#ffdf4f"
          : "#74e7dc";
        context.save();
        context.globalAlpha = Math.max(0.55, Math.min(1, Number(hand.score ?? 1)));
        context.lineWidth = 2.2;
        context.lineCap = "round";
        context.lineJoin = "round";
        context.strokeStyle = color;
        context.shadowColor = color;
        context.shadowBlur = 9;
        context.beginPath();
        HAND_CONNECTIONS.forEach(([start, end]) => {
          const a = points[start];
          const b = points[end];
          if (!a || !b) return;
          context.moveTo(a.x, a.y);
          context.lineTo(b.x, b.y);
        });
        context.stroke();
        context.shadowBlur = 5;
        points.forEach((point, index) => {
          if (!point) return;
          context.beginPath();
          context.arc(point.x, point.y, index === 0 ? 4 : 3, 0, Math.PI * 2);
          context.fillStyle = color;
          context.fill();
          context.strokeStyle = "rgba(7,10,14,.85)";
          context.lineWidth = 1;
          context.stroke();
        });
        context.restore();
      });
    };

    const findClickable = (x: number, y: number) => {
      const element = document.elementFromPoint(x, y);
      const target = element?.closest("button:not(:disabled), a[href], [role='button']");
      return target instanceof HTMLElement ? target : null;
    };

    const clamp = (value: number, minimum: number, maximum: number) => Math.max(minimum, Math.min(maximum, value));

    const sendScene = () => {
      if (socket?.readyState !== WebSocket.OPEN || activeObjectId) return;
      const target = document.querySelector<HTMLElement>("[data-myhands-target='glass-card']");
      if (!target) return;
      const bounds = target.getBoundingClientRect();
      const geometry = getVideoGeometry();
      const x = clamp((bounds.left - geometry.originX - geometry.offsetX) / geometry.drawWidth, 0, 0.99);
      const y = clamp((bounds.top - geometry.originY - geometry.offsetY) / geometry.drawHeight, 0, 0.99);
      const width = clamp(bounds.width / geometry.drawWidth, 0.01, 1 - x);
      const height = clamp(bounds.height / geometry.drawHeight, 0.01, 1 - y);
      socket.send(JSON.stringify({
        type: "scene",
        objects: [{ id: "glass-card", x, y, w: width, h: height, z: 10 }],
      }));
    };

    const placeSceneObject = (x: number, y: number) => {
      const target = document.querySelector<HTMLElement>("[data-myhands-target='glass-card']");
      const stage = target?.closest<HTMLElement>(".hands-stage");
      if (!target || !stage) return;
      const geometry = getVideoGeometry();
      const stageBounds = stage.getBoundingClientRect();
      const screenX = geometry.originX + geometry.offsetX + x * geometry.drawWidth;
      const screenY = geometry.originY + geometry.offsetY + y * geometry.drawHeight;
      const maximumLeft = Math.max(0, stageBounds.width - target.offsetWidth);
      const maximumTop = Math.max(0, stageBounds.height - target.offsetHeight);
      target.style.right = "auto";
      target.style.left = `${clamp(screenX - stageBounds.left, 0, maximumLeft)}px`;
      target.style.top = `${clamp(screenY - stageBounds.top, 0, maximumTop)}px`;
    };

    const processTrackingEvent = (event: MyHandsEvent) => {
      onTrackingEvent(event);
      if (event.type === "hand_landmarks") {
        latestHands = Array.isArray(event.hands) ? event.hands as WireHand[] : [];
        drawWireframe();
      } else if (event.type === "cursor_moved") {
        const x = Number(event.x);
        const y = Number(event.y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) return;
        pointerPosition = toScreenPoint(x, y);
        const pointer = pointerRef.current;
        if (pointer) {
          pointer.hidden = false;
          pointer.style.left = `${pointerPosition.x}px`;
          pointer.style.top = `${pointerPosition.y}px`;
        }
      } else if (event.type === "pinch_started") {
        const pointer = pointerRef.current;
        pointer?.classList.add("pinched");
        const x = Number(event.x);
        const y = Number(event.y);
        const screenPosition = Number.isFinite(x) && Number.isFinite(y) ? toScreenPoint(x, y) : pointerPosition;
        pinchTarget = findClickable(screenPosition.x, screenPosition.y);
      } else if (event.type === "pinch_released") {
        pointerRef.current?.classList.remove("pinched");
        const currentTarget = findClickable(pointerPosition.x, pointerPosition.y);
        if (pinchTarget?.isConnected && currentTarget && (currentTarget === pinchTarget || pinchTarget.contains(currentTarget))) {
          pinchTarget.click();
        }
        pinchTarget = null;
      } else if (event.type === "object_grabbed") {
        activeObjectId = String(event.id ?? "glass-card");
        pointerRef.current?.classList.add("pinched");
      } else if (event.type === "object_dragged") {
        if (String(event.id ?? "") === "glass-card") {
          placeSceneObject(Number(event.x), Number(event.y));
        }
      } else if (event.type === "object_released") {
        if (String(event.id ?? activeObjectId ?? "") === "glass-card") {
          placeSceneObject(Number(event.x), Number(event.y));
          activeObjectId = null;
          window.clearTimeout(sceneRefreshTimeout);
          sceneRefreshTimeout = window.setTimeout(sendScene, 60);
        }
      } else if (event.type === "fist_started") {
        pointerRef.current?.classList.add("pinched");
      } else if (event.type === "fist_released" || event.type === "hand_lost") {
        pointerRef.current?.classList.remove("pinched");
        if (event.type === "hand_lost") {
          if (pointerRef.current) pointerRef.current.hidden = true;
          pinchTarget = null;
        }
      } else if (event.type === "session_stopped") {
        if (pointerRef.current) pointerRef.current.hidden = true;
        pinchTarget = null;
        activeObjectId = null;
        latestHands = [];
        drawWireframe();
        if (event.reason !== "tracker_failed" && event.reason !== "camera_failed") {
          onTrackerStatus("off");
        }
      } else if (event.type === "tracking_unavailable" || event.type === "transport_error") {
        const message = String(event.reason ?? event.message ?? "Hand tracking is unavailable.");
        onTrackerStatus("error", message);
      }
    };

    const connectTracker = () => {
      onTrackerStatus("connecting");
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${window.location.host}/ws/myhands`);
      socket.binaryType = "arraybuffer";

      socket.onopen = () => {
        if (disposed || !socket) return;
        onTrackerStatus("live");
        sendScene();
        sceneTimer = window.setInterval(sendScene, 250);
        const frameCanvas = document.createElement("canvas");
        const frameContext = frameCanvas.getContext("2d", { alpha: false });
        if (!frameContext) {
          onTrackerStatus("error", "Could not create the camera frame encoder.");
          return;
        }
        const sendFrame = () => {
          const video = videoRef.current;
          if (
            disposed || !video || video.videoWidth < 2 || video.videoHeight < 2
            || socket?.readyState !== WebSocket.OPEN || encodingFrame
            || socket.bufferedAmount > 180_000
          ) return;
          const scale = Math.min(1, 640 / video.videoWidth, 360 / video.videoHeight);
          const width = Math.max(2, Math.round(video.videoWidth * scale));
          const height = Math.max(2, Math.round(video.videoHeight * scale));
          if (frameCanvas.width !== width || frameCanvas.height !== height) {
            frameCanvas.width = width;
            frameCanvas.height = height;
          }
          frameContext.drawImage(video, 0, 0, width, height);
          encodingFrame = true;
          frameCanvas.toBlob((blob) => {
            encodingFrame = false;
            if (blob && !disposed && socket?.readyState === WebSocket.OPEN && socket.bufferedAmount <= 180_000) {
              socket.send(blob);
            }
          }, "image/jpeg", 0.58);
        };
        frameTimer = window.setInterval(sendFrame, 50);
      };

      socket.onmessage = (message) => {
        if (disposed) return;
        try {
          const payload = JSON.parse(String(message.data)) as { event?: MyHandsEvent; type?: string };
          const event = payload.event ?? (payload as MyHandsEvent);
          if (event && typeof event.type === "string") processTrackingEvent(event);
        } catch {
          // Ignore malformed service messages; the next event can still recover the view.
        }
      };

      socket.onerror = () => {
        if (!disposed) onTrackerStatus("error", "The local My Hands tracker is not reachable.");
      };
      socket.onclose = (event) => {
        if (!disposed && event.code !== 1000) {
          onTrackerStatus("error", event.reason || "The My Hands tracker disconnected.");
        }
      };
    };

    const startCamera = async () => {
      if (!active) {
        onStatus("off");
        onTrackerStatus("off");
        return;
      }
      if (!mediaDevices?.getUserMedia) {
        const error = "This webview does not expose camera access.";
        onStatus("unsupported", error);
        onTrackerStatus("error", error);
        return;
      }

      onStatus("starting");
      try {
        const video: MediaTrackConstraints = {
          width: { ideal: 1920 },
          height: { ideal: 1080 },
          ...(deviceId ? { deviceId: { exact: deviceId } } : { facingMode: "user" }),
        };
        stream = await mediaDevices.getUserMedia({ video, audio: false });
        if (disposed) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        const videoElement = videoRef.current;
        if (videoElement) {
          videoElement.srcObject = stream;
          await videoElement.play().catch(() => undefined);
        }
        await refreshDevices();
        if (disposed) return;

        activeTrack = stream.getVideoTracks()[0] ?? null;
        activeTrack?.addEventListener("ended", handleTrackEnded);
        onStatus("live");
        mediaDevices.addEventListener?.("devicechange", refreshDevices);
        connectTracker();
      } catch (error) {
        const message = error instanceof Error ? error.message : "Camera could not be opened.";
        if (!disposed) {
          onStatus("error", message);
          onTrackerStatus("error", message);
        }
      }
    };

    function handleTrackEnded() {
      if (!disposed) {
        const message = "The camera stream ended. Check that the camera is still connected.";
        onStatus("error", message);
        onTrackerStatus("error", message);
      }
    }

    const handleViewportChange = () => {
      drawWireframe();
      sendScene();
    };

    void startCamera();
    window.addEventListener("resize", handleViewportChange);
    document.addEventListener("scroll", sendScene, true);
    return () => {
      disposed = true;
      window.removeEventListener("resize", handleViewportChange);
      document.removeEventListener("scroll", sendScene, true);
      window.clearInterval(frameTimer);
      window.clearInterval(sceneTimer);
      window.clearTimeout(sceneRefreshTimeout);
      mediaDevices?.removeEventListener?.("devicechange", refreshDevices);
      activeTrack?.removeEventListener("ended", handleTrackEnded);
      socket?.close(1000, "My Hands closed");
      stream?.getTracks().forEach((track) => track.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
      if (pointerRef.current) {
        pointerRef.current.hidden = true;
        pointerRef.current.classList.remove("pinched");
      }
      pinchTarget = null;
      latestHands = [];
      drawWireframe();
      onTrackerStatus("off");
    };
  }, [active, deviceId, onDevices, onStatus, onTrackerStatus, onTrackingEvent]);

  if (!active) return null;
  return (
    <>
      <div className="camera-backdrop" aria-hidden="true">
        <video ref={videoRef} autoPlay muted playsInline />
        <div className="camera-vignette" />
        <canvas ref={overlayRef} className="camera-wireframe" />
      </div>
      <div ref={pointerRef} className="hands-pointer" aria-hidden="true" hidden>
        <span />
      </div>
    </>
  );
}

export function MyHandsPage({
  cameraEnabled,
  setCameraEnabled,
  cameraDevices,
  selectedCameraId,
  setSelectedCameraId,
  cameraStatus,
  cameraError,
  trackerStatus,
  trackerError,
  handPresent,
  lastGesture,
  refreshCameraDevices,
  glassOpacity,
  setGlassOpacity,
  glassBlur,
  setGlassBlur,
  glassBloom,
  setGlassBloom,
}: MyHandsPageProps) {
  const isLive = cameraEnabled && cameraStatus === "live";
  const statusText = cameraStatus === "live"
    ? "LIVE · VIDEO ONLY"
    : cameraStatus === "starting"
      ? "REQUESTING CAMERA"
      : cameraStatus === "unsupported"
        ? "CAMERA UNAVAILABLE"
        : cameraStatus === "error"
          ? "CAMERA NEEDS ATTENTION"
          : "CAMERA OFF";
  const trackerText = trackerStatus === "live"
    ? "TRACKING LIVE"
    : trackerStatus === "connecting"
      ? "CONNECTING"
      : trackerStatus === "error"
        ? "TRACKER NEEDS ATTENTION"
        : "TRACKING OFF";
  const handText = handPresent ? "Hand found · pointer follows" : trackerStatus === "live" ? "Move a hand into the camera view" : trackerText;

  return (
    <div className="content-wrap subpage-wrap hands-page">
      <div className="page-heading-row">
        <div>
          <div className="eyebrow"><span className="eyebrow-mark" />MY HANDS · GLASS MODE</div>
          <h1>Your world,<br /><span>through the glass.</span></h1>
          <p>Use your webcam as a live background. The camera opens only when you enable this mode; frames go to the separate My Hands tracker.</p>
        </div>
        <div className={`read-only-chip camera-chip${isLive ? " camera-chip-live" : ""}`}><Camera size={15} />{statusText}</div>
      </div>

      <div className="hands-layout">
        <div className="hands-main-column">
          <section className="panel hands-preview-card">
            <div className="hands-card-heading">
              <div className="hands-heading-icon"><Camera size={16} /></div>
              <div className="hands-heading-copy"><strong>Camera glass</strong><small>The live feed sits behind the entire Super AI Agent interface.</small></div>
              <button className={cameraEnabled ? "outline-button hands-toggle" : "primary-button hands-toggle"} onClick={() => setCameraEnabled((current) => !current)}>
                {cameraEnabled ? "Turn camera off" : "Enable camera"}<ArrowRight size={14} />
              </button>
            </div>

            <div className={`hands-stage${isLive ? " live" : ""}`}>
              <div className="hands-stage-grid" />
              <div className="glass-sample-card" data-myhands-target="glass-card">
                <div className="glass-sample-kicker"><Sparkles size={13} />FROSTED INTERFACE</div>
                <h2>My Hands</h2>
                <p>Pinch-grab this card, move your hand, then release to see the tracking respond.</p>
                <div className="glass-sample-footer"><span className="yellow-sample-dot" />{isLive ? handText : "Previewing glass surface"}<span className="glass-sample-line" /></div>
              </div>
              <div className="hand-track-preview">
                <div className="hand-track-icon"><Hand size={25} strokeWidth={1.35} /></div>
                <div><strong>Wireframe hand</strong><small>{handText}</small></div>
                <span className={`tracking-state ${trackerStatus}`}>{trackerText}</span>
              </div>
              {!isLive && (
                <div className="hands-stage-empty">
                  <div className="camera-empty-icon"><Camera size={21} /></div>
                  <strong>{cameraStatus === "error" ? "Camera could not start" : "Turn on the camera to preview the glass"}</strong>
                  <span>{cameraError || "This requests video only; it does not open or change your microphone."}</span>
                </div>
              )}
              {isLive && <div className="hands-live-label"><span className="pulse-dot" />CAMERA BACKGROUND ACTIVE</div>}
            </div>

            <div className="hands-card-footer"><ShieldCheck size={14} /><span>{isHostedPreview ? "Hosted preview sends video frames to the Arena sandbox sidecar · not recorded" : "Video-only · local sidecar processing · not recorded"}</span><span className="hands-camera-name">{cameraDevices.find((device) => device.deviceId === selectedCameraId)?.label || "System-selected camera"}</span></div>
          </section>

          <section className="panel tracking-card">
            <div className="tracking-icon"><Hand size={19} /></div>
            <div className="tracking-copy"><div className="eyebrow">GESTURE LAYER · {trackerText}</div><h3>Wireframe aligned to your hand</h3><p>The existing My Hands tracker reads the whole hand. Its wireframe follows the same camera image; pinch can move the glass card, while a pinch on a control activates it.</p></div>
            <div className="tracking-right"><span className="planned-tag">{lastGesture}</span><MousePointer2 size={19} /></div>
          </section>
          {trackerError && <div className="tracker-error-note"><span className="status-dot muted" />{trackerError}</div>}
        </div>

        <aside className="hands-control-column">
          <section className="panel hands-settings-card">
            <div className="hands-section-title"><div><div className="eyebrow">DEVICE</div><h3>Choose your camera</h3></div><button className="icon-button small" title="Refresh camera list" onClick={refreshCameraDevices}><RefreshCw size={14} /></button></div>
            <label className="device-label" htmlFor="camera-choice">WEBCAM</label>
            <select id="camera-choice" className="device-select" value={selectedCameraId} onChange={(event) => setSelectedCameraId(event.target.value)}>
              <option value="">System default camera</option>
              {cameraDevices.map((device, index) => <option key={device.deviceId || index} value={device.deviceId}>{device.label || `Camera ${index + 1} (allow camera access to show its name)`}</option>)}
            </select>
            <div className="device-helper"><span className={`status-dot ${isLive ? "good" : "muted"}`} />{isLive ? "Using this camera for My Hands video and tracking." : "Camera list comes from the current operating system/webview."}</div>
            <div className="camera-mic-note"><Check size={13} /><span>Microphone is not opened by My Hands.</span></div>
          </section>

          <section className="panel hands-settings-card glass-settings-card">
            <div className="hands-section-title"><div><div className="eyebrow">GLASS MATERIAL</div><h3>Shape the surface</h3></div><SlidersHorizontal size={16} /></div>
            <GlassSlider label="Transparency" hint="Less tint lets more of the camera show." value={glassOpacity} min={18} max={82} suffix="%" onChange={setGlassOpacity} />
            <GlassSlider label="Sand-blast blur" hint="Frosts the image behind each panel." value={glassBlur} min={0} max={32} suffix="px" onChange={setGlassBlur} />
            <GlassSlider label="Yellow bloom" hint="Soft glow on the outline and active controls." value={glassBloom} min={0} max={100} suffix="%" onChange={setGlassBloom} />
            <div className="glass-settings-foot"><span className="yellow-sample-dot" />Live preview settings</div>
          </section>

          <section className="panel audio-route-note">
            <div className="audio-route-icon"><AudioLines size={16} /></div>
            <div><strong>JARVIS audio stays separate</strong><p>Microphone and speaker selection will use the existing Python OS device list. This camera view will not start a second mic stream.</p></div>
          </section>
        </aside>
      </div>
    </div>
  );
}

function GlassSlider({ label, hint, value, min, max, suffix, onChange }: { label: string; hint: string; value: number; min: number; max: number; suffix: string; onChange: (value: number) => void }) {
  return (
    <label className="glass-slider-row">
      <span className="glass-slider-top"><strong>{label}</strong><output>{value}{suffix}</output></span>
      <input type="range" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.target.value))} />
      <small>{hint}</small>
    </label>
  );
}
