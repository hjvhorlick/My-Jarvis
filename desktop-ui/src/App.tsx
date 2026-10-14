import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  Bell,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileImage,
  Hand,
  Images,
  LayoutDashboard,
  Mail,
  Megaphone,
  Mic,
  Moon,
  PanelLeftClose,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  WandSparkles,
  X,
  Zap,
  Plug,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { CameraBackdrop, MyHandsPage } from "./MyHands";
import type { CameraStatus, MyHandsEvent, TrackerStatus } from "./MyHands";

type Page = "overview" | "assistant" | "my-hands" | "connections" | "settings" | "studio" | "email" | "assets";
type Message = { role: "user" | "system"; text: string };

type NavItem = {
  id: Page;
  label: string;
  icon: LucideIcon;
  status?: "planned";
};

const workspaceItems: NavItem[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "assistant", label: "Assistant", icon: Sparkles },
  { id: "my-hands", label: "My Hands", icon: Hand },
  { id: "studio", label: "Marketing studio", icon: Megaphone, status: "planned" },
  { id: "email", label: "Email workspace", icon: Mail, status: "planned" },
  { id: "assets", label: "Asset library", icon: Images, status: "planned" },
];

const manageItems: NavItem[] = [
  { id: "connections", label: "Connections", icon: Plug },
  { id: "settings", label: "Settings", icon: Settings2 },
];

const pageNames: Record<Page, string> = {
  overview: "Overview",
  assistant: "Assistant preview",
  "my-hands": "My Hands",
  connections: "Connections",
  settings: "Settings",
  studio: "Marketing studio",
  email: "Email workspace",
  assets: "Asset library",
};

function App() {
  const [page, setPage] = useState<Page>("overview");
  const [calmTheme, setCalmTheme] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [notice, setNotice] = useState("");
  const [cameraEnabled, setCameraEnabled] = useState(false);
  const [cameraDevices, setCameraDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedCameraId, setSelectedCameraId] = useState("");
  const [cameraStatus, setCameraStatus] = useState<CameraStatus>("off");
  const [cameraError, setCameraError] = useState("");
  const [trackerStatus, setTrackerStatus] = useState<TrackerStatus>("off");
  const [trackerError, setTrackerError] = useState("");
  const [handPresent, setHandPresent] = useState(false);
  const [lastGesture, setLastGesture] = useState("Tracking is off");
  const [glassOpacity, setGlassOpacity] = useState(55);
  const [glassBlur, setGlassBlur] = useState(18);
  const [glassBloom, setGlassBloom] = useState(52);
  const [messages, setMessages] = useState<Message[]>([
    { role: "system", text: "This is a visual preview. The JARVIS voice agent is not connected." },
  ]);
  const [draft, setDraft] = useState("");

  const receiveCameraDevices = useCallback((devices: MediaDeviceInfo[]) => {
    const cameras = devices.filter((device) => device.kind === "videoinput");
    setCameraDevices(cameras);
    setSelectedCameraId((current) => cameras.some((device) => device.deviceId === current) ? current : "");
  }, []);

  const receiveCameraStatus = useCallback((status: CameraStatus, error = "") => {
    setCameraStatus(status);
    setCameraError(error);
  }, []);

  const receiveTrackerStatus = useCallback((status: TrackerStatus, error = "") => {
    setTrackerStatus(status);
    setTrackerError(error);
    if (status === "off") setLastGesture("Tracking is off");
    else if (status === "connecting") setLastGesture("Connecting to local tracker");
    else if (status === "live") setLastGesture("Looking for a hand");
    else setLastGesture("Tracker unavailable");
    if (status !== "live") setHandPresent(false);
  }, []);

  const receiveTrackingEvent = useCallback((event: MyHandsEvent) => {
    if (event.type === "hand_detected") {
      setHandPresent(true);
      setLastGesture("Hand detected · pointer following");
    } else if (event.type === "hand_lost") {
      setHandPresent(false);
      setLastGesture("No hand detected");
    } else if (event.type === "hand_landmarks") {
      setHandPresent(Array.isArray(event.hands) && event.hands.length > 0);
    } else if (event.type === "pinch_started") {
      setLastGesture("Pinch · pointer press");
    } else if (event.type === "pinch_released") {
      setLastGesture("Pinch released");
    } else if (event.type === "object_grabbed") {
      setLastGesture("Glass card grabbed");
    } else if (event.type === "object_dragged") {
      setLastGesture("Moving glass card");
    } else if (event.type === "object_released") {
      setLastGesture("Glass card released");
    } else if (event.type === "fist_started") {
      setLastGesture("Fist grip");
    } else if (event.type === "fist_released") {
      setLastGesture("Fist released");
    } else if (event.type === "scale_started") {
      setLastGesture("Two-hand scale");
    } else if (event.type === "scale_ended") {
      setLastGesture("Scale released");
    } else if (event.type === "clap") {
      setLastGesture("Clap detected");
    } else if (event.type === "pull_started") {
      setLastGesture("Pull gesture");
    } else if (event.type === "pull_ended") {
      setLastGesture("Pull released");
    } else if (event.type === "rotate_started") {
      setLastGesture("Rotate gesture");
    } else if (event.type === "rotate_ended") {
      setLastGesture("Rotate released");
    } else if (event.type === "tracking_unavailable" || event.type === "transport_error") {
      const message = String(event.reason ?? event.message ?? "Hand tracking is unavailable.");
      setTrackerStatus("error");
      setTrackerError(message);
      setLastGesture("Tracker unavailable");
    }
  }, []);

  const refreshCameraDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) {
      receiveCameraStatus("unsupported", "Camera access is unavailable in this webview.");
      return;
    }
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      receiveCameraDevices(devices);
      if (!devices.some((device) => device.kind === "videoinput")) {
        setCameraError("No cameras were reported by the operating system.");
      } else {
        setCameraError("");
      }
    } catch (error) {
      receiveCameraStatus("error", error instanceof Error ? error.message : "Could not list cameras.");
    }
  }, [receiveCameraDevices, receiveCameraStatus]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 3000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  function openPage(next: Page) {
    if (page === "my-hands" && next !== "my-hands") setCameraEnabled(false);
    setPage(next);
  }

  function showNotice(text: string) {
    setNotice(text);
  }

  function submitPreviewMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setMessages((items) => [
      ...items,
      { role: "user", text },
      { role: "system", text: "Preview only — nothing was sent to the voice agent." },
    ]);
    setDraft("");
  }

  const dateLabel = new Intl.DateTimeFormat("en-ZA", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(new Date());

  return (
    <div
      className={`app-shell${calmTheme ? " calm-theme" : ""}${sidebarCollapsed ? " sidebar-collapsed" : ""}${page === "my-hands" ? " hands-mode" : ""}`}
      style={{
        "--glass-blur": `${glassBlur}px`,
        "--glass-alpha": `${(100 - glassOpacity) / 100}`,
        "--glass-bloom": `${glassBloom / 320}`,
      } as React.CSSProperties}
    >
      <CameraBackdrop
        active={page === "my-hands" && cameraEnabled}
        deviceId={selectedCameraId}
        onDevices={receiveCameraDevices}
        onStatus={receiveCameraStatus}
        onTrackerStatus={receiveTrackerStatus}
        onTrackingEvent={receiveTrackingEvent}
      />
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark"><span>S</span><i /></div>
          {!sidebarCollapsed && (
            <div className="brand-copy">
              <div className="brand-name">SUPER AI AGENT</div>
              <div className="brand-caption">ONE WORKSPACE · MANY CHARACTERS</div>
            </div>
          )}
          <button
            className="sidebar-collapse icon-button"
            aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() => setSidebarCollapsed((value) => !value)}
          >
            <PanelLeftClose size={16} />
          </button>
        </div>

        <div className="workspace-switcher character-switcher" title={sidebarCollapsed ? "Active character: JARVIS" : undefined}>
          <div className="workspace-avatar character-avatar">J</div>
          {!sidebarCollapsed && <><div className="workspace-label"><strong>JARVIS</strong><small>Voice & personality</small></div><span className="character-live-mark" /><span className="character-selected-tag">ACTIVE</span></>}
        </div>

        <nav className="side-nav" aria-label="Main navigation">
          <div className="nav-group-label">WORKSPACE</div>
          {workspaceItems.map((item) => (
            <NavButton
              key={item.id}
              item={item}
              active={page === item.id}
              collapsed={sidebarCollapsed}
              onClick={() => openPage(item.id)}
            />
          ))}
          <div className="nav-separator" />
          <div className="nav-group-label">MANAGE</div>
          {manageItems.map((item) => (
            <NavButton
              key={item.id}
              item={item}
              active={page === item.id}
              collapsed={sidebarCollapsed}
              onClick={() => openPage(item.id)}
            />
          ))}
        </nav>

        <div className="sidebar-spacer" />
        {!sidebarCollapsed && (
          <div className="agent-isolation-card">
            <div className="isolation-icon"><ShieldCheck size={15} /></div>
            <div><strong>Voice core protected</strong><small>Not connected in this preview</small></div>
            <span className="status-dot muted" />
          </div>
        )}
        <button className="help-link" onClick={() => showNotice("Help and onboarding can be added after the visual direction is approved.")}>
          <CircleHelp size={17} />{!sidebarCollapsed && <span>Help & feedback</span>}
        </button>
        <div className="sidebar-footer">
          <div className="profile-chip"><div className="profile-avatar">V</div>{!sidebarCollapsed && <><div className="profile-copy"><strong>Local user</strong><small>Workspace owner</small></div><button className="more-button" onClick={() => showNotice("Profile options are preview-only.")} aria-label="Profile options"><ChevronDown size={15} /></button></>}</div>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="crumbs"><span>Workspace</span><ChevronRight size={13} /><strong>{pageNames[page]}</strong></div>
          <div className="topbar-actions">
            <div className="environment-pill"><span className="pulse-dot" />UI PREVIEW</div>
            <button className="top-icon-button" title="Search (preview only)" onClick={() => showNotice("Search will be connected after the UI direction is approved.")}><Search size={17} /><kbd>⌘ K</kbd></button>
            <button className="top-icon-button notification-button" title="Notifications" onClick={() => showNotice("You are all caught up.")}><Bell size={17} /><i /></button>
            <div className="top-divider" />
            <button className="theme-toggle" title={calmTheme ? "Switch to dark theme" : "Switch to soft theme"} onClick={() => setCalmTheme((value) => !value)}>
              {calmTheme ? <Moon size={16} /> : <Sun size={16} />}
            </button>
            <div className="top-avatar">V</div>
          </div>
        </header>

        <div className="page-scroll">
          {page === "overview" && <Overview onNavigate={openPage} onNotice={showNotice} dateLabel={dateLabel} />}
          {page === "assistant" && <AssistantPreview messages={messages} draft={draft} setDraft={setDraft} onSubmit={submitPreviewMessage} onNotice={showNotice} />}
          {page === "my-hands" && <MyHandsPage cameraEnabled={cameraEnabled} setCameraEnabled={setCameraEnabled} cameraDevices={cameraDevices} selectedCameraId={selectedCameraId} setSelectedCameraId={setSelectedCameraId} cameraStatus={cameraStatus} cameraError={cameraError} trackerStatus={trackerStatus} trackerError={trackerError} handPresent={handPresent} lastGesture={lastGesture} refreshCameraDevices={refreshCameraDevices} glassOpacity={glassOpacity} setGlassOpacity={setGlassOpacity} glassBlur={glassBlur} setGlassBlur={setGlassBlur} glassBloom={glassBloom} setGlassBloom={setGlassBloom} />}
          {page === "connections" && <ConnectionsPage onNotice={showNotice} />}
          {page === "settings" && <SettingsPage calmTheme={calmTheme} setCalmTheme={setCalmTheme} onNotice={showNotice} />}
          {page === "studio" && <PlannedPage kind="studio" onNotice={showNotice} />}
          {page === "email" && <PlannedPage kind="email" onNotice={showNotice} />}
          {page === "assets" && <PlannedPage kind="assets" onNotice={showNotice} />}
          <footer className="page-footer"><span>SUPER AI AGENT · VISUAL PROTOTYPE</span><span>Voice engine unchanged <span className="footer-sep">·</span> Local preview only</span></footer>
        </div>
      </main>
      {notice && <div className="toast"><span className="toast-mark"><Check size={14} /></span>{notice}<button onClick={() => setNotice("")} aria-label="Dismiss"><X size={14} /></button></div>}
    </div>
  );
}

function NavButton({ item, active, collapsed, onClick }: { item: NavItem; active: boolean; collapsed: boolean; onClick: () => void }) {
  const Icon = item.icon;
  return (
    <button className={`nav-item${active ? " active" : ""}${item.status ? " planned" : ""}`} onClick={onClick} title={collapsed ? item.label : undefined}>
      <Icon size={18} strokeWidth={1.8} />
      {!collapsed && <><span>{item.label}</span>{item.status ? <small className="soon-tag">LATER</small> : null}</>}
      {collapsed && item.status ? <span className="nav-status-dot" /> : null}
    </button>
  );
}

function Overview({ onNavigate, onNotice, dateLabel }: { onNavigate: (page: Page) => void; onNotice: (text: string) => void; dateLabel: string }) {
  return (
    <div className="content-wrap">
      <div className="welcome-row">
        <div>
          <div className="eyebrow"><span className="eyebrow-mark" />YOUR SPACE · {dateLabel.toUpperCase()}</div>
          <h1>A clearer space<br /><span>for bigger ideas.</span></h1>
          <p className="welcome-copy">A fresh home for your assistant, creative work, and the tools you use every day.</p>
        </div>
        <div className="welcome-orbit" aria-hidden="true">
          <div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="orbit orbit-three" />
          <div className="orbit-core"><Sparkles size={25} /></div>
          <span className="orbit-star star-a">✦</span><span className="orbit-star star-b">·</span><span className="orbit-star star-c">✦</span>
        </div>
      </div>

      <section className="hero-grid">
        <div className="assistant-card panel">
          <div className="card-topline"><div className="card-kicker"><span className="tiny-icon"><AudioLines size={14} /></span>ACTIVE CHARACTER · JARVIS</div><span className="badge badge-neutral"><span className="status-dot muted" />Not connected</span></div>
          <div className="assistant-card-body">
            <div className="assistant-copy">
              <div className="core-label"><ShieldCheck size={14} /> CORE LEFT UNTOUCHED</div>
              <h2>Your assistant,<br /><span>in a new workspace.</span></h2>
              <p>This is a UI-only Tauri preview. JARVIS is the current voice/personality character; the agent, prompts, and session logic have not been changed or connected.</p>
              <button className="primary-button" onClick={() => onNavigate("assistant")}>Explore assistant view <ArrowRight size={16} /></button>
            </div>
            <div className="voice-visual" aria-hidden="true">
              <div className="voice-halo halo-outer" /><div className="voice-halo halo-inner" />
              <div className="voice-core"><AudioLines size={27} strokeWidth={1.6} /></div>
              <div className="voice-equalizer">{Array.from({ length: 25 }).map((_, i) => <i key={i} style={{ "--bar": `${18 + ((i * 17 + 11) % 36)}px`, "--delay": `${(i % 7) * 0.12}s` } as React.CSSProperties} />)}</div>
              <div className="voice-caption"><span className="status-dot muted" />Awaiting local bridge</div>
            </div>
          </div>
          <div className="assistant-card-foot"><span><span className="foot-dot" />No connection to the Python agent</span><button className="text-button" onClick={() => onNotice("Agent connection is intentionally disabled in this prototype.")}>How this works <ArrowUpRight size={14} /></button></div>
        </div>

        <div className="start-card panel">
          <div className="start-icon"><WandSparkles size={20} /></div>
          <div className="eyebrow muted-eyebrow">A NEW START</div>
          <h3>Make it<br />feel like yours.</h3>
          <p>Shape your workspace now. Connect the bigger capabilities when you’re ready.</p>
          <button className="outline-button" onClick={() => onNavigate("settings")}>Explore appearance <ArrowRight size={15} /></button>
          <div className="start-watermark">✳</div>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading"><div><div className="eyebrow">YOUR WORKSPACE</div><h2>Rooms for what’s next</h2></div><button className="subtle-button" onClick={() => onNotice("Workspace modules are visual placeholders for now.")}>View roadmap <ArrowUpRight size={14} /></button></div>
        <div className="module-grid">
          <ModuleCard icon={Megaphone} iconClass="violet" title="Marketing studio" description="Campaign ideas, briefs, and content in one place." tag="PLANNED" onClick={() => onNavigate("studio")} />
          <ModuleCard icon={Mail} iconClass="mint" title="Email workspace" description="Drafts, templates, and account connections." tag="PLANNED" onClick={() => onNavigate("email")} />
          <ModuleCard icon={FileImage} iconClass="amber" title="Asset library" description="A home for creative files and sourced assets." tag="PLANNED" onClick={() => onNavigate("assets")} />
        </div>
      </section>

      <section className="bottom-grid">
        <div className="panel activity-panel">
          <div className="section-heading compact"><div><div className="eyebrow">RECENT ACTIVITY</div><h2>A quiet start</h2></div><button className="more-button" onClick={() => onNotice("Activity history is not connected in this visual preview.")} aria-label="More activity options"><span>···</span></button></div>
          <div className="empty-activity"><div className="empty-icon"><Activity size={19} /></div><div><strong>Your activity will show up here</strong><p>This preview doesn’t read or change your current JARVIS history.</p></div></div>
          <div className="activity-note"><span className="activity-check"><Check size={12} /></span><span>Visual shell ready to explore</span><small>LOCAL PREVIEW</small></div>
        </div>
        <div className="panel status-panel">
          <div className="section-heading compact"><div><div className="eyebrow">SYSTEM STATUS</div><h2>Connections</h2></div><button className="icon-button small" onClick={() => onNavigate("connections")} aria-label="Open connections"><ArrowUpRight size={15} /></button></div>
          <ConnectionRow icon={AudioLines} title="Voice agent" status="Not connected" tone="quiet" />
          <ConnectionRow icon={Plug} title="External services" status="Not configured" tone="quiet" />
          <ConnectionRow icon={ShieldCheck} title="Core protection" status="Enabled" tone="good" />
          <button className="manage-connections" onClick={() => onNavigate("connections")}>Manage connections <ArrowRight size={14} /></button>
        </div>
      </section>
    </div>
  );
}

function ModuleCard({ icon: Icon, iconClass, title, description, tag, onClick }: { icon: LucideIcon; iconClass: string; title: string; description: string; tag: string; onClick: () => void }) {
  return (
    <button className="module-card panel" onClick={onClick}>
      <div className={`module-icon ${iconClass}`}><Icon size={19} strokeWidth={1.8} /></div>
      <div className="module-card-meta"><span className="planned-tag">{tag}</span><ArrowUpRight size={15} /></div>
      <h3>{title}</h3><p>{description}</p>
      <div className="module-bottom"><span>Preview module</span><ChevronRight size={15} /></div>
    </button>
  );
}

function ConnectionRow({ icon: Icon, title, status, tone }: { icon: LucideIcon; title: string; status: string; tone: "quiet" | "good" }) {
  return <div className="connection-row"><div className="connection-icon"><Icon size={15} /></div><div className="connection-copy"><strong>{title}</strong><small>{status}</small></div><span className={`connection-indicator ${tone}`}><i /></span></div>;
}

function AssistantPreview({ messages, draft, setDraft, onSubmit, onNotice }: { messages: Message[]; draft: string; setDraft: (value: string) => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void; onNotice: (text: string) => void }) {
  return (
    <div className="content-wrap subpage-wrap">
      <div className="page-heading-row"><div><div className="eyebrow"><span className="eyebrow-mark" />ASSISTANT</div><h1>A familiar core.<br /><span>A different workspace.</span></h1><p>This screen demonstrates the future control surface. It is not linked to live voice, Gemini, your microphone, or the Python engine.</p></div><div className="read-only-chip"><ShieldCheck size={15} /> AGENT UNTOUCHED</div></div>
      <div className="assistant-demo-layout">
        <section className="panel conversation-panel">
          <div className="conversation-header"><div className="conversation-avatar"><Sparkles size={17} /></div><div><strong>JARVIS</strong><small>UI preview · no live session</small></div><span className="badge badge-neutral"><span className="status-dot muted" />Offline</span></div>
          <div className="conversation-body">
            <div className="date-divider"><span />TODAY · PREVIEW SESSION<span /></div>
            {messages.map((message, index) => message.role === "user" ? (
              <div className="demo-message user-message" key={`${index}-${message.text}`}><div className="message-label">YOU <small>just now</small></div><div className="message-bubble">{message.text}</div></div>
            ) : (
              <div className="demo-message system-message" key={`${index}-${message.text}`}><div className="message-avatar"><ShieldCheck size={14} /></div><div><div className="message-label">PREVIEW NOTICE</div><div className="notice-bubble">{message.text}</div></div></div>
            ))}
            <div className="sample-response"><div className="message-avatar jarvis-avatar"><Sparkles size={14} /></div><div><div className="message-label">JARVIS <small>SAMPLE ONLY</small></div><div className="message-bubble agent-bubble">The new workspace can provide a clear place for conversations and tasks. This sample response is static and was not generated by the agent.</div></div></div>
          </div>
          <form className="composer demo-composer" onSubmit={onSubmit}>
            <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Try the layout — this will not reach JARVIS" aria-label="Type a local preview message" />
            <button type="button" className="composer-icon" title="Microphone is not connected" onClick={() => onNotice("Microphone access is not enabled in this UI-only preview.")}><Mic size={17} /></button>
            <button type="submit" className="send-button" disabled={!draft.trim()}><ArrowRight size={16} /><span>Preview</span></button>
          </form>
          <div className="composer-caption"><ShieldCheck size={12} /> Local UI demo only · no message leaves this page</div>
        </section>
        <aside className="assistant-side-column">
          <div className="panel agent-status-card"><div className="eyebrow">SESSION STATUS</div><div className="status-big"><span className="status-dot muted" />Not connected</div><p>Live audio and commands stay with the existing desktop app until a separate bridge is designed.</p><div className="status-separator" /><div className="status-readonly"><ShieldCheck size={14} /><span>Voice agent source is unchanged</span><Check size={14} /></div></div>
          <div className="panel controls-preview-card"><div className="eyebrow">CONTROL SURFACE</div><h3>Built for a desktop rhythm.</h3><p>Controls can be brought across later without changing the assistant’s voice or session behaviour.</p><div className="mini-controls"><button disabled><Mic size={15} />Mute</button><button disabled><Zap size={15} />Wake</button><button disabled><AudioLines size={15} />Audio</button></div><span className="disabled-caption">Controls are visual only</span></div>
        </aside>
      </div>
    </div>
  );
}

function ConnectionsPage({ onNotice }: { onNotice: (text: string) => void }) {
  const rows = [
    { icon: AudioLines, title: "JARVIS voice engine", detail: "Existing Python voice agent", status: "Intentionally separate" },
    { icon: Plug, title: "Local assistant bridge", detail: "Not part of this UI preview", status: "Not connected" },
    { icon: Mail, title: "Email account", detail: "Gmail / Outlook connection can be considered later", status: "Not configured" },
    { icon: Images, title: "Asset sources", detail: "Stock, design, and media providers can be reviewed later", status: "Not configured" },
  ];
  return (
    <div className="content-wrap subpage-wrap">
      <div className="page-heading-row"><div><div className="eyebrow"><span className="eyebrow-mark" />MANAGE</div><h1>Nothing connected.<br /><span>That’s intentional.</span></h1><p>This conversion preview doesn’t start services or change how the current assistant runs.</p></div><div className="read-only-chip"><ShieldCheck size={15} /> SAFE PREVIEW</div></div>
      <div className="panel connections-list">
        <div className="connections-list-header"><div><div className="eyebrow">AVAILABLE LATER</div><h2>Workspace connections</h2></div><span className="badge badge-neutral">0 ACTIVE</span></div>
        {rows.map(({ icon: Icon, title, detail, status }) => <div className="connection-detail-row" key={title}><div className="connection-icon large"><Icon size={17} /></div><div className="connection-detail-copy"><strong>{title}</strong><small>{detail}</small></div><span className="connection-state">{status}</span><button className="outline-button tiny" onClick={() => onNotice("Connections are not enabled in this visual preview.")}>Details</button></div>)}
      </div>
      <div className="note-card"><ShieldCheck size={17} /><div><strong>Agent isolation is deliberate</strong><p>Voice, wake-word, prompts, Gemini sessions, and computer actions are left as-is. This prototype only changes the interface layer.</p></div></div>
    </div>
  );
}

function SettingsPage({ calmTheme, setCalmTheme, onNotice }: { calmTheme: boolean; setCalmTheme: (value: (previous: boolean) => boolean) => void; onNotice: (text: string) => void }) {
  return (
    <div className="content-wrap subpage-wrap settings-page">
      <div className="page-heading-row"><div><div className="eyebrow"><span className="eyebrow-mark" />PREFERENCES</div><h1>Your space,<br /><span>your rules.</span></h1><p>Appearance controls work locally in this preview. Assistant settings have not been moved or changed.</p></div><div className="read-only-chip"><Settings2 size={15} /> PREVIEW SETTINGS</div></div>
      <section className="panel settings-card"><div className="settings-section-title"><div><div className="eyebrow">APPEARANCE</div><h2>Set the mood</h2></div><span className="badge badge-good"><Check size={12} />Saved locally</span></div><div className="theme-options"><button className={`theme-choice dark-choice${!calmTheme ? " selected" : ""}`} onClick={() => setCalmTheme(() => false)}><span className="theme-swatch"><i /><i /><i /></span><span><strong>Midnight</strong><small>Deep, focused workspace</small></span>{!calmTheme && <span className="selected-check"><Check size={13} /></span>}</button><button className={`theme-choice light-choice${calmTheme ? " selected" : ""}`} onClick={() => setCalmTheme(() => true)}><span className="theme-swatch"><i /><i /><i /></span><span><strong>Soft light</strong><small>Calm, daylight palette</small></span>{calmTheme && <span className="selected-check"><Check size={13} /></span>}</button></div></section>
      <section className="panel settings-card read-only-settings"><div className="settings-section-title"><div><div className="eyebrow">ASSISTANT CORE</div><h2>Kept separate on purpose</h2></div><span className="badge badge-neutral"><ShieldCheck size={12} />Read-only</span></div><div className="readonly-row"><div><strong>Voice engine & session logic</strong><small>Still handled by the current JARVIS desktop app.</small></div><span>UNCHANGED</span></div><div className="readonly-row"><div><strong>Voice, prompts, and wake-word behaviour</strong><small>This Tauri preview does not edit or invoke them.</small></div><span>UNCHANGED</span></div><button className="subtle-button settings-help" onClick={() => onNotice("Settings migration is deferred; current settings remain in the existing app.")}>Why is this read-only? <ArrowUpRight size={14} /></button></section>
    </div>
  );
}

function PlannedPage({ kind, onNotice }: { kind: "studio" | "email" | "assets"; onNotice: (text: string) => void }) {
  const config = {
    studio: { icon: Megaphone, overline: "FUTURE WORKSPACE", title: "Marketing studio", copy: "A dedicated home for campaign briefs, content planning, creative direction, and launch-ready material.", items: ["Campaign workspace", "Brand voice & briefs", "Content calendar"] },
    email: { icon: Mail, overline: "FUTURE WORKSPACE", title: "Email workspace", copy: "A focused place for drafting, organizing, and later connecting your email accounts when you choose.", items: ["Drafts & templates", "Inbox workflows", "Account connections"] },
    assets: { icon: FileImage, overline: "FUTURE WORKSPACE", title: "Asset library", copy: "A searchable home for design references and sourced media, with clear origin and usage notes.", items: ["Images & graphics", "Video, audio & files", "Source and license notes"] },
  }[kind];
  const Icon = config.icon;
  return (
    <div className="content-wrap subpage-wrap planned-page">
      <div className="page-heading-row"><div><div className="eyebrow"><span className="eyebrow-mark" />{config.overline}</div><h1>{config.title}<br /><span>when you’re ready.</span></h1><p>{config.copy}</p></div><div className="read-only-chip planned-chip"><Clock3 size={15} /> NOT BUILT YET</div></div>
      <div className="panel planned-preview">
        <div className="planned-art"><div className="planned-art-glow" /><div className="planned-art-icon"><Icon size={31} strokeWidth={1.5} /></div><div className="planned-orbit orbit-a" /><div className="planned-orbit orbit-b" /><Sparkles className="planned-sparkle" size={18} /></div>
        <div className="planned-info"><div className="eyebrow">A PLACEHOLDER, NOT A FEATURE</div><h2>A clear path from idea<br />to finished work.</h2><p>This is only a preview of where this workspace could live. There are no accounts, integrations, downloads, or generated materials connected.</p><div className="planned-pill-row">{config.items.map((item) => <span key={item}><Check size={12} />{item}</span>)}</div><button className="outline-button" onClick={() => onNotice("This workspace is only a visual placeholder; no feature has been built yet.")}>What this preview means <ArrowRight size={15} /></button></div>
      </div>
      <div className="preview-note"><ShieldCheck size={15} /><span>Preview only: no data is sent, fetched, or stored by this screen.</span></div>
    </div>
  );
}

export default App;
