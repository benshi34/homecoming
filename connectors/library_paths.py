"""Library locations shared by importers, the desktop probe, and file readers."""
import os
import plistlib
from pathlib import Path


def record_path(value, corpus):
    """Resolve corpus-relative references and older references prefixed with the library's name.

    Return the logical path: callers enforce their own symlink/containment rules.
    Absolute references (Photos originals, documents) keep their original meaning.
    """
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    # Prefer a real corpus-relative file when the library itself is named media, raw, or corpus.
    if (corpus / path).exists():
        return corpus / path
    if path.parts and path.parts[0] in {corpus.name, "corpus"}:
        path = Path(*path.parts[1:])
    elif len(path.parts) > 1 and path.parts[1] in {"media", "raw"}:
        # A legacy reference can keep its old prefix after the library itself is renamed.
        previous = corpus / Path(*path.parts[1:])
        if previous.exists():
            return previous
    return corpus / path


def photos_libraries(home=None):
    """Discover named libraries in Pictures and Photos' system library, including external drives.

    UMP_PHOTOS_LIBRARY explicitly selects one library. Unavailable external drives are skipped.
    Keep the default path when nothing exists so the setup probe can explain its missing state.
    """
    home = Path(home or Path.home())
    override = os.environ.get("UMP_PHOTOS_LIBRARY")
    if override:
        return [Path(override).expanduser()]
    candidates = sorted((home / "Pictures").glob("*.photoslibrary"))
    # Photos' system library preference also locates libraries on external volumes.
    # See osxphotos/utils.py:get_system_library_path for the photolibraryd preference locations.
    preferences = (
        "Library/Group Containers/group.com.apple.photolibraryd.private/Library/Preferences/group.com.apple.photolibraryd.private.plist",
        "Library/Containers/com.apple.photolibraryd/Data/Library/Preferences/com.apple.photolibraryd.plist",
    )
    for relative in preferences:
        try:
            prefs = plistlib.loads((home / relative).read_bytes())
            value = prefs.get("SystemLibraryPath") if isinstance(prefs, dict) else None
            if isinstance(value, str) and value:
                candidates.append(Path(value).expanduser())
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
    libraries = list({p.resolve(): p for p in candidates if p.is_dir() and p.suffix == ".photoslibrary"}.values())
    return libraries or [home / "Pictures/Photos Library.photoslibrary"]
