import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QSettings

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from scripture import __version__, references, updater as updater_module
from scripture.controller import esv_attribution, migrate_legacy_api_keys, parse_json, should_retry_range, valid_esv_payload, valid_web_payload
from scripture import main as main_module
from scripture.favorites import FavoritesError, FavoritesStore
from scripture.errors import SecretStoreError
from scripture.secrets import MAX_SECRET_FILE_BYTES, SecretStore
from scripture import secrets as secrets_module
from scripture.updater import (
    JOURNAL_VERSION,
    MAX_UPDATE_BYTES,
    ProcessIdentity,
    authenticity_decision,
    matching_publisher,
    matching_signer,
    normalize_digest,
    parse_release,
    platform_asset_name,
    recovery_decision,
    run_update_helper,
    safe_url,
    sha256_file,
    signature_record_valid,
    tag_tuple,
    verify_file,
    _normalized_executable,
    _process_environment,
    _process_identity,
    _relaunch_after_wait,
    _run_bounded,
    _launch_installed_target,
    _restart_existing_target,
    cleanup_stale_update_helpers,
)


class RetryClassificationTests(unittest.TestCase):
    def test_only_explicit_range_unsupported_http_responses_retry(self):
        body = json.dumps({"error": "Passage ranges are not supported"})
        self.assertTrue(should_retry_range("web", "John 3:14-18", "John 3:16", body, "server returned HTTP 400", 400))
        self.assertFalse(should_retry_range("web", "John 3:14-18", "John 3:16", json.dumps({"error": "Unauthorized"}), "server returned HTTP 401", 401))
        self.assertFalse(should_retry_range("web", "John 3:14-18", "John 3:16", json.dumps({"error": "Passage ranges are not supported"}), "network error: timed out", 0))
        self.assertFalse(should_retry_range("web", "John 3:14-18", "John 3:16", "not-json", "server returned HTTP 400", 400))
        self.assertFalse(should_retry_range("web", "John 3:14-18", "John 3:16", json.dumps({"verses": []}), "server returned HTTP 400", 400))
        self.assertFalse(should_retry_range("web", "John 3:16", "John 3:16", body, "server returned HTTP 400", 400))
        self.assertFalse(should_retry_range("web", "John 3:14-18", "John 3:16", body, "server returned HTTP 400", 400, True))
        esv_body = json.dumps({"code": 4001, "message": "Passage ranges are not supported"})
        self.assertTrue(should_retry_range("esv", "John 3:14-18", "John 3:16", esv_body, "server returned HTTP 400", 400))
        self.assertFalse(should_retry_range("esv", "John 3:14-18", "John 3:16", esv_body, "network error: timed out", 0))

    def test_reference_normalization_rejects_injection_and_bad_order(self):
        self.assertEqual(references.normalize_reference("  1   John   3:16  "), "1 John 3:16")
        for value in ("", "John", "John 0:1", "John 3:0", "John 3:9-8", "John 3:16&x=y", "John\n3:16", "x" * 121):
            self.assertEqual(references.normalize_reference(value), "")


class UpdaterPureTests(unittest.TestCase):
    def test_version_source_is_canonical(self):
        source = (Path(__file__).parents[1] / "src" / "scripture" / "VERSION").read_text(encoding="ascii").strip()
        self.assertEqual(__version__, source)

    def test_tag_validation_is_strict(self):
        self.assertEqual(tag_tuple("v12.3.4"), (12, 3, 4))
        self.assertEqual(tag_tuple("12.3.4"), (12, 3, 4))
        for value in ("v1.2", "v1.2.3.4", "v1.2.x", "v01.2.3", "v1.2.3;echo"):
            self.assertEqual(tag_tuple(value), ())

    def test_url_origin_validation(self):
        self.assertTrue(safe_url("https://api.github.com/repos/a/b/releases/latest"))
        self.assertTrue(safe_url("https://github.com/a/b/releases/download/v1.2.3/a.exe", asset=True))
        self.assertTrue(safe_url("https://release-assets.githubusercontent.com/a", asset=True))
        self.assertFalse(safe_url("https://evil.githubusercontent.com/a", asset=True))
        self.assertFalse(safe_url("http://github.com/a"))
        self.assertFalse(safe_url("https://github.com.evil.example/a", asset=True))
        self.assertFalse(safe_url("https://user:pass@github.com/a", asset=True))
        self.assertFalse(safe_url("https://github.com:444/a", asset=True))

    def test_release_requires_platform_asset_metadata(self):
        payload = {
            "tag_name": "v1.2.3",
            "html_url": "https://github.com/a/b/releases/tag/v1.2.3",
            "assets": [
                {
                    "name": "Scripture.exe",
                    "browser_download_url": "https://github.com/a/b/releases/download/v1.2.3/Scripture.exe",
                    "size": 10,
                    "digest": "sha256:" + "a" * 64,
                }
            ],
        }
        release = parse_release(payload, system="Windows", machine="AMD64")
        self.assertIsNotNone(release)
        self.assertEqual(release.asset.name, "Scripture.exe")
        self.assertEqual(platform_asset_name("Darwin", "arm64", "v1.2.3"), "Scripture-1.2.3-arm64.dmg")
        payload["assets"][0].pop("digest")
        self.assertIsNone(parse_release(payload, system="Windows", machine="AMD64"))
        payload["assets"][0]["digest"] = "sha256:" + "a" * 64
        payload["assets"][0]["size"] = MAX_UPDATE_BYTES + 1
        self.assertIsNone(parse_release(payload, system="Windows", machine="AMD64"))

    def test_external_signature_output_is_bounded_before_buffering(self):
        result = _run_bounded(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 4096)"],
            os.environ.copy(),
            32,
            2,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.returncode, 125)
        self.assertLessEqual(len(result.stdout), 32)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact"
            data = b"verified artifact"
            path.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            self.assertEqual(normalize_digest("SHA256:" + digest), digest)
            self.assertEqual(sha256_file(str(path)), digest)
            self.assertTrue(verify_file(str(path), digest, len(data)))
            self.assertFalse(verify_file(str(path), digest, len(data) + 1))
            path.write_bytes(data + b"x")
            self.assertFalse(verify_file(str(path), digest, len(data)))

    def test_authenticity_and_recovery_fail_closed(self):
        valid = {
            "status": "Valid",
            "signature_type": "Authenticode",
            "subject": "CN=Scripture Publisher, O=Example",
            "thumbprint": "A" * 40,
        }
        self.assertTrue(signature_record_valid(valid))
        self.assertFalse(signature_record_valid({**valid, "status": "NotSigned"}))
        self.assertFalse(signature_record_valid({**valid, "signature_type": "HashOnly"}))
        self.assertFalse(signature_record_valid({**valid, "signature_type": "Unknown"}))
        self.assertTrue(matching_publisher(valid["subject"], valid["subject"].casefold()))
        self.assertFalse(matching_publisher(valid["subject"], "CN=Other Publisher"))
        identity = {"subject": valid["subject"], "thumbprint": valid["thumbprint"]}
        self.assertTrue(matching_signer(identity, {**identity, "subject": identity["subject"].casefold()}))
        self.assertFalse(matching_signer(identity, {**identity, "thumbprint": "B" * 40}))
        self.assertEqual(authenticity_decision(True, True, True, False), "browser")
        self.assertEqual(authenticity_decision(False, True, True, True), "browser")
        self.assertEqual(authenticity_decision(True, True, True, True), "replace")
        self.assertEqual(recovery_decision("new_installed", True, True, True, False), "commit")
        self.assertEqual(recovery_decision("backup_ready", False, False, True, True), "promote")
        self.assertEqual(recovery_decision("backup_ready", True, False, True, False), "restore_backup")
        self.assertEqual(recovery_decision("new_installed", True, False, False, False), "abort")
        self.assertEqual(recovery_decision("prepared", True, False, False, False, True), "keep_current")
        self.assertEqual(recovery_decision("prepared", True, False, False, True), "promote")
        self.assertEqual(recovery_decision("new_installed", False, False, False, False), "abort")

    def test_helper_wait_and_stale_cleanup_fail_safely(self):
        with mock.patch.object(updater_module, "_wait_for_parent", return_value=False), mock.patch.object(
            updater_module, "_launch_installed_target"
        ) as launch:
            _restart_existing_target(123, "missing.exe", "helper.exe")
            launch.assert_not_called()
        original = {"subject": "CN=Original", "thumbprint": "A" * 40}
        replacement = {"subject": "CN=Original", "thumbprint": "B" * 40}
        with mock.patch.object(updater_module, "windows_authenticode_signature", return_value=replacement), mock.patch.object(
            updater_module.subprocess, "Popen"
        ) as popen:
            self.assertFalse(_launch_installed_target("Scripture.exe", "helper.exe", original))
            popen.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "outside"
            target.mkdir()
            link = root / "scripture-update-helper-stale"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                raise unittest.SkipTest("symlink creation unavailable") from exc
            pending = root / "scripture-update-stale"
            pending.mkdir()
            (pending / "artifact").write_bytes(b"x")
            old = 1
            os.utime(pending, (old, old))
            stale_clock = nullcontext()
            try:
                os.utime(link, (old, old), follow_symlinks=False)
            except (NotImplementedError, OSError):
                stale_clock = mock.patch.object(
                    updater_module.time, "time", return_value=max(link.lstat().st_mtime, pending.stat().st_mtime) + 3601
                )
            with stale_clock, mock.patch.object(updater_module.tempfile, "gettempdir", return_value=directory):
                cleanup_stale_update_helpers()
            self.assertFalse(os.path.lexists(link))
            self.assertTrue(target.is_dir())
            self.assertFalse(pending.exists())

    def test_update_helper_rejects_pid_only_arguments(self):
        self.assertEqual(run_update_helper(["target.exe", "pending.exe", "a" * 64, "1", "123", "helper.exe"]), 2)

    def test_parent_wait_binds_pid_to_process_identity(self):
        identity = ProcessIdentity(123, _normalized_executable(sys.executable))
        replacements = (
            ProcessIdentity(124, identity.executable),
            ProcessIdentity(identity.creation_time, identity.executable + ".other"),
        )
        for replacement in replacements:
            with self.subTest(replacement=replacement):
                with mock.patch.object(updater_module, "_process_identity", return_value=replacement), mock.patch.object(
                    updater_module, "_pid_alive"
                ) as alive, mock.patch.object(updater_module.time, "sleep") as sleep:
                    self.assertFalse(
                        updater_module._wait_for_parent(os.getpid(), identity.creation_time, identity.executable)
                    )
                alive.assert_not_called()
                sleep.assert_not_called()
        self.assertFalse(updater_module._wait_for_parent(os.getpid()))

    def test_helper_start_passes_parent_creation_time_and_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "Scripture.exe"
            pending = root / "pending" / "Scripture.new.exe"
            helper_dir = root / "scripture-update-helper-test"
            checker = updater_module.UpdateChecker.__new__(updater_module.UpdateChecker)
            checker._dl_dir = str(pending.parent)
            checker._dl_path = str(pending)
            checker._dl_file = None
            checker._dl_received = 0
            checker._dl_expected_digest = "a" * 64
            checker._dl_expected_size = 1
            checker._artifact_verified = True
            identity = ProcessIdentity(123, _normalized_executable(str(target)))
            with mock.patch.object(updater_module.sys, "executable", str(target)), mock.patch.object(
                updater_module, "_process_identity", return_value=identity
            ), mock.patch.object(updater_module.tempfile, "mkdtemp", return_value=str(helper_dir)), mock.patch.object(
                updater_module.shutil, "copyfile"
            ), mock.patch.object(updater_module, "_windows_signer_match", return_value=True), mock.patch.object(
                updater_module.subprocess, "Popen"
            ) as popen:
                checker._start_update_helper()
            command = popen.call_args.args[0]
            self.assertEqual(
                command[6:],
                [str(os.getpid()), str(identity.creation_time), identity.executable, command[0]],
            )

    def test_signature_failures_relaunch_a_valid_old_target(self):
        identity = {"subject": "CN=Original", "thumbprint": "A" * 40, "signature_type": "authenticode"}
        with mock.patch.object(updater_module, "_wait_for_parent", return_value=True) as wait, mock.patch.object(
            updater_module, "windows_authenticode_signature", side_effect=[None, identity]
        ), mock.patch.object(updater_module, "_windows_signer_match", return_value=False), mock.patch.object(
            updater_module, "_launch_installed_target", return_value=True
        ) as launch:
            self.assertTrue(
                _restart_existing_target(123, "Scripture.exe", "helper.exe", 7, sys.executable)
            )
        wait.assert_called_once_with(123, 7, sys.executable)
        launch.assert_called_once_with("Scripture.exe", "helper.exe", identity)

    def test_post_shutdown_signature_failure_retries_before_relaunch(self):
        identity = {"subject": "CN=Original", "thumbprint": "A" * 40, "signature_type": "authenticode"}
        with mock.patch.object(updater_module, "windows_authenticode_signature", side_effect=[None, identity]), mock.patch.object(
            updater_module, "_windows_signer_match", return_value=True
        ), mock.patch.object(updater_module, "_launch_installed_target", return_value=True) as launch:
            self.assertTrue(_relaunch_after_wait("Scripture.exe", "helper.exe", identity))
        launch.assert_called_once_with("Scripture.exe", "helper.exe", identity)

    def test_interrupted_update_restores_only_the_journaled_backup(self):
        identity = {"subject": "CN=Scripture Publisher", "thumbprint": "A" * 40, "signature_type": "authenticode"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "Scripture.exe"
            update_id = "1" * 32
            backup = root / ("Scripture.exe.scripture-backup-" + update_id)
            staged = root / ("Scripture.exe.scripture-staged-" + update_id)
            pending_dir = Path(tempfile.mkdtemp(prefix="scripture-update-", dir=directory))
            pending = pending_dir / "Scripture.new.exe"
            old_data = b"original signed executable"
            new_data = b"new signed executable"
            target.write_bytes(b"corrupt replacement")
            backup.write_bytes(old_data)
            pending.write_bytes(new_data)
            journal = {
                "version": JOURNAL_VERSION,
                "phase": "new_installed",
                "update_id": update_id,
                "digest": hashlib.sha256(new_data).hexdigest(),
                "size": len(new_data),
                "publisher": identity["subject"],
                "thumbprint": identity["thumbprint"],
                "backup_digest": hashlib.sha256(old_data).hexdigest(),
                "backup_size": len(old_data),
                "target": str(target),
                "backup": str(backup),
                "staged": str(staged),
                "pending": str(pending),
            }
            with mock.patch.object(updater_module.tempfile, "gettempdir", return_value=directory):
                updater_module._write_update_journal(str(target), journal)
                with mock.patch.object(updater_module, "windows_authenticode_signature", return_value=identity):
                    self.assertTrue(updater_module.recover_interrupted_update(str(target)))
            self.assertEqual(target.read_bytes(), old_data)
            self.assertFalse(backup.exists())
            self.assertFalse(pending.exists())
            self.assertFalse((Path(str(target) + ".scripture-update-journal.json")).exists())
            shutil.rmtree(pending_dir, ignore_errors=True)


class PersistenceTests(unittest.TestCase):
    def test_favorites_rejects_invalid_schema_and_writes_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            store = FavoritesStore(directory)
            store.ensure_dir()
            self.assertEqual(store.add("John 3:16", current=[]), ["John 3:16"])
            self.assertEqual(store.list(), ["John 3:16"])
            Path(store.path).write_text(json.dumps({"bad": True}), encoding="utf-8")
            with self.assertRaises(FavoritesError):
                store.list()
            Path(store.path).write_text(json.dumps(["John 3:16", 7]), encoding="utf-8")
            with self.assertRaises(FavoritesError):
                store.list()
            self.assertEqual(store.remove("John 3:16", current=["John 3:16"]), [])

    def test_secret_store_does_not_use_qsettings(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SecretStore(directory)
            store.save("key-value")
            self.assertEqual(store.load(), "key-value")
            store.clear()
            self.assertEqual(store.load(), "")
            with self.assertRaises(Exception):
                store.save("bad\nkey")

    def test_secret_file_read_is_bounded_before_buffering(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SecretStore(directory)
            store.path.write_bytes(b"x" * (MAX_SECRET_FILE_BYTES + 1))
            with mock.patch.object(secrets_module.sys, "platform", "linux"), mock.patch.object(
                Path, "read_bytes", side_effect=AssertionError("unbounded read")
            ):
                with self.assertRaises(SecretStoreError):
                    store.load()

    def test_legacy_qsettings_key_is_migrated_and_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            current = QSettings(str(Path(directory) / "current.ini"), QSettings.Format.IniFormat)
            legacy = QSettings(str(Path(directory) / "legacy.ini"), QSettings.Format.IniFormat)
            current.setValue("apiKey", "legacy-key")
            current.sync()
            store = SecretStore(directory)
            value, error = migrate_legacy_api_keys(current, legacy, store)
            print(
                "QSETTINGS_MIGRATION current_status=%r legacy_status=%r current_contains=%r legacy_contains=%r current_exists=%r legacy_exists=%r"
                % (
                    current.status(),
                    legacy.status(),
                    current.contains("apiKey"),
                    legacy.contains("apiKey"),
                    Path(current.fileName()).exists(),
                    Path(legacy.fileName()).exists(),
                )
            )
            self.assertEqual(value, "legacy-key")
            self.assertEqual(error, "")
            self.assertFalse(current.contains("apiKey"))
            self.assertEqual(store.load(), "legacy-key")

    def test_bounded_kill_uses_process_fallback_on_windows(self):
        process = mock.Mock(pid=123)
        with mock.patch.object(secrets_module.os, "name", "nt"), mock.patch.object(
            secrets_module.os, "killpg", create=True
        ) as killpg:
            secrets_module._kill_process_group(process)
        killpg.assert_not_called()
        process.kill.assert_called_once_with()

    def test_keychain_output_is_bounded_before_buffering(self):
        result = secrets_module._run_bounded(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 4096)"],
            max_bytes=32,
            timeout=2,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.returncode, 125)
        self.assertLessEqual(len(result.stdout), 32)

    def test_bounded_helper_forwards_input_and_enforces_timeout(self):
        result = secrets_module._run_bounded(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
            b"input",
            max_bytes=5,
            timeout=2,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"input")

        result = secrets_module._run_bounded(
            [sys.executable, "-c", "import time; time.sleep(1)"],
            max_bytes=1,
            timeout=0.1,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.returncode, 124)

        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "secret", "ESV_API_KEY": "secret"}, clear=False):
            self.assertNotIn("GITHUB_TOKEN", secrets_module._helper_environment())
            self.assertNotIn("ESV_API_KEY", secrets_module._helper_environment())
            self.assertNotIn("GITHUB_TOKEN", _process_environment())
            self.assertEqual(_process_environment()["PATH"], r"C:\Windows\System32;C:\Windows")


class SchemaTests(unittest.TestCase):
    def test_json_roots_and_provider_shapes_are_checked(self):
        with self.assertRaises(ValueError):
            parse_json("[]")
        with self.assertRaises(ValueError):
            parse_json("not json")
        self.assertTrue(valid_esv_payload({"canonical": "John 3:16", "passages": ["[1] text"]}))
        self.assertFalse(valid_esv_payload({"passages": [{"text": "bad"}]}))
        self.assertTrue(valid_web_payload({"reference": "John 3:16", "verses": [{"verse": 1, "text": "text"}]}))
        self.assertFalse(valid_web_payload({"verses": [{"verse": 1}]}))
        self.assertFalse(valid_web_payload({"verses": [{"verse": True, "text": "text"}]}))
        self.assertEqual(esv_attribution({"copyright": "Provider terms", "attribution": "Provider terms"}), "")
        self.assertEqual(esv_attribution({}), "")

    def test_reference_urls_encode_delimiters_and_reject_injection(self):
        url = references.browser_url("1 John 1:7", "web")
        self.assertNotIn(" ", url)
        self.assertIn("1%20John%201%3A7", url)
        self.assertEqual(references.browser_url("John 3:16&x=y", "web"), "")
        self.assertEqual(references.encode_reference("John\n3:16"), "")

    def test_macos_tag_workflow_requires_signing_and_notarization(self):
        workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "build-macos.yml").read_text(encoding="utf-8")
        self.assertIn("if: github.ref_type == 'tag'", workflow)
        self.assertIn("Developer ID signing secrets are required for a tag build", workflow)
        self.assertIn("notarization secrets are required for a tag build", workflow)
        self.assertIn("codesign --verify --deep --strict", workflow)
        self.assertIn("xcrun stapler validate", workflow)
        self.assertNotIn('if [[ -z "${MACOS_CERT_BASE64:-}" ]]; then exit 0; fi', workflow)
        self.assertNotIn('if [[ -z "${MACOS_NOTARIZE_APPLE_ID:-}" ]]; then exit 0; fi', workflow)
        publish = workflow.split("  publish:", 1)[1]
        self.assertIn("if: github.ref_type == 'tag'", publish)
        self.assertIn("needs.build.result == 'success'", publish)

    def test_startup_log_rotates_before_append(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "startup-error.log"
            path.write_text("x" * 1024, encoding="utf-8")
            old_limit = main_module.STARTUP_LOG_MAX_BYTES
            old_backups = main_module.STARTUP_LOG_BACKUPS
            main_module.STARTUP_LOG_MAX_BYTES = 100
            main_module.STARTUP_LOG_BACKUPS = 2
            try:
                main_module._rotate_startup_log(path)
            finally:
                main_module.STARTUP_LOG_MAX_BYTES = old_limit
                main_module.STARTUP_LOG_BACKUPS = old_backups
            self.assertTrue(path.with_name(path.name + ".1").exists())


if __name__ == "__main__":
    unittest.main()
