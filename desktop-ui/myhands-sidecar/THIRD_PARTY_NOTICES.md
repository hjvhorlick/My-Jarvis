# My Hands sidecar notices

## My Hands source and provenance

The My Hands tracker and gesture-engine modules in this sidecar are adapted from the
user's `hjvhorlick/The-better-Jarvis` repository at commit
`316e60dac0982eee935be57adcf8fd26a3573de0`. The repository's `UPSTREAM-LICENSE.txt`
and `docs/MYHANDS_CLEAN_ROOM.md` are retained with the source. The upstream licence file
is CC BY-NC 4.0. The owner states that My Hands was recreated independently from the
original Barehands implementation and that the code and its licence are theirs; this
assertion is recorded as supplied and has not been independently verified here. Preserve
both upstream provenance records when redistributing. The original `barehands/`
application, its AGPL-3.0 code, and its assets are not included in this sidecar.

## Runtime dependencies

- MediaPipe 0.10.14 — Apache-2.0; local hand-landmark inference.
- OpenCV headless 4.10.0.84 — Apache-2.0; decode incoming in-memory JPEG frames.
- FastAPI — MIT; local sidecar API.
- Uvicorn — BSD-3-Clause; local API/WebSocket server.
- Pydantic — MIT; FastAPI dependency.

Full dependency license texts are included in their installed packages. The My Hands
requirements remain pinned in `requirements-myhands.txt` and `requirements.txt`; retain
this notice and the upstream provenance/licence files when redistributing the sidecar.
