"""Local Chromium selection/launch validation. Never installs or reads old runs."""
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys


class BrowserSelectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserSelection:
    executable: str
    source: str


def select_browser(explicit=None, *, bundled_path=None, environ=None, platform=None, which=None):
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    which = shutil.which if which is None else which
    def usable(candidate):
        try:
            p = Path(candidate).expanduser().resolve()
            return p if p.is_file() and (platform == 'win32' or os.access(p, os.X_OK)) else None
        except (OSError, ValueError, TypeError):
            return None
    if explicit is not None:
        p = usable(explicit)
        if p is None: raise BrowserSelectionError('BROWSER_OVERRIDE_MISSING_OR_UNUSABLE')
        return BrowserSelection(str(p), 'explicit')
    if bundled_path:
        p = usable(bundled_path)
        if p: return BrowserSelection(str(p), 'playwright-bundled')
    for name in ('chromium', 'chromium-browser', 'google-chrome', 'chrome', 'msedge'):
        candidate = which(name)
        if candidate:
            p = usable(candidate)
            if p: return BrowserSelection(str(p), 'PATH')
    locations = []
    if platform == 'win32':
        for key in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            if environ.get(key):
                base = Path(environ[key])
                locations.extend([base / 'Google/Chrome/Application/chrome.exe',
                                  base / 'Microsoft/Edge/Application/msedge.exe'])
    elif platform == 'darwin':
        locations = [Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
                     Path('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge')]
    for candidate in locations:
        p = usable(candidate)
        if p: return BrowserSelection(str(p), 'installed-location')
    raise BrowserSelectionError('BROWSER_NOT_FOUND: pass --browser-executable; no installation performed')


def validate_browser(selection, chromium):
    browser = None
    try:
        browser = chromium.launch(headless=True, executable_path=selection.executable, timeout=5000)
        version = browser.version
        if not isinstance(version, str) or not version:
            raise BrowserSelectionError('BROWSER_VERSION_UNAVAILABLE')
        return {'status': 'READY', 'executable': selection.executable,
                'selection_source': selection.source, 'version': version,
                'validation': 'Actual headless Chromium protocol launch; application behavior still requires verification'}
    except BrowserSelectionError:
        raise
    except Exception as exc:
        raise BrowserSelectionError('BROWSER_LAUNCH_UNAVAILABLE: ' + type(exc).__name__) from None
    finally:
        if browser is not None:
            try: browser.close()
            except Exception:
                raise BrowserSelectionError('BROWSER_CLEANUP_FAILED') from None
