"""Auto-Cast: Automatic DLNA/AirPlay device scanner and caster."""

import asyncio
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from device import Device, DeviceType
from scanner import scan_all, scan_by_type
from media_server import MediaServer
from config import Config, SUPPORTED_EXTENSIONS, MIME_TYPES
import dlna_controller
import airplay_controller

console = Console()
__version__ = "1.0.0"


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def _scan(timeout: float, device_type: str | None) -> list[Device]:
    """Run device scan with progress indicator."""
    type_map = {
        "dlna": DeviceType.DLNA,
        "airplay": DeviceType.AIRPLAY,
        "chromecast": DeviceType.CHROMECAST,
    }

    with console.status("[bold green]Scanning for devices..."):
        if device_type and device_type in type_map:
            return await scan_by_type(type_map[device_type], timeout)
        return await scan_all(timeout)


def _display_devices(devices: list[Device]):
    """Display found devices in a rich table."""
    if not devices:
        console.print("[yellow]No devices found.[/yellow]")
        return

    table = Table(title="Discovered Devices", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="bold cyan")
    table.add_column("Type", style="green")
    table.add_column("IP", style="white")
    table.add_column("Port", style="white")
    table.add_column("Manufacturer", style="dim")
    table.add_column("Model", style="dim")

    for i, device in enumerate(devices, 1):
        table.add_row(
            str(i),
            device.name,
            device.display_type,
            device.ip,
            str(device.port),
            device.manufacturer,
            device.model,
        )

    console.print(table)


def _select_device(devices: list[Device], name: str | None) -> Device | None:
    """Select a device by name or return the first one."""
    if not devices:
        return None

    if name:
        name_lower = name.lower()
        for d in devices:
            if name_lower in d.name.lower():
                return d
        console.print(f"[yellow]Device '{name}' not found. Using first device.[/yellow]")

    return devices[0]


def _validate_media(filepath: str) -> tuple[str, str]:
    """Validate media file and return (absolute_path, content_type)."""
    path = Path(filepath).resolve()
    if not path.exists():
        raise click.BadParameter(f"File not found: {filepath}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise click.BadParameter(
            f"Unsupported format: {ext}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    content_type = MIME_TYPES.get(ext, "application/octet-stream")
    return str(path), content_type


async def _play_on_dlna(device: Device, media_path: str, content_type: str):
    """Play media on a DLNA device with local HTTP server."""
    server = MediaServer()
    try:
        local_ip, port = await server.start()
        server.register_file(media_path)
        media_url = server.get_url(media_path)

        console.print(f"[dim]Media server: {media_url}[/dim]")
        await dlna_controller.play(device, media_url, content_type)

        console.print(f"\n[bold green]Now playing on {device.name}[/bold green]")
        console.print("[dim]Press Ctrl+C to stop[/dim]\n")

        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping playback...[/yellow]")
        await dlna_controller.stop(device)
    finally:
        await server.stop()


async def _play_on_airplay(device: Device, media_path: str):
    """Play media on an AirPlay device."""
    console.print(f"[dim]Streaming to {device.name}...[/dim]")
    await airplay_controller.play(device, media_path)

    console.print(f"\n[bold green]Now playing on {device.name}[/bold green]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping playback...[/yellow]")
        await airplay_controller.stop(device)


async def _auto_play(
    devices: list[Device],
    media_path: str,
    content_type: str,
    target_name: str | None,
):
    """Auto-select device and play."""
    device = _select_device(devices, target_name)
    if not device:
        console.print("[red]No devices available for playback.[/red]")
        return

    console.print(f"\n[bold]Selected device:[/bold] {device}")

    if device.device_type == DeviceType.DLNA:
        await _play_on_dlna(device, media_path, content_type)
    elif device.device_type == DeviceType.AIRPLAY:
        await _play_on_airplay(device, media_path)
    elif device.device_type == DeviceType.CHROMECAST:
        console.print("[yellow]Chromecast playback not yet implemented.[/yellow]")
    else:
        console.print(f"[red]Unsupported device type: {device.device_type}[/red]")


@click.group()
@click.version_option(__version__, prog_name="auto-cast")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
def cli(verbose: bool):
    """Auto-Cast: Scan and cast to DLNA/AirPlay devices."""
    setup_logging(verbose)


@cli.command()
@click.option("--timeout", "-t", default=5.0, help="Scan timeout in seconds.")
@click.option("--type", "-T", "device_type", type=click.Choice(["dlna", "airplay", "chromecast"]), help="Filter by device type.")
def scan(timeout: float, device_type: str | None):
    """Scan for available devices."""
    console.print(Panel("[bold]Auto-Cast Device Scanner[/bold]", style="blue"))
    devices = asyncio.run(_scan(timeout, device_type))
    _display_devices(devices)
    console.print(f"\n[dim]Found {len(devices)} device(s)[/dim]")


@cli.command()
@click.argument("media_file", type=click.Path(exists=True))
@click.option("--to", "-t", "target", help="Target device name (partial match).")
@click.option("--type", "-T", "device_type", type=click.Choice(["dlna", "airplay", "chromecast"]), help="Filter by device type.")
@click.option("--timeout", default=5.0, help="Scan timeout in seconds.")
def play(media_file: str, target: str | None, device_type: str | None, timeout: float):
    """Scan for devices and play a media file."""
    console.print(Panel("[bold]Auto-Cast Player[/bold]", style="blue"))

    media_path, content_type = _validate_media(media_file)
    console.print(f"[bold]Media:[/bold] {media_path}")
    console.print(f"[bold]Type:[/bold]  {content_type}\n")

    devices = asyncio.run(_scan(timeout, device_type))
    _display_devices(devices)

    if not devices:
        console.print("[red]No devices found. Cannot play.[/red]")
        sys.exit(1)

    asyncio.run(_auto_play(devices, media_path, content_type, target))


@cli.command()
@click.argument("device_name")
def stop(device_name: str):
    """Stop playback on a device."""
    console.print(f"[bold]Stopping {device_name}...[/bold]")
    devices = asyncio.run(_scan(5.0, None))
    device = _select_device(devices, device_name)
    if not device:
        console.print(f"[red]Device '{device_name}' not found.[/red]")
        sys.exit(1)

    if device.device_type == DeviceType.DLNA:
        asyncio.run(dlna_controller.stop(device))
    elif device.device_type == DeviceType.AIRPLAY:
        asyncio.run(airplay_controller.stop(device))

    console.print(f"[green]Stopped on {device.name}[/green]")


@cli.command(name="formats")
def list_formats():
    """List supported media formats."""
    table = Table(title="Supported Formats", show_lines=True)
    table.add_column("Extension", style="cyan")
    table.add_column("MIME Type", style="green")
    table.add_column("Category", style="dim")

    for ext in sorted(SUPPORTED_EXTENSIONS):
        mime = MIME_TYPES.get(ext, "unknown")
        if "video" in mime:
            cat = "Video"
        elif "audio" in mime:
            cat = "Audio"
        elif "image" in mime:
            cat = "Image"
        else:
            cat = "Other"
        table.add_row(ext, mime, cat)

    console.print(table)


if __name__ == "__main__":
    cli()
