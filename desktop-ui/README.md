# Super AI Agent Tauri UI preview

A Tauri-compatible UI shell for **Super AI Agent**, with JARVIS as its current voice/personality character. The Python voice agent remains disconnected and unchanged: the UI does not start it, access its microphone, send commands to it, or alter its voice/session behavior.

## My Hands

The optional My Hands tracker is a separate service. The WebView is the sole webcam owner; only when My Hands is enabled does it send small, downscaled video frames to the sidecar. The tracker returns the existing gesture events and 21-point landmarks, which are rendered as a wireframe directly over the matching camera view. No microphone is opened; frames are processed in memory and not persisted. **The hosted Arena preview sends camera frames to its sandbox sidecar.** To keep processing on your computer, run both the UI and sidecar locally. The source and tests are in `myhands-sidecar/`; the original `barehands/` application is not included.

Install the sidecar dependencies in a Python 3.11 environment, following the OpenCV replacement steps in `myhands-sidecar/README.md`. Then use two terminals:

```bash
# Terminal 1, from desktop-ui/
npm run myhands:dev

# Terminal 2, from desktop-ui/
npm run dev
```

The Vite server proxies the relative My Hands API/WebSocket paths to the local service. In the desktop UI, open **My Hands** and explicitly enable the camera. The camera closes when you turn it off or leave the page. Set `PYTHON` to a specific Python interpreter if it is not found on PATH.

## Run the browser preview

```bash
npm install
npm run dev
```

Open the Vite address shown in the terminal (normally port 1420). The assistant and future workspace screens remain preview/placeholders.

## Run as a Tauri desktop window

Install the Rust toolchain and native Tauri prerequisites, then run `npm run desktop:dev` (start the My Hands service in a separate terminal first if you want tracking). Native compilation cannot be verified in environments without Rust/Cargo.

**Not yet done:** native sidecar packaging and the production Tauri IPC/permission configuration. The current tracker connection is for the Vite development preview; it is not yet a transferable production installer.
