import argparse
import logging
import time
from pathlib import Path

from . import __version__
from .config import ConfigError, default_config_path, load_config, setup_language
from .i18n import _


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="dailydeck",
        description="Daily Deck: the Stream Deck shows the keyboard shortcuts of the focused application.",
    )
    parser.add_argument("-c", "--config", type=Path, help="config file (default: ~/.config/dailydeck/config.toml)")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--print-focus", action="store_true",
                      help="print the focused window's ids and title whenever they change (to write profiles)")
    mode.add_argument("--dry-run", metavar="SHORTCUT",
                      help="show which physical keys a shortcut would press, without pressing them")
    mode.add_argument("--gui", action="store_true", help="open the profile editor")
    mode.add_argument("--tray", action="store_true", help="run with an icon in the top bar / notification area")
    mode.add_argument("--preview", metavar="DIR", type=Path,
                      help="render every profile as PNG into DIR instead of using the device")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("PIL").setLevel(logging.INFO)
    setup_language(args.config.expanduser() if args.config else None)
    config_path = (args.config or default_config_path()).expanduser().resolve()

    explicit = args.config.expanduser().resolve() if args.config else None  # else: follow local.toml
    if args.tray:
        from .tray import main as tray_main

        return tray_main(explicit)
    if args.gui:
        from .gui import main as gui_main

        return gui_main(explicit)
    if args.print_focus:
        return _print_focus()
    if args.dry_run:
        return _dry_run(config_path, args.dry_run)
    if args.preview:
        return _preview(config_path, args.preview)

    from .app import run

    return run(config_path, follow=explicit is None)


def _print_focus() -> int:
    from .focus import create_focus_provider

    provider = create_focus_provider()
    last = None
    print(_("Switch between windows; Ctrl+C quits."))
    try:
        while True:
            info = provider.get()
            if info != last and not info.empty:
                print(f"[{provider.name}] ids={list(info.ids)} title={info.title!r}")
                last = info
            time.sleep(0.3)
    except KeyboardInterrupt:
        return 0


def _dry_run(config_path: Path, shortcut: str) -> int:
    from .keys import ShortcutError, create_key_sender, format_shortcut, parse_shortcut

    try:
        chords = parse_shortcut(shortcut)
    except ShortcutError as e:
        print(_("Error: {error}").format(error=e))
        return 1
    try:
        s = load_config(config_path).settings
        layout, variant, backend = s.keyboard_layout, s.keyboard_variant, s.key_backend
    except ConfigError:
        layout, variant, backend = None, None, "auto"
    print(f"{format_shortcut(chords)}  ->  ", end="")
    sender = create_key_sender(backend, layout, variant)
    try:
        print(sender.describe(chords))
    finally:
        sender.close()
    return 0


def _preview(config_path: Path, out_dir: Path) -> int:
    from PIL import Image

    from .layout import match_ids, page_count, render_page

    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(_("Error: {error}").format(error=e))
        return 1
    s = config.settings
    cols, rows, size = 5, 3, 72
    gap = s.key_spacing
    out_dir.mkdir(parents=True, exist_ok=True)
    for profile in config.profiles:
        for page in range(page_count(len(profile.buttons), cols * rows)):
            sheet = Image.new("RGB", (cols * (size + gap) + gap, rows * (size + gap) + gap), "#101010")
            for i, img in enumerate(render_page(profile, s, match_ids(profile), page, cols, rows)):
                sheet.paste(img, (gap + (i % cols) * (size + gap), gap + (i // cols) * (size + gap)))
            suffix = f"-{page + 1}" if page else ""
            target = out_dir / f"{profile.name.replace('/', '_')}{suffix}.png"
            sheet.save(target)
            print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
