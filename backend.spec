# PyInstaller spec for the Phantom-AI backend (Edge TTS + local Vosk recognition).
import pathlib
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

project_root = pathlib.Path(".").resolve()
block_cipher = None
hiddenimports = ["phantom_voice", "actions.offline_speech", "actions.secure_network", "actions.internet_services", "actions.speech_text"]
datas = []
binaries = []

# Collect dependencies fully: the speech package and its websocket/TLS stack use
# submodules and certificate data that are easy for static analysis to miss.
for package in ["edge_tts", "websockets", "aiohttp", "certifi", "vosk", "sounddevice", "_sounddevice_data", "cffi"]:
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
        datas.extend(package_datas)
        binaries.extend(package_binaries)
        hiddenimports.extend(package_hidden)
    except Exception:
        try:
            datas.extend(collect_data_files(package))
            hiddenimports.extend(collect_submodules(package))
        except Exception:
            pass

for package in ["actions", "agent", "core", "memory", "models", "plugins"]:
    folder = project_root / package
    if folder.exists():
        datas.append((str(folder), package))

config_dir = project_root / "config"
if config_dir.exists():
    datas.append((str(config_dir), "config"))

for filename in ["ui.py", "main.py"]:
    file_path = project_root / filename
    if file_path.exists():
        datas.append((str(file_path), "."))

a = Analysis(
    ["bridge_backend.py"], pathex=[str(project_root)], binaries=binaries, datas=datas,
    hiddenimports=list(dict.fromkeys(hiddenimports)), hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=[], win_no_prefer_redirects=False,
    win_private_assemblies=False, cipher=block_cipher, noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [], [], name="phantom-backend", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    exclude_binaries=True, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False,
    upx_exclude=[], name="bk",
)
