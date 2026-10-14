# My Hands local tracker sidecar

This isolated service reuses the My Hands tracker and gesture engine from the user's
`hjvhorlick/The-better-Jarvis` repository. It does not import or start the Jarvis voice
agent, alter its microphone/speaker path, or include the separate `barehands/` app.

The WebView remains the only camera owner. While My Hands is enabled, the UI sends small
JPEG frames over `/ws/myhands`; this service runs the existing MediaPipe tracker and
gesture engine, then returns the 21-point hand landmarks and gesture events. The browser
draws the wireframe on the matching mirrored camera view and displays the in-app pointer.
Frames are processed in memory and not persisted. When the UI and sidecar run locally,
processing stays on that computer. The hosted Arena preview forwards camera frames to its
sandbox sidecar; use a local run for on-device processing. No microphone is opened.

## Development

In a clean virtual environment, install the service and tracker dependencies. MediaPipe pulls in an OpenCV build that should be replaced by the headless build, following the verified recipe from the source repository:

```sh
python -m pip install -r requirements.txt
python -m pip install mediapipe==0.10.14
python -m pip uninstall -y opencv-contrib-python
python -m pip install --force-reinstall --no-deps opencv-python-headless==4.10.0.84
python -m uvicorn server:app --host 127.0.0.1 --port 8795
```

The Vite development server proxies the relative `/ws/myhands` and `/api/myhands/*`
paths to this service. Browser code does not connect to a hard-coded loopback URL.

## Source and provenance

The My Hands package was copied from `hjvhorlick/The-better-Jarvis` at commit
`316e60dac0982eee935be57adcf8fd26a3573de0` (2026-10-14). Its specification and
clean-room provenance record are in `docs/`. Those notes, the source repository's
license, and third-party notices should be retained with the app. The independent
My Hands modules are used here; the original AGPL-3.0 `barehands/` application and its
assets are not included.

The development API is deliberately a separate process. Native Tauri sidecar packaging
and its OS-specific permission configuration still need to be added and tested before
this tracker can run in a packaged desktop build.
