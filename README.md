# Auto-Cast

[中文](#中文) | [English](#english)

---

## 中文

Auto-Cast 是一个 Windows 投屏工具，支持扫描局域网内的 DLNA / AirPlay / Chromecast 设备，并把本地媒体、B 站等直播链接、窗口画面或屏幕画面推送到电视播放。

### 当前状态

- 本地文件、直播链接、窗口投屏、屏幕投屏、停止播放、自动续播已可用。
- 音量控制仍取决于电视是否支持 DLNA `RenderingControl` 音量命令；如果电视不响应，应用会尽量探测真实控制地址，但不保证所有电视可控。
- 直播 / 窗口 / 屏幕投屏需要本机可用 `ffmpeg`。

### 主要功能

- **设备扫描**：通过 SSDP 扫描 DLNA 渲染器，通过 mDNS 扫描 AirPlay / Chromecast 服务。
- **GUI 投屏**：现代深色 PySide6 图形界面，支持设备列表、文件选择、直播 URL、窗口选择和屏幕选择。
- **本地媒体投屏**：内置 HTTP 媒体服务器，让 DLNA 电视直接拉取本地视频、音频和图片。
- **直播链接投屏**：使用 `yt-dlp` 解析直播真实流地址，并通过 FFmpeg 转码为电视更容易播放的 MPEG-TS。
- **窗口 / 屏幕投屏**：采集窗口或显示器画面，经 FFmpeg 转码后推送到 DLNA 电视。
- **自动续播**：记住上次成功连接的设备和播放来源，重新扫描到同一设备时自动续播。
- **停止播放**：停止电视端播放并关闭本地转码 / HTTP 服务。
- **码率设置**：码率滑块控制下一次直播 / 窗口 / 屏幕投屏的 FFmpeg 输出码率。

### 下载和运行

如果你只想使用 GUI：

1. 下载 release 中的 `auto-cast-gui.exe`。
2. 确认系统已安装 FFmpeg，并且 `ffmpeg.exe` 在 `PATH` 中。
3. 双击运行 `auto-cast-gui.exe`。
4. 点击 **Scan Devices** 扫描电视。
5. 选择设备后播放文件、直播 URL、窗口或屏幕。

> 如果直播、窗口或屏幕投屏没有画面，优先检查 FFmpeg 是否可用：`ffmpeg -version`。

### 从源码运行

```bash
pip install -r requirements.txt
python gui.py
```

CLI 也可用：

```bash
# 扫描设备
python main.py scan

# 自动投屏本地文件
python main.py play video.mp4

# 指定设备
python main.py play video.mp4 --to "客厅电视"

# 只扫描 DLNA
python main.py scan --type dlna

# 停止播放
python main.py stop "客厅电视"

# 查看支持格式
python main.py formats
```

### 支持格式

| 类型 | 格式 |
| --- | --- |
| 视频 | mp4, mkv, avi, mov, webm |
| 音频 | mp3, wav, flac, aac, ogg |
| 图片 | jpg, jpeg, png, gif, bmp |
| 直播 | B 站等 `yt-dlp` 可解析的直播链接，或直接媒体流 URL |

### FFmpeg 和码率

直播、窗口和屏幕投屏会走 FFmpeg：

- 视频编码：H.264 (`libx264`)
- 音频编码：AAC
- 容器：MPEG-TS (`video/mp2t`)
- 低延迟参数：固定 GOP、`zerolatency`、`maxrate`、`bufsize`

GUI 中的码率滑块会影响下一次开始的直播 / 窗口 / 屏幕投屏。运行中调整码率不会重启当前 FFmpeg 流。

### 自动续播说明

启用 **Resume** 后，应用会保存少量状态到：

```text
%USERPROFILE%\.auto-cast\state.json
```

保存内容包括设备名称、设备类型、设备 IP、设备 UID、本地文件路径或去除查询参数后的直播 URL。为了避免误投，自动匹配不会只依赖 IP；没有 UID 时必须设备名、类型和 IP 都一致。

### 已知限制

- 电视音量控制依赖 DLNA `RenderingControl`，不同品牌电视支持情况不一致。
- 窗口采集基于桌面像素采集，受保护视频、硬件加速窗口或最小化窗口可能黑屏。
- Chromecast 发现存在，但当前主要播放路径集中在 DLNA / AirPlay。
- 直播平台 URL 解析能力取决于 `yt-dlp`。

### 开发和测试

```bash
pip install -r requirements.txt
python -m pytest test_auto_cast.py
```

打包 GUI：

```bash
pyinstaller auto-cast-gui.spec --distpath dist --workpath build-package --noconfirm
```

构建完成后发布文件位于：

```text
dist/auto-cast-gui.exe
```

---

## English

Auto-Cast is a Windows casting tool that discovers DLNA / AirPlay / Chromecast devices on your local network and casts local media files, live URLs, windows, or screens to a TV.

### Current status

- Local files, live URLs, window casting, screen casting, stop playback, and auto resume are working.
- Volume control depends on whether the TV supports DLNA `RenderingControl` volume commands. The app tries to discover the real control URL, but not every TV accepts remote volume control.
- Live URL, window, and screen casting require a working `ffmpeg` executable in `PATH`.

### Features

- **Device discovery**: SSDP for DLNA renderers and mDNS for AirPlay / Chromecast services.
- **GUI casting**: Modern dark PySide6 interface with device list, file picker, live URL input, window selection, and screen selection.
- **Local media casting**: Built-in HTTP server so DLNA TVs can pull local videos, audio files, and images.
- **Live URL casting**: Resolves live stream URLs with `yt-dlp` and transcodes them with FFmpeg to MPEG-TS for better TV compatibility.
- **Window / screen casting**: Captures a selected window or monitor, transcodes it with FFmpeg, and pushes it to a DLNA TV.
- **Auto resume**: Remembers the last successful device and playback source, then resumes when the same device is discovered again.
- **Stop playback**: Stops TV playback and shuts down local transcoding / HTTP services.
- **Bitrate setting**: The bitrate slider controls the next FFmpeg output bitrate for live / window / screen casting.

### Download and run

For GUI usage:

1. Download `auto-cast-gui.exe` from the release.
2. Make sure FFmpeg is installed and `ffmpeg.exe` is available in `PATH`.
3. Run `auto-cast-gui.exe`.
4. Click **Scan Devices**.
5. Select a target device and cast a file, live URL, window, or screen.

> If live, window, or screen casting has no picture, check FFmpeg first with `ffmpeg -version`.

### Run from source

```bash
pip install -r requirements.txt
python gui.py
```

CLI usage:

```bash
# Scan devices
python main.py scan

# Cast a local file
python main.py play video.mp4

# Select a target device
python main.py play video.mp4 --to "Living Room TV"

# Scan DLNA only
python main.py scan --type dlna

# Stop playback
python main.py stop "Living Room TV"

# Show supported formats
python main.py formats
```

### Supported formats

| Type | Formats |
| --- | --- |
| Video | mp4, mkv, avi, mov, webm |
| Audio | mp3, wav, flac, aac, ogg |
| Image | jpg, jpeg, png, gif, bmp |
| Live | Live URLs supported by `yt-dlp`, or direct media stream URLs |

### FFmpeg and bitrate

Live, window, and screen casting use FFmpeg:

- Video codec: H.264 (`libx264`)
- Audio codec: AAC
- Container: MPEG-TS (`video/mp2t`)
- Low-latency settings: fixed GOP, `zerolatency`, `maxrate`, and `bufsize`

The GUI bitrate slider applies to the next live / window / screen cast. Changing it while a stream is already running does not restart the current FFmpeg process.

### Auto resume

When **Resume** is enabled, Auto-Cast stores small state at:

```text
%USERPROFILE%\.auto-cast\state.json
```

The state includes device name, type, IP, UID, local media path, or a redacted live URL without query parameters. To avoid casting to the wrong TV, auto matching never uses IP alone; without a UID, device name, type, and IP must all match.

### Known limitations

- TV volume control depends on DLNA `RenderingControl`; support varies by vendor.
- Window capture uses desktop pixels. Protected video, hardware-accelerated windows, or minimized windows may produce a black image.
- Chromecast discovery exists, but the main playback paths are currently DLNA / AirPlay.
- Live platform support depends on `yt-dlp`.

### Development and tests

```bash
pip install -r requirements.txt
python -m pytest test_auto_cast.py
```

Build the GUI executable:

```bash
pyinstaller auto-cast-gui.spec --distpath dist --workpath build-package --noconfirm
```

The GUI executable is generated at:

```text
dist/auto-cast-gui.exe
```

## License

MIT
