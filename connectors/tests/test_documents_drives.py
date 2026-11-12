"""External-drive document reading: volume policy, filtering and persistence."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONNECTORS))
import documents  # noqa: E402


def records(corpus):
    path = corpus / "normalized/documents.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class DriveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home, self.corpus, self.volumes = root / "home", root / "corpus", root / "volumes"
        self.home.mkdir()
        self.corpus.mkdir()
        self.volumes.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def run_documents(self, infos=None, patch=""):
        infos = infos or {}
        code = (
            "import documents; from pathlib import Path; "
            f"documents.VOLUMES=Path({str(self.volumes)!r}); "
            f"documents._mounted_fs_types=lambda: {{}}; documents._backup_mounts=lambda: set(); "
            f"documents._diskutil_info=lambda p: {infos!r}.get(Path(p).name, {{}}); "
            f"{patch}documents.main()"
        )
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus)}
        result = subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, env=env,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_classifier_covers_external_disk_image_network_backup_installer_and_system(self):
        # Keys as diskutil reports them on macOS 26 (an external SSD, a mounted .dmg).
        ssd = {"BusProtocol": "PCI-Express", "FilesystemType": "apfs", "Internal": False, "WritableVolume": True,
               "MountPoint": "/Volumes/Travel SSD"}
        cases = [
            (ssd, None, ["notes"], (), (True, None)),
            ({**ssd, "BusProtocol": "USB", "FilesystemType": "exfat"}, None, ["DCIM"], (), (True, None)),
            ({**ssd, "BusProtocol": "Disk Image", "MountPoint": "/Volumes/Installer"}, None, [], (), (False, "disk_image")),
            ({}, "smbfs", [], (), (False, "network_share")),
            (ssd, None, ["2026-11-01-093000.previous"], (), (False, "time_machine")),
            (ssd, None, ["Backups.backupdb"], (), (False, "time_machine")),
            (ssd, None, ["anything"], ("/Volumes/Travel SSD",), (False, "time_machine")),
            ({**ssd, "WritableVolume": False}, None, ["System", "Install macOS Tahoe.app"], (), (False, "installer_or_system")),
            (ssd, None, ["System", "notes"], (), (True, None)),  # a folder you named System on a drive you write to
        ]
        for info, fs_type, top, backups, expected in cases:
            self.assertEqual(documents.classify_volume(info, fs_type, top, backups), expected, (info, top))

    def test_drive_records_skip_index_folders_and_exports(self):
        drive = self.volumes / "Travel SSD"
        drive.mkdir()
        (drive / "garden.md").write_text("notes from the SSD")
        (drive / "ignored.noindex").mkdir()
        (drive / "ignored.noindex/secret.md").write_text("do not read")
        (drive / ".Spotlight-V100").mkdir()
        (drive / ".Spotlight-V100/index.md").write_text("do not read")
        (drive / "Takeout-export").mkdir()
        (drive / "Takeout-export/conversations.json").write_text("{}")
        (drive / "Takeout-export/message.md").write_text("do not read")
        (drive / "old-laptop/site").mkdir(parents=True)
        (drive / "old-laptop/site/pyproject.toml").write_text("[project]")
        (drive / "old-laptop/site/launch-plan.md").write_text("do not read")
        for repo, marker in (("projects/tool", "dir"), ("projects/tool-wt", "file")):
            (drive / repo).mkdir(parents=True)
            (drive / repo / "design-notes.md").write_text("do not read")
            if marker == "dir":
                (drive / repo / ".git").mkdir()
            else:
                (drive / repo / ".git").write_text("gitdir: elsewhere")
        boot = self.volumes / "Macintosh HD"
        boot.symlink_to("/")
        infos = {"Travel SSD": {"VolumeName": "Travel SSD", "VolumeUUID": "ssd-uuid", "Type": "apfs",
                               "RemovableMedia": True},
                 "Macintosh HD": {"VolumeName": "Macintosh HD", "VolumeUUID": "boot", "Type": "apfs"}}
        result = self.run_documents(infos)
        rs = records(self.corpus)
        self.assertEqual([r["title"] for r in rs], ["garden.md"])
        self.assertEqual(rs[0]["thread"], "Travel SSD")
        self.assertEqual(rs[0]["meta"]["drive"], "Travel SSD")
        self.assertEqual(rs[0]["meta"]["drive_id"], "ssd-uuid")
        notes = json.loads((self.corpus / "manifest.json").read_text())["documents"]["notes"]
        self.assertNotIn("Macintosh HD", {r["thread"] for r in rs})
        self.assertGreaterEqual(notes["unzipped_exports"], 1)
        self.assertNotIn("secret", result.stdout)

    def test_drives_json_auto_read_and_skip(self):
        for name in ("ReadMeDrive", "SkipMeDrive", "AutoOffDrive"):
            drive = self.volumes / name
            drive.mkdir()
            (drive / "note.md").write_text(name)
        infos = {name: {"VolumeName": name, "VolumeUUID": f"{name}-uuid", "Type": "apfs",
                        "RemovableMedia": True} for name in ("ReadMeDrive", "SkipMeDrive", "AutoOffDrive")}
        (self.corpus / "drives.json").write_text(json.dumps({"auto": False, "read": ["ReadMeDrive", "SkipMeDrive"],
                                                               "skip": ["SkipMeDrive"]}))
        self.run_documents(infos)
        self.assertEqual({r["meta"]["drive"] for r in records(self.corpus)}, {"ReadMeDrive"})

    def test_unplugged_drive_records_accumulate(self):
        drive = self.volumes / "KeepsHistory"
        drive.mkdir()
        (drive / "note.md").write_text("stays after unplug")
        info = {"KeepsHistory": {"VolumeName": "KeepsHistory", "VolumeUUID": "keep-id", "Type": "apfs",
                                 "RemovableMedia": True}}
        self.run_documents(info)
        (drive / "note.md").unlink()
        drive.rmdir()
        self.run_documents()
        self.assertEqual([r["text"] for r in records(self.corpus)], ["stays after unplug"])

    def test_renaming_a_drive_keeps_one_record_per_file(self):
        drive = self.volumes / "Old Name"
        drive.mkdir()
        (drive / "letters").mkdir()
        (drive / "letters/to-grandma.md").write_text("dear grandma")
        info = lambda name: {name: {"VolumeName": name, "VolumeUUID": "same-uuid"}}
        self.run_documents(info("Old Name"))
        drive.rename(self.volumes / "New Name")
        self.run_documents(info("New Name"))
        rs = records(self.corpus)
        self.assertEqual([r["id"] for r in rs], ["drive:same-uuid/letters/to-grandma.md"])
        self.assertEqual(rs[0]["meta"]["drive"], "New Name")
        self.assertTrue(rs[0]["meta"]["path"].endswith("/New Name/letters/to-grandma.md"))

    def test_corpus_inside_drive_is_not_walked_and_vault_meta_survives(self):
        drive = self.volumes / "VaultDrive"
        drive.mkdir()
        (drive / "note.md").write_text("drive note")
        (drive / "corpus").mkdir()
        (drive / "corpus/should-not-be-a-document.md").write_text("corpus data")
        vault = drive / "Garden"
        vault.mkdir()
        (vault / "seed.md").write_text("beans")
        obsidian = self.home / "Library/Application Support/obsidian"
        obsidian.mkdir(parents=True)
        (obsidian / "obsidian.json").write_text(json.dumps({"vaults": {"v": {"path": str(vault)}}}))
        self.corpus = drive / "corpus"
        info = {"VaultDrive": {"VolumeName": "VaultDrive", "VolumeUUID": "vault-id", "Type": "apfs",
                                "RemovableMedia": True}}
        self.run_documents(info)
        rs = {r["title"]: r for r in records(self.corpus)}
        self.assertEqual(set(rs), {"note.md", "seed.md"})
        self.assertEqual(rs["seed.md"]["meta"]["vault"], "Garden")
        self.assertNotIn("should-not-be-a-document.md", rs)

    def test_permission_denied_drive_is_not_fatal(self):
        drive = self.volumes / "Locked"
        drive.mkdir()
        (drive / "note.md").write_text("not readable")
        info = {"Locked": {"VolumeName": "Locked", "VolumeUUID": "locked-id", "Type": "apfs",
                            "RemovableMedia": True}}
        patch = (
            f"_real_scandir=documents.os.scandir; "
            f"documents.os.scandir=lambda p: (_ for _ in ()).throw(PermissionError(1, 'Operation not permitted')) "
            f"if str(p)=={str(drive)!r} else _real_scandir(p); "
        )
        result = self.run_documents(info, patch)
        self.assertEqual(records(self.corpus), [])
        notes = json.loads((self.corpus / "manifest.json").read_text())["documents"]["notes"]
        self.assertEqual(notes["drives_not_allowed"], 1)
        self.assertIn("drives_not_allowed", result.stdout)


if __name__ == "__main__":
    unittest.main()
