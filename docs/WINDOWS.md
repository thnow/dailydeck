# Windows notes

Tested with a Stream Deck MK.2 on Windows 11, German keyboard layout.

| | |
|---|---|
| Focused app | `focus/windows.py` – exe name and title of the foreground window; Store apps are looked up behind `ApplicationFrameHost.exe` |
| Key presses | `keys/windows_sendinput.py` – `SendInput` with virtual key and scan codes, characters through the keyboard layout of the focused window (`VkKeyScanExW`) |
| App icons | `appicons.py` – exe path of a running process (or the *App Paths* registry), icon extracted to a PNG in `%LOCALAPPDATA%\dailydeck\icons` |
| Start at login | `autostart.py` – value `dailydeck` under `HKCU\…\CurrentVersion\Run` (the installer's option writes the same value) |
| Device access | `hidapi.dll` from the official [libusb/hidapi](https://github.com/libusb/hidapi) release, no driver needed |

## Build the installer

```powershell
winget install astral-sh.uv JRSoftware.InnoSetup
powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1
```

The result is `dist\Daily Deck\` and `dist\DailyDeck-<version>-windows-x64-setup.exe`. The script
builds in a fresh venv under `build\windows`, smoke-tests the programs (`--dry-run`, `--preview`)
and compiles [packaging/windows/dailydeck.iss](../packaging/windows/dailydeck.iss).

- Two programs share one folder: `Daily Deck.exe` (no console; tray app, `--gui` for the editor)
  and `dailydeck.exe` (console; `--print-focus`, `--dry-run`, `-v`).
- The installer needs no admin rights (per user, `%LOCALAPPDATA%\Programs\Daily Deck`) and offers
  an installation for all users. It closes a running Daily Deck before updating; uninstalling
  keeps the configuration in `%APPDATA%\dailydeck`.
- The app logs to `%LOCALAPPDATA%\Daily Deck\dailydeck.log`.
- **Signing:** with `SIGN_COMMAND` set (e.g. a `signtool sign … {file}` call), the script signs
  both programs before packing them and then the setup. Unsigned, SmartScreen shows "Windows
  protected your PC" on the first start of the setup (*More info → Run anyway*).

## Run from source

```powershell
winget install astral-sh.uv
uv venv --python 3.13 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
powershell -ExecutionPolicy Bypass -File scripts\fetch-hidapi.ps1
.venv\Scripts\pythonw.exe -m dailydeck --tray
```

## Implementation notes

- **Why not pynput.** It sends characters by virtual key only and drops the modifiers the layout
  needs: on a German layout `ctrl+/` arrived as Ctrl+7 instead of Ctrl+Shift+7.
- **AltGr is Ctrl+Alt** on Windows, so `ctrl+[` (AltGr+8 on German layouts) arrives as `[`. Apps
  that need it get a `keys_windows` variant.
- **Elevated windows** (run as administrator) do not accept input from a normal process (UIPI).
- **Bringing the editor to the front** from the tray needs `AttachThreadInput`, otherwise Windows
  only flashes the taskbar button (`gui.bring_to_front`).
- **Do not start the tray hidden** (`Start-Process -WindowStyle Hidden`): Windows applies that to
  the first window of the process, so the editor would open invisibly.
- **Store apps** have no icon in their exe; their logo would have to come from `AppxManifest.xml`.
