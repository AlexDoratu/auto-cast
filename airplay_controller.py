"""AirPlay device control via pyatv."""

import logging
from pathlib import Path

import pyatv
from pyatv.const import Protocol

from device import Device

logger = logging.getLogger(__name__)


def _make_config(device: Device) -> pyatv.conf.AppleTV:
    """Create pyatv config for an AirPlay device."""
    config = pyatv.conf.AppleTV(device.ip, device.name)
    config.add_service(
        pyatv.conf.ManualService(
            identifier=device.uid or device.ip,
            protocol=Protocol.AirPlay,
            port=device.port,
        )
    )
    return config


async def play(device: Device, media_path: str):
    """Play a media file on an AirPlay device."""
    config = _make_config(device)
    atv = None
    try:
        atv = await pyatv.connect(config)
        path = Path(media_path)
        if path.exists():
            await atv.stream.stream_file(str(path))
            logger.info(f"AirPlay: streaming {media_path} to {device.name}")
        else:
            await atv.stream.stream_url(media_path)
            logger.info(f"AirPlay: streaming URL {media_path} to {device.name}")
    except Exception as e:
        logger.error(f"AirPlay play failed on {device.name}: {e}")
        raise
    finally:
        if atv:
            atv.close()


async def stop(device: Device):
    """Stop playback on an AirPlay device."""
    config = _make_config(device)
    atv = None
    try:
        atv = await pyatv.connect(config)
        await atv.remote_control.stop()
        logger.info(f"AirPlay: stopped on {device.name}")
    except Exception as e:
        logger.error(f"AirPlay stop failed on {device.name}: {e}")
    finally:
        if atv:
            atv.close()


async def set_volume(device: Device, volume: int):
    """Set volume (0-100) on an AirPlay device."""
    config = _make_config(device)
    atv = None
    try:
        atv = await pyatv.connect(config)
        pyatv_volume = volume / 100.0
        await atv.remote_control.set_volume(pyatv_volume)
        logger.info(f"AirPlay: volume set to {volume} on {device.name}")
    except Exception as e:
        logger.error(f"AirPlay set_volume failed on {device.name}: {e}")
    finally:
        if atv:
            atv.close()
