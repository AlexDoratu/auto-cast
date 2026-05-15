# Auto-Cast

Auto-Cast is a Windows desktop casting tool. The current app is a Flutter GUI backed by the existing Python casting engine.

It discovers DLNA / AirPlay / Chromecast devices on the local network and casts local media files, live URLs, selected windows, or screens to a TV.

## Architecture

- `flutter_gui/`: Flutter desktop UI.
- `gui_bridge.py`: persistent line-delimited JSON bridge used by Flutter.
- `scanner.py`: DLNA SSDP and AirPlay / Chromecast mDNS discovery.
- `dlna_controller.py`: DLNA SOAP playback, stop, volume, seek, and status control.
- `airplay_controller.py`: AirPlay playback and control through `pyatv`.
- `media_server.py`: local aiohttp server for media files and live/capture streams.
- `ffmpeg_transcoder.py`: FFmpeg MPEG-TS transcoding for live, window, and screen casting.
- `capture.py`: Windows window/screen capture.
- `main.py`: legacy CLI for direct backend operations.

## Requirements

- Windows
- Python 3.11+
- Flutter SDK with Windows desktop support
- FFmpeg available in `PATH`

For the GitHub Windows release zip, Python dependencies are bundled in `gui_bridge.exe`. FFmpeg is still required in `PATH` for live URL, window, and screen streaming.

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

## Run The Flutter GUI

```powershell
cd flutter_gui
flutter pub get
flutter run -d windows
```

The Flutter app starts `gui_bridge.py` automatically and communicates with it over stdin/stdout JSON.

## Run The Windows Release

Download and extract `Auto-Cast-v1.4.0-windows.zip`, then run:

```text
auto_cast_flutter.exe
```

Keep `auto_cast_flutter.exe`, `gui_bridge.exe`, `flutter_windows.dll`, and the `data/` folder in the same directory.

## Backend Bridge

You can test the bridge directly:

```powershell
python gui_bridge.py --stdio
```

Send one JSON command per line:

```json
{"id":1,"command":"state"}
{"id":2,"command":"scan","timeout":5}
```

Supported bridge commands:

- `state`
- `scan`
- `windows`
- `monitors`
- `play_media`
- `inspect_video`
- `cache_video`
- `cancel_cache`
- `play_cached_video`
- `play_live`
- `cast_window`
- `cast_screen`
- `stop`
- `set_volume`
- `seek`
- `playback_status`
- `restart_stream`

## Video URL Casting

Regular video pages such as Bilibili are resolved through `yt-dlp`. The GUI can inspect a URL, cache it locally, then cast the cached file through DLNA so seeking works.

Cached files are stored under:

```text
%USERPROFILE%\.auto-cast\cache
```

## CLI

The CLI is still available for backend debugging:

```powershell
python main.py scan
python main.py play video.mp4
python main.py stop "Living Room TV"
python main.py formats
```

## Tests

```powershell
python -m pytest test_auto_cast.py
python -m py_compile gui_bridge.py
```

Flutter checks, after installing Flutter:

```powershell
cd flutter_gui
flutter analyze
flutter test
```

## Known Limits

- Chromecast discovery exists, but playback is still focused on DLNA / AirPlay-compatible paths.
- TV volume depends on DLNA `RenderingControl`; not every TV supports it.
- Window capture is desktop-pixel based. Protected video, hardware acceleration, or minimized windows can produce black frames.
- Live URL resolution depends on `yt-dlp` and the source platform.
- Bitrate changes for live/window/screen streams restart the stream and can cause a brief interruption.
- AirPlay playback does not expose the same detailed TV status as DLNA.

## License

MIT
