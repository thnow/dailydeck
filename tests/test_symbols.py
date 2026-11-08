import zipfile

from PIL import Image

from dailydeck import symbols
from dailydeck.config import resolve_icon
from dailydeck.profile_io import export_profile, import_profile
from dailydeck.render import render_key


def test_every_symbol_is_bundled():
    names = symbols.all_names()
    assert len(names) == len(set(names))
    missing = [n for n in names if not symbols.symbol_path(n).is_file()]
    assert not missing
    assert (symbols.SYMBOLS_DIR / "LICENSE").is_file()


def test_resolve_symbol(tmp_path):
    assert resolve_icon(tmp_path, "symbol:play") == symbols.SYMBOLS_DIR / "play.png"
    assert resolve_icon(tmp_path, "symbol:../../evil") == symbols.SYMBOLS_DIR / "evil.png"
    assert resolve_icon(tmp_path, "icons/x.png") == tmp_path / "icons" / "x.png"
    assert resolve_icon(tmp_path, None) is None


def test_symbol_is_drawn_in_text_color():
    image = render_key((72, 72), icon=symbols.symbol_path("square"), background="#000000", text_color="#ff0000")
    colors = {c for _n, c in image.getcolors(72 * 72)}
    assert any(r > 200 and g < 60 and b < 60 for r, g, b in colors)
    assert not any(r > 200 and g > 200 and b > 200 for r, g, b in colors)  # no white left


def test_export_import_keeps_symbols(tmp_path):
    src_dir, dst_dir = tmp_path / "src", tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    profile = {"name": "Player", "match": ["player"], "icon": "symbol:music",
               "buttons": [{"label": "Play", "keys": "playpause", "icon": "symbol:play"}]}
    target = tmp_path / "player.dailydeck"
    export_profile(profile, src_dir, target)
    with zipfile.ZipFile(target) as zf:
        assert not [n for n in zf.namelist() if n.startswith("icons/")]
    imported = import_profile(target, dst_dir)
    assert imported["icon"] == "symbol:music"
    assert imported["buttons"][0]["icon"] == "symbol:play"


def test_symbols_are_white_on_transparent():
    with Image.open(symbols.symbol_path("play")) as img:
        img = img.convert("RGBA")
        assert img.getchannel("A").getextrema()[0] == 0
        opaque = img.getchannel("A").point(lambda a: 255 if a == 255 else 0)
        assert opaque.getbbox()
        white = Image.new("L", img.size, 255)
        for band in "RGB":  # every fully opaque pixel is white
            assert Image.composite(img.getchannel(band), white, opaque).getextrema()[0] == 255
