# Auto-Cast

自动扫描局域网内的 DLNA / AirPlay / Chromecast 设备，发现后自动连接并播放媒体文件。

## 功能

- **设备发现**：SSDP 扫描 DLNA 渲染器，mDNS 扫描 AirPlay 和 Chromecast
- **自动播放**：发现设备后自动连接并推送媒体
- **多协议支持**：DLNA（SOAP 控制）、AirPlay（pyatv）
- **内置媒体服务器**：为 DLNA 渲染器提供 HTTP 拉流服务
- **CLI 交互**：Rich 美化输出，支持按名称/类型筛选设备

## 安装

```bash
pip install -r requirements.txt
```

## 使用

```bash
# 扫描设备
python main.py scan

# 自动投屏
python main.py play video.mp4

# 指定设备
python main.py play video.mp4 --to "客厅电视"

# 只扫 DLNA
python main.py scan --type dlna

# 停止播放
python main.py stop "客厅电视"

# 查看支持格式
python main.py formats
```

## 支持格式

| 类型 | 格式 |
|------|------|
| 视频 | mp4, mkv, avi, mov, webm |
| 音频 | mp3, wav, flac, aac, ogg |
| 图片 | jpg, jpeg, png, gif, bmp |

## 架构

```
main.py (CLI)
  ├── scanner.py          # SSDP + mDNS 设备发现
  ├── dlna_controller.py  # DLNA SOAP 播放控制
  ├── airplay_controller.py # AirPlay 播放控制
  ├── media_server.py     # HTTP 媒体服务器
  ├── device.py           # 统一设备抽象
  └── config.py           # 配置管理
```

## 测试

```bash
pip install pytest pytest-asyncio
python -m pytest test_auto_cast.py -v
```

## 依赖

- `async-upnp-client` — DLNA/UPnP 发现与控制
- `pyatv` — AirPlay 控制
- `zeroconf` — mDNS 服务发现
- `aiohttp` — HTTP 媒体服务器
- `rich` + `click` — CLI 界面

## License

MIT
