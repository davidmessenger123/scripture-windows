import ctypes
import datetime
import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QGuiApplication, QImage

from scripture import references
from scripture import secrets as secrets_module
from scripture import secure_files as secure_files_module
from scripture.controller import (
    MAX_ANIMATION_SPEED,
    MAX_VERSE_FONT_PX,
    MIN_SCRIM_OPACITY,
    AppController,
    daily_event_due,
)
from scripture.favorites import FavoritesStore
from scripture.fetcher import ESV_COMMON_QUERY
from scripture.main import TrayNotification, TrayNotificationRouter, _route_tray_click, daily_notification_body
from scripture.passage_cache import (
    CACHE_VERSION,
    MAX_AGE_SECONDS,
    PassageCache,
    PassageCacheError,
    fingerprint_secret,
    record_mac,
)
from scripture.secrets import SecretStore
from scripture.secure_files import create_owner_only_directory, owner_only_dacl_valid
from scripture.sharing import (
    CARD_HEIGHT,
    CARD_WIDTH,
    ShareError,
    copy_card,
    copy_image,
    default_filename,
    format_plain_text,
    render_card,
    save_card_atomic,
)

LONG_PROVIDER_TEXT = (
    "Scripture quotations are from the ESV® Bible, © 2001 Crossway. "
    "Used by permission. All rights reserved. This provider legal block must never be displayed or shared."
)


class FakeFetcher(QObject):
    esv_result = Signal(int, str, str, int)
    web_result = Signal(int, str, str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fail = False
        self.requested = []
        self.aborted = 0

    def abort(self):
        self.aborted += 1

    def fetch_esv(self, tag, reference, api_key):
        self.requested.append(("esv", reference, api_key))
        if self.fail:
            self.esv_result.emit(tag, "", "network error: offline", 0)
            return
        body = json.dumps({
            "canonical": "John 3:16",
            "passages": [
                "[14] Before the passage.\n[15] Context before the verse.\n"
                "[16] For God so loved the world.\n[17] Context after the verse.\n"
                "[18] The end of the passage.\n\n" + LONG_PROVIDER_TEXT
            ],
            "copyright": LONG_PROVIDER_TEXT,
        })
        self.esv_result.emit(tag, body, "", 200)

    def fetch_web(self, tag, reference, translation):
        self.requested.append((translation, reference, ""))
        if self.fail:
            self.web_result.emit(tag, "", "network error: offline", 0)
            return
        body = json.dumps({
            "reference": "John 3:16",
            "translation": {"name": "World English Bible"},
            "verses": [{"verse": 16, "text": "For God so loved the world."}],
        })
        self.web_result.emit(tag, body, "", 200)


class DeferredFetcher(QObject):
    esv_result = Signal(int, str, str, int)
    web_result = Signal(int, str, str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.calls = []
        self.aborted = 0

    def abort(self):
        self.aborted += 1

    def fetch_esv(self, tag, reference, api_key):
        self.calls.append(("esv", tag, reference, api_key))

    def fetch_web(self, tag, reference, translation):
        self.calls.append((translation, tag, reference, ""))

    @staticmethod
    def esv_body(reference="John 3:16", legal_suffix=""):
        return json.dumps({
            "canonical": reference,
            "passages": ["[16] For God so loved the world." + legal_suffix],
            "copyright": legal_suffix,
        })

    @staticmethod
    def web_body(reference="John 3:16", translation="World English Bible"):
        return json.dumps({
            "reference": reference,
            "translation": {"name": translation},
            "verses": [{"verse": 16, "text": "For God so loved the world."}],
        })


class SecurityPlatformTests(unittest.TestCase):
    def test_macos_native_keychain_crud_uses_security_framework_boundary(self):
        state = {"item": False, "value": b"native-secret", "added": [], "modified": [], "deleted": False}
        dictionary_sizes = []
        holder = {}

        class Core:
            def __init__(self):
                self.data = {}

            def CFStringCreateWithCString(self, allocator, value, encoding):
                return 101 if b"org.davidjm" in value else 102

            def CFBooleanCreate(self, allocator, value):
                return 401

            def CFDataCreate(self, allocator, pointer, length):
                value = ctypes.string_at(pointer, length)
                item = 600 + len(self.data)
                holder[item] = ctypes.create_string_buffer(value, len(value))
                self.data[item] = (holder[item], len(value))
                return item

            def CFDataGetBytePtr(self, data):
                key = data.value if isinstance(data, ctypes.c_void_p) else data
                return ctypes.cast(self.data[key][0], ctypes.c_void_p).value

            def CFDataGetLength(self, data):
                key = data.value if isinstance(data, ctypes.c_void_p) else data
                return self.data[key][1]

            def CFDictionaryCreate(self, allocator, keys, values, count, key_callbacks, value_callbacks):
                dictionary_sizes.append(count)
                return 501

            def CFRelease(self, value):
                return None

        class Security:
            core = None

            def SecItemCopyMatching(self, query, result):
                if not state["item"]:
                    return secrets_module.KEYCHAIN_ITEM_NOT_FOUND
                buffer = ctypes.create_string_buffer(state["value"], len(state["value"]))
                result._obj.value = self.core.CFDataCreate(None, ctypes.cast(buffer, ctypes.c_void_p), len(state["value"]))
                return secrets_module.KEYCHAIN_SUCCESS

            def SecItemAdd(self, attributes, result):
                state["item"] = True
                state["value"] = b"native-secret"
                state["added"].append(state["value"])
                return secrets_module.KEYCHAIN_SUCCESS

            def SecItemUpdate(self, query, attributes):
                if not state["item"]:
                    return secrets_module.KEYCHAIN_ITEM_NOT_FOUND
                state["value"] = b"updated-secret"
                state["modified"].append(state["value"])
                return secrets_module.KEYCHAIN_SUCCESS

            def SecItemDelete(self, query):
                state["deleted"] = True
                state["item"] = False
                return secrets_module.KEYCHAIN_SUCCESS

        core = Core()
        security = Security()
        security.core = core
        api = (core, security)
        with mock.patch.object(secrets_module.sys, "platform", "darwin"), mock.patch.object(
            secrets_module, "_macos_security_api", return_value=api
        ):
            secrets_module._keychain_save("native-secret")
            self.assertEqual(state["added"], [b"native-secret"])
            self.assertEqual(secrets_module._keychain_load(), "native-secret")
            secrets_module._keychain_save("updated-secret")
            self.assertEqual(state["modified"], [b"updated-secret"])
            secrets_module._keychain_clear()
            self.assertTrue(state["deleted"])
        self.assertGreaterEqual(dictionary_sizes.count(1), 2)
        self.assertIn(4, dictionary_sizes)
        self.assertIn(3, dictionary_sizes)

    @unittest.skipUnless(os.name == "nt", "Windows-only integration test")
    def test_windows_real_private_directory_and_committed_file_dacl(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private"
            create_owner_only_directory(private)
            self.assertTrue(owner_only_dacl_valid(private))
            committed = secure_files_module.secure_atomic_write_bytes(str(private / "card.bin"), b"card")
            self.assertTrue(owner_only_dacl_valid(committed))

    def test_windows_library_loading_uses_system_directory(self):
        root = Path(__file__).parents[1] / "src" / "scripture"
        secure_source = (root / "secure_files.py").read_text(encoding="utf-8")
        secrets_source = (root / "secrets.py").read_text(encoding="utf-8")
        updater_source = (root / "updater.py").read_text(encoding="utf-8")
        self.assertIn("GetSystemDirectoryW", secure_source)
        self.assertIn("get_length_sid = advapi32.GetLengthSid", secure_source)
        self.assertIn("copy_sid.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]", secure_source)
        self.assertIn("local_alloc = kernel32.LocalAlloc", secure_source)
        self.assertIn("SetSecurityInfo", secure_source)
        self.assertIn("GetSecurityDescriptorDacl", secure_source)
        self.assertIn("_SE_FILE_OBJECT", secure_source)
        self.assertNotIn("SetKernelObjectSecurity", secure_source)
        self.assertNotIn("_SE_KERNEL_OBJECT", secure_source)
        self.assertIn("GetSecurityDescriptorDacl", secure_source)
        self.assertIn("GetAclInformation", secure_source)
        self.assertIn("GetAce", secure_source)
        self.assertIn("EqualSid", secure_source)
        self.assertIn("ACCESS_ALLOWED_ACE_STRUCT", secure_source)
        self.assertIn("ACL_SIZE_INFORMATION_STRUCT", secure_source)
        self.assertIn("_SE_DACL_PROTECTED", secure_source)
        self.assertNotIn("ConvertSecurityDescriptorToStringSecurityDescriptorW", secure_source)
        self.assertIn("PROTECTED_DACL_SECURITY_INFORMATION", secure_source)
        self.assertIn("FlushFileBuffers", secure_source)
        self.assertIn("secure_atomic_write_bytes", secure_source)
        self.assertIn("CreateFileW", secure_source)
        self.assertIn("_CREATE_NEW", secure_source)
        self.assertIn("_GENERIC_READ | _GENERIC_WRITE | _READ_CONTROL | _WRITE_DAC", secure_source)
        self.assertIn("_GENERIC_READ | _GENERIC_WRITE", secure_source)
        self.assertIn("_GENERIC_READ = 0x80000000", secure_source)
        self.assertNotIn("SystemRoot", secrets_source)
        self.assertNotIn("ctypes.WinDLL", secrets_source)
        self.assertNotIn("ctypes.WinDLL", updater_source)
        self.assertIn("SecItemCopyMatching", secrets_source)
        self.assertIn("SecItemAdd", secrets_source)
        self.assertIn("SecItemUpdate", secrets_source)
        self.assertIn("SecItemDelete", secrets_source)
        self.assertIn("CFDataGetBytePtr", secrets_source)
        self.assertIn("CFDataCreate.argtypes", secrets_source)
        self.assertIn("SecItemCopyMatching.argtypes", secrets_source)
        self.assertIn("Security.framework", secrets_source)
        self.assertNotIn("SecKeychainFindGenericPassword", secrets_source)
        self.assertNotIn("SecKeychainItemFreeContent", secrets_source)
        self.assertNotIn("CFRelease(data)", secrets_source)
        self.assertNotIn("/usr/bin/security", secrets_source)
        self.assertIn("advapi32, descriptor, local_free = _owner_only_descriptor()", secure_source)
        self.assertNotIn("token, _sid, descriptor, local_free, close_handle = _owner_only_descriptor()", secure_source)
        calls = []
        sid_buffer = ctypes.create_string_buffer(8)
        allocated = []

        class Function:
            def __init__(self, callback):
                self.callback = callback
                self.argtypes = None
                self.restype = None

            def __call__(self, *args):
                return self.callback(*args)

        advapi = type("Advapi", (), {})()
        kernel = type("Kernel", (), {})()
        advapi.OpenProcessToken = Function(lambda process, access, token: setattr(token._obj, "value", 123) or 1)
        def token_info(token, info_class, data, length, returned):
            if data is None:
                returned._obj.value = ctypes.sizeof(secure_files_module.TOKEN_USER_STRUCT)
                return 0
            user = ctypes.cast(data, ctypes.POINTER(secure_files_module.TOKEN_USER_STRUCT)).contents
            user.Sid = ctypes.cast(sid_buffer, ctypes.POINTER(ctypes.c_ubyte))
            user.Attributes = 0
            return 1
        advapi.GetTokenInformation = Function(token_info)
        advapi.ConvertSidToStringSidW = Function(lambda sid, text: setattr(text._obj, "value", "S-1-5-21") or 1)
        advapi.GetLengthSid = Function(lambda sid: 8)
        def copy_sid(length, destination, source):
            calls.append((length, destination, source))
            return 1
        advapi.CopySid = Function(copy_sid)
        kernel.GetCurrentProcess = Function(lambda: 99)
        def local_alloc(flags, size):
            value = ctypes.create_string_buffer(size)
            allocated.append(value)
            return ctypes.cast(value, ctypes.c_void_p)
        kernel.LocalAlloc = Function(local_alloc)
        kernel.LocalFree = Function(lambda value: calls.append(("free", value)) or 0)
        kernel.CloseHandle = Function(lambda value: calls.append(("close", value)) or 1)
        with mock.patch.object(secure_files_module, "windows_system_library", side_effect=lambda name: advapi if "advapi" in name else kernel), mock.patch.object(
            secure_files_module.ctypes, "get_last_error", return_value=122, create=True
        ):
            result = secure_files_module._current_user_sid()
        self.assertEqual(calls[0][0], 8)
        self.assertIs(advapi.CopySid.argtypes[0], secure_files_module.wintypes.DWORD)
        _advapi, _kernel, token, sid, sid_text, local_free, close_handle = result
        local_free(sid)
        local_free(sid_text)
        close_handle(token)
        descriptor = ctypes.c_void_p(0x1234)
        dacl = ctypes.c_void_p(0x5678)
        fake_advapi = type("FakeAdvapi", (), {})()
        def get_dacl(descriptor_pointer, present, dacl_pointer, defaulted):
            present._obj.value = 1
            dacl_pointer._obj.value = dacl.value
            return 1
        fake_advapi.GetSecurityDescriptorDacl = Function(get_dacl)
        fake_advapi.SetSecurityInfo = Function(lambda *args: calls.append(("set_security_info", args)) or 0)
        free_descriptor = mock.Mock()
        with mock.patch.object(
            secure_files_module,
            "_owner_only_descriptor",
            return_value=(fake_advapi, descriptor, free_descriptor),
        ):
            secure_files_module._restrict_handle_windows(99)
        free_descriptor.assert_called_once_with(descriptor)
        self.assertTrue(any(call[0] == "set_security_info" for call in calls if isinstance(call, tuple)))
        structural = type("StructuralAdvapi", (), {})()
        safe_sid_storage = ctypes.create_string_buffer(b"\x01" * 8)
        wrong_sid_storage = ctypes.create_string_buffer(b"\x02" * 8)
        current_sid = ctypes.c_void_p(ctypes.addressof(safe_sid_storage))
        descriptor_owner = ctypes.c_void_p(ctypes.addressof(safe_sid_storage))
        dacl_pointer = ctypes.c_void_p(200)
        state = {
            "descriptor_owner": ctypes.addressof(safe_sid_storage),
            "count": 1,
            "ace_type": 0,
            "flags": 0,
            "mask": secure_files_module._FILE_ALL_ACCESS,
            "sid": safe_sid_storage,
        }
        ace_storage = secure_files_module.ACCESS_ALLOWED_ACE_STRUCT()

        def pointer_value(value):
            return value.value if isinstance(value, ctypes.c_void_p) else int(value)

        structural.GetSecurityDescriptorOwner = Function(
            lambda descriptor, output, defaulted: setattr(output._obj, "value", state["descriptor_owner"]) or setattr(defaulted._obj, "value", 0) or 1
        )
        structural.GetSecurityDescriptorDacl = Function(
            lambda descriptor, present, output, defaulted: setattr(present._obj, "value", 1)
            or setattr(output._obj, "value", dacl_pointer.value)
            or setattr(defaulted._obj, "value", 0)
            or 1
        )
        structural.GetSecurityDescriptorControl = Function(
            lambda descriptor, control, revision: setattr(control._obj, "value", secure_files_module._SE_DACL_PROTECTED) or setattr(revision._obj, "value", 1) or 1
        )
        def acl_info(acl, buffer, length, info_class):
            buffer._obj.AceCount = state["count"]
            buffer._obj.AclBytesInUse = 12
            buffer._obj.AclBytesFree = 0
            return 1
        structural.GetAclInformation = Function(acl_info)
        def get_ace(acl, index, output):
            if index != 0:
                return 0
            ace_storage.AceType = state["ace_type"]
            ace_storage.AceFlags = state["flags"]
            ace_storage.AceSize = ctypes.sizeof(ace_storage)
            ace_storage.Mask = state["mask"]
            sid_offset = secure_files_module.ACCESS_ALLOWED_ACE_STRUCT.SidStart.offset
            sid_size = ctypes.sizeof(ace_storage) - sid_offset
            ctypes.memmove(ctypes.byref(ace_storage, sid_offset), state["sid"], sid_size)
            output._obj.value = ctypes.addressof(ace_storage)
            return 1
        structural.GetAce = Function(get_ace)
        def equal_sid(left, right):
            sid_size = ctypes.sizeof(ace_storage) - secure_files_module.ACCESS_ALLOWED_ACE_STRUCT.SidStart.offset
            return ctypes.string_at(pointer_value(left), sid_size) == ctypes.string_at(pointer_value(right), sid_size)
        structural.EqualSid = Function(equal_sid)
        for name, changes, expected in (
            ("one-safe", {}, True),
            ("owner-different", {"descriptor_owner": ctypes.addressof(wrong_sid_storage)}, True),
            ("extra", {"count": 2}, False),
            ("deny", {"ace_type": 1}, False),
            ("wrong-SID", {"sid": wrong_sid_storage}, False),
        ):
            with self.subTest(name=name):
                state.update({
                    "descriptor_owner": ctypes.addressof(safe_sid_storage),
                    "count": 1,
                    "ace_type": 0,
                    "flags": 0,
                    "mask": secure_files_module._FILE_ALL_ACCESS,
                    "sid": safe_sid_storage,
                })
                state.update(changes)
                with mock.patch.object(secure_files_module, "windows_system_library", return_value=structural):
                    self.assertEqual(
                        secure_files_module._descriptor_owner_only_valid(
                            ctypes.c_void_p(1), descriptor_owner, dacl_pointer, current_sid
                        ),
                        expected,
                    )
    def test_taxonomy_uses_only_the_curated_deck(self):
        self.assertEqual(len(references.SCRIPTURE), 185)
        self.assertEqual(len(set(references.SCRIPTURE)), 185)
        for values in references.TOPIC_REFERENCES.values():
            self.assertTrue(values)
            self.assertTrue(values.issubset(references.SCRIPTURE))
        self.assertEqual(references.filtered_references("invalid", "invalid"), [])
        self.assertTrue(references.filtered_references("John", "Love"))
        self.assertTrue(all(references.book_for_reference(item) == "John" for item in references.filtered_references("John", "Love")))
        self.assertEqual(references.topics_for_reference("John 3:16"), references.topics_for_reference("John 3:16"))

    def test_esv_legal_suffix_variants_are_removed_before_verse_parsing(self):
        variants = (
            LONG_PROVIDER_TEXT,
            "Scripture quotations from the ESV Bible (The Holy Bible, English Standard Version), Copyright 2001 by Crossway. Used by permission. All rights reserved. esv.org",
            "ESV® Bible — English Standard Version. © Crossway. Used by permission.",
            "Copyright 2001 by Crossway. All rights reserved. esv.org",
        )
        for variant in variants:
            with self.subTest(variant=variant):
                passage = "[16] The verse itself.\n\n" + variant
                cleaned = references.strip_esv_legal_suffix(passage)
                before, focal, after = references.parse_numbered_passage(cleaned, 16)
                self.assertEqual((before, focal, after), ("", "[16] The verse itself.", ""))
                self.assertFalse(references.esv_legal_text_present(cleaned))
        self.assertIn("include-copyright=false", ESV_COMMON_QUERY)
        self.assertNotIn("include-copyright=true", ESV_COMMON_QUERY)


class PassageCacheTests(unittest.TestCase):
    def sample(self, provider="web", identity="", passage="John 3:14-18", anchor="John 3:16"):
        verse = int(anchor.rsplit(":", 1)[1])
        return {
            "provider": provider,
            "translation_id": provider,
            "passage": passage,
            "anchor": anchor,
            "identity": identity,
            "before": "[14] For God so loved the world.",
            "focal": "[%d] For God so loved the world." % verse,
            "after": "[18] There is no condemnation.",
            "reference": anchor,
            "translation_name": references.expected_translation_name(provider),
            "attribution": "Attribution",
        }

    def put(self, store, value, now=1000):
        store.put(now=now, **value)

    def test_round_trip_bounds_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PassageCache(directory)
            self.put(store, self.sample())
            self.assertEqual(store.size(1000), 1)
            self.assertIsNotNone(store.get("web", "John 3:14-18", "John 3:16", "", 1000))
            if os.name == "nt":
                self.assertTrue(owner_only_dacl_valid(store.path))
            else:
                mode = stat.S_IMODE(Path(store.path).stat().st_mode)
                self.assertEqual(mode, 0o600)
            with mock.patch("scripture.passage_cache.MAX_ENTRIES", 2):
                self.put(store, self.sample(passage="John 3:16"), 1001)
                self.put(store, self.sample(anchor="John 3:15", passage="John 3:13-17"), 1002)
                self.put(store, self.sample(anchor="John 3:14", passage="John 3:12-16"), 1003)
                self.assertEqual(store.size(1003), 2)

    def test_esv_identity_is_a_fingerprint_not_the_key(self):
        secret = "secret-api-key"
        identity = fingerprint_secret(secret)
        with tempfile.TemporaryDirectory() as directory:
            store = PassageCache(directory)
            self.put(store, self.sample("esv", identity))
            raw = Path(store.path).read_text(encoding="utf-8")
            self.assertNotIn(secret, raw)
            self.assertIn(identity, raw)
            with self.assertRaises(PassageCacheError):
                store.put(
                    "esv",
                    "esv",
                    "John 3:14-18",
                    "John 3:16",
                    "raw-key",
                    "",
                    "[16] text",
                    "",
                    "John 3:16",
                    "English Standard Version",
                    "",
                )

    def test_expired_entries_are_not_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PassageCache(directory)
            self.put(store, self.sample(), now=1000)
            self.assertIsNone(store.get("web", "John 3:14-18", "John 3:16", "", 1000 + MAX_AGE_SECONDS + 1))

    def test_invalid_schema_and_oversized_entries_fail_closed(self):
        self.assertEqual(CACHE_VERSION, 3)
        for version in (1, 2):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                store = PassageCache(directory)
                Path(store.path).write_text(json.dumps({"version": version, "entries": []}), encoding="utf-8")
                os.chmod(store.path, 0o600)
                with self.assertRaises(PassageCacheError):
                    store.list()
        value = self.sample()
        value["focal"] = ""
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(PassageCacheError):
                self.put(PassageCache(directory), value)

    def test_cache_authenticates_canonical_records_with_install_key(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PassageCache(directory)
            self.put(store, self.sample())
            key = bytes.fromhex(Path(store.key_path).read_text(encoding="ascii"))
            path = Path(store.path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["entries"][0]["attribution"] = "tampered"
            payload["entries"][0]["cached_at"] = int(time.time())
            path.write_text(json.dumps(payload), encoding="utf-8")
            os.chmod(path, 0o600)
            with self.assertRaises(PassageCacheError):
                PassageCache(directory).list()
            payload["entries"][0]["mac"] = record_mac(key, payload["entries"][0])
            path.write_text(json.dumps(payload), encoding="utf-8")
            os.chmod(path, 0o600)
            self.assertEqual(len(PassageCache(directory).list()), 1)

    def test_fresh_private_directories_and_cache_key_are_owner_only(self):
        def assert_private(path, mode):
            if os.name == "nt":
                self.assertTrue(owner_only_dacl_valid(str(path)))
            else:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fresh" / "app"
            create_owner_only_directory(root)
            assert_private(root, 0o700)
            store = PassageCache(str(root))
            self.put(store, self.sample())
            assert_private(Path(store.key_path), 0o600)
            assert_private(Path(store.path), 0o600)
            secret = SecretStore(str(root))
            secret.save("secret")
            assert_private(Path(secret.path), 0o600)
            share = root / "Pictures" / "Scripture"
            create_owner_only_directory(share)
            assert_private(share, 0o700)

        mutations = (
            ("translation_id", "esv"),
            ("translation_name", "King James Version"),
            ("reference", "John 4:1"),
            ("passage", "John 4:1"),
            ("focal", "For God so loved the world."),
        )
        for field, replacement in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                store = PassageCache(directory)
                self.put(store, self.sample())
                path = Path(store.path)
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["entries"][0][field] = replacement
                path.write_text(json.dumps(payload), encoding="utf-8")
                os.chmod(path, 0o600)
                reopened = PassageCache(directory)
                with self.assertRaises(PassageCacheError):
                    reopened.list()


class SharingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication(["scripture-tests"])

    def test_plain_text_card_and_clipboard(self):
        text = format_plain_text(
            "[14] Before",
            "[16] For God so loved the world.",
            "[18] After",
            "John 3:16",
            "World English Bible",
        )
        self.assertIn("John 3:16", text)
        self.assertIn("World English Bible", text)
        self.assertNotIn(LONG_PROVIDER_TEXT, text)
        self.assertNotIn("<span", text)
        sharing_source = Path(__file__).parents[1].joinpath("src", "scripture", "sharing.py").read_text(encoding="utf-8")
        overlay_source = Path(__file__).parents[1].joinpath("src", "scripture", "qml", "main.qml").read_text(encoding="utf-8")
        self.assertNotIn("attribution", sharing_source.lower())
        self.assertNotIn("translationAttribution", overlay_source)
        first = render_card(text)
        second = render_card(text)
        self.assertEqual(first.width(), CARD_WIDTH)
        self.assertEqual(first.height(), CARD_HEIGHT)
        self.assertTrue(first == second)
        copy_card(text, first)
        mime = QGuiApplication.clipboard().mimeData()
        self.assertIsNotNone(mime)
        self.assertIn("image/png", mime.formats())
        self.assertTrue(bytes(mime.data("image/png")).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn("John 3:16", mime.text())
        self.assertNotIn(LONG_PROVIDER_TEXT, mime.text())
        copy_image(first)
        self.assertEqual(QGuiApplication.clipboard().image().size(), first.size())

    def test_atomic_png_save_and_safe_filename(self):
        sharing_source = Path(__file__).parents[1].joinpath("src", "scripture", "sharing.py").read_text(encoding="utf-8")
        self.assertIn("secure_atomic_write_bytes", sharing_source)
        self.assertNotIn("QSaveFile", sharing_source)
        self.assertNotIn("mkstemp", sharing_source)
        text = format_plain_text("", "For God so loved the world.", "", "John 3:16", "WEB")
        image = render_card(text)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / default_filename("John 3:16")
            result = save_card_atomic(image, path)
            self.assertTrue(Path(result).samefile(path))
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 100)
            if os.name == "nt":
                self.assertTrue(owner_only_dacl_valid(path))
            else:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(ShareError):
                save_card_atomic(image, Path(directory) / "card.txt")

    def test_precommit_sharing_failures_are_share_errors(self):
        text = format_plain_text("", "For God so loved the world.", "", "John 3:16", "WEB")
        image = render_card(text)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "card.png"
            with mock.patch("scripture.sharing.secure_atomic_write_bytes", side_effect=OSError("denied")):
                with self.assertRaises(ShareError):
                    save_card_atomic(image, path)
            self.assertFalse(path.exists())

    def test_card_text_and_layout_are_bounded(self):
        with self.assertRaises(ShareError):
            format_plain_text("", "x" * (49 * 1024), "", "John 3:16", "WEB")
        with self.assertRaises(ShareError):
            render_card("x" * 5000)
        with self.assertRaises(ShareError):
            render_card("\n".join(["word"] * 90))
        text = format_plain_text("", "For God so loved the world.", "", "John 3:16", "WEB")
        with self.assertRaises(ShareError):
            render_card(text + "\n" + ("long sentence " * 1800) + "\n— John 3:16\nWEB")


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication(["scripture-controller-tests"])

    def controller(self, directory, fetcher, values=None):
        settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
        legacy = QSettings(str(Path(directory) / "legacy.ini"), QSettings.Format.IniFormat)
        for key, value in (values or {}).items():
            settings.setValue(key, value)
        settings.sync()
        return AppController(
            settings=settings,
            legacy_settings=legacy,
            store=FavoritesStore(directory),
            cache=PassageCache(directory),
            secrets=SecretStore(directory),
            fetcher=fetcher,
            data_dir=directory,
        )

    def test_settings_validate_and_clamp(self):
        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeFetcher()
            controller = self.controller(directory, fetcher)
            saved = controller.save_settings(
                "",
                "WEB",
                "John 3:16",
                "07:30",
                "08:00",
                "John",
                "Love",
                True,
                "999",
                "0.01",
                "99",
            )
            self.assertTrue(saved)
            self.assertEqual(controller.settingsVerseFontPx, MAX_VERSE_FONT_PX)
            self.assertEqual(controller.settingsScrimOpacity, MIN_SCRIM_OPACITY)
            self.assertEqual(controller.settingsAnimationSpeed, MAX_ANIMATION_SPEED)
            self.assertEqual(controller.settingsBookFilter, "John")
            self.assertEqual(controller.settingsTopicFilter, "Love")
            self.assertFalse(controller.save_settings(
                "",
                "WEB",
                "",
                "",
                "",
                "",
                "",
                True,
                "28",
                "0.78",
                "1",
            ))
            self.assertTrue(controller.settingsNoticeError)
            controller.deleteLater()

    def test_network_first_cache_fallback_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeFetcher()
            controller = self.controller(directory, fetcher, {"fixedReference": "John 3:16", "translation": "WEB"})
            controller.refresh()
            self.assertFalse(controller.fromCache)
            self.assertEqual(controller.passageCacheSize, 1)
            first_request_count = len(fetcher.requested)
            fetcher.fail = True
            controller.refresh()
            self.assertEqual(len(fetcher.requested), first_request_count + 1)
            self.assertTrue(controller.fromCache)
            self.assertIn("fallback", controller.fetchNotice.lower())
            controller.deleteLater()

    def test_superseded_requests_and_range_retry_keep_immutable_context(self):
        with tempfile.TemporaryDirectory() as directory:
            SecretStore(directory).save("old-key")
            fetcher = DeferredFetcher()
            controller = self.controller(
                directory,
                fetcher,
                {"fixedReference": "John 3:16", "translation": "ESV"},
            )
            controller.refresh()
            first = fetcher.calls[-1]
            self.assertEqual((first[0], first[2], first[3]), ("esv", "John 3:14-18", "old-key"))
            fetcher.esv_result.emit(
                first[1],
                json.dumps({"code": 400, "message": "Ranges are not supported"}),
                "server returned HTTP 422",
                422,
            )
            retry = fetcher.calls[-1]
            self.assertEqual((retry[0], retry[2], retry[3]), ("esv", "John 3:16", "old-key"))
            controller._settings.setValue("translation", "WEB")
            controller._api_key_value = "new-key"
            controller._on_setting_changed("translation", "WEB")
            controller.refresh()
            current = fetcher.calls[-1]
            self.assertEqual(current[:3], ("web", current[1], "John 3:14-18"))
            fetcher.esv_result.emit(retry[1], fetcher.esv_body(), "", 200)
            self.assertTrue(controller.loading)
            self.assertEqual(controller.translationId, "web")
            fetcher.web_result.emit(current[1], fetcher.web_body(), "", 200)
            self.assertFalse(controller.loading)
            self.assertEqual(controller.translationId, "web")
            cached = json.loads(Path(directory, "passage-cache.json").read_text(encoding="utf-8"))["entries"][0]
            self.assertEqual((cached["provider"], cached["translation_id"], cached["translation_name"]), ("web", "web", "World English Bible"))
            controller.deleteLater()

    def test_malformed_payload_conversion_always_reaches_terminal_state(self):
        cases = (
            ("web", lambda body: body),
            ("esv", lambda body: body),
        )
        for provider, _ in cases:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                secret = "test-key" if provider == "esv" else ""
                if secret:
                    SecretStore(directory).save(secret)
                fetcher = DeferredFetcher()
                controller = self.controller(
                    directory,
                    fetcher,
                    {"fixedReference": "John 3:16", "translation": provider.upper()},
                )
                controller.refresh()
                call = fetcher.calls[-1]
                if provider == "web":
                    body = fetcher.web_body(reference="John 4:1")
                    fetcher.web_result.emit(call[1], body, "", 200)
                else:
                    body = json.dumps({
                        "canonical": "John 3:16",
                        "passages": ["[" + ("9" * 5000) + "] text"],
                    })
                    fetcher.esv_result.emit(call[1], body, "", 200)
                self.assertFalse(controller.loading)
                self.assertIn("incomplete or inconsistent", controller.errorText.lower())
                controller.deleteLater()

    def test_provider_legal_text_stays_internal(self):
        with tempfile.TemporaryDirectory() as directory:
            SecretStore(directory).save("test-esv-key")
            fetcher = FakeFetcher()
            controller = self.controller(
                directory,
                fetcher,
                {"fixedReference": "John 3:16", "translation": "ESV"},
            )
            controller.refresh()
            controller.copy_verse_text()
            copied = QGuiApplication.clipboard().text()
            self.assertIn("John 3:16", copied)
            self.assertIn("English Standard Version", copied)
            self.assertNotIn(LONG_PROVIDER_TEXT, copied)
            notification = daily_notification_body(controller.verseReference, controller.translationName)
            self.assertIn("John 3:16", notification)
            self.assertIn("English Standard Version", notification)
            self.assertNotIn(LONG_PROVIDER_TEXT, notification)
            cache_text = Path(directory, "passage-cache.json").read_text(encoding="utf-8")
            self.assertNotIn(LONG_PROVIDER_TEXT, cache_text)
            cached = json.loads(cache_text)
            self.assertEqual(cached["entries"][0]["attribution"], "")
            controller.deleteLater()

    def test_persisted_invalid_times_and_references_disable_features_with_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeFetcher()
            controller = self.controller(
                directory,
                fetcher,
                {
                    "autoOpenAt": "not-a-time",
                    "notificationTime": "99:99",
                    "notificationEnabled": True,
                    "fixedReference": "not a reference",
                },
            )
            self.assertFalse(controller._daily_timer.isActive())
            self.assertIn("invalid", controller.settingsNotice.lower())
            self.assertEqual(controller.fixedReference, "not a reference")
            controller.refresh()
            self.assertFalse(controller.loading)
            self.assertIn("reference", controller.errorText.lower())
            controller.deleteLater()

    def test_settings_hot_reload_never_broadens_invalid_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeFetcher()
            controller = self.controller(directory, fetcher, {"translation": "WEB"})
            controller._settings.setValue("bookFilter", "Not a book")
            controller._settings_watcher.poll()
            self.assertEqual(controller.settingsBookFilter, "Not a book")
            self.assertEqual(controller._filtered_pool(), [])
            self.assertIn("invalid", controller.filterError.lower())
            request_count = len(fetcher.requested)
            controller.refresh()
            self.assertEqual(len(fetcher.requested), request_count)
            self.assertIn("no references", controller.errorText.lower())
            controller._settings.setValue("bookFilter", "Genesis")
            controller._settings.setValue("topicFilter", "Hope")
            controller._settings_watcher.poll()
            self.assertEqual(controller._filtered_pool(), [])
            self.assertIn("no scripture references", controller.filterError.lower())
            controller._settings.setValue("bookFilter", "John")
            controller._settings.setValue("topicFilter", "Love")
            controller._settings_watcher.poll()
            self.assertTrue(controller._filtered_pool())
            self.assertEqual(controller.filterError, "")
            controller.deleteLater()

    def test_filters_apply_only_to_random_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeFetcher()
            controller = self.controller(
                directory,
                fetcher,
                {"bookFilter": "John", "topicFilter": "Love", "translation": "WEB"},
            )
            for _ in range(8):
                controller.refresh()
                self.assertTrue(fetcher.requested[-1][1].startswith("John "))
            controller.load_reference("Genesis 1:1")
            self.assertTrue(fetcher.requested[-1][1].startswith("Genesis 1:1"))
            controller._settings.setValue("fixedReference", "Psalm 23:1")
            controller.refresh()
            self.assertTrue(fetcher.requested[-1][1].startswith("Psalm 23:1"))
            controller.deleteLater()

    def test_daily_notification_dedupe_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime.datetime.now()
            fetcher = FakeFetcher()
            controller = self.controller(
                directory,
                fetcher,
                {
                    "notificationEnabled": True,
                    "notificationTime": now.strftime("%H:%M"),
                    "fixedReference": "John 3:16",
                    "translation": "WEB",
                },
            )
            received = []
            controller.dailyNotificationReady.connect(lambda reference, translation: received.append((reference, translation)))
            controller.start_daily_events()
            controller.check_auto_open()
            self.assertEqual(received, [("John 3:16", "World English Bible")])
            self.assertNotEqual(str(controller._settings.value("lastNotificationDay", "")), now.strftime("%Y-%m-%d"))
            controller.mark_daily_notification_delivered()
            self.assertEqual(str(controller._settings.value("lastNotificationDay")), now.strftime("%Y-%m-%d"))
            request_count = len(fetcher.requested)
            controller.check_auto_open()
            self.assertEqual(len(fetcher.requested), request_count)
            controller.deleteLater()

    def test_auto_open_commits_only_after_successful_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime.datetime.now()
            fetcher = FakeFetcher()
            fetcher.fail = True
            controller = self.controller(
                directory,
                fetcher,
                {"autoOpenAt": now.strftime("%H:%M"), "fixedReference": "John 3:16", "translation": "WEB"},
            )
            controller.start_daily_events()
            self.assertFalse(controller.overlayOpen)
            self.assertNotEqual(str(controller._settings.value("lastAutoOpenDay", "")), now.strftime("%Y-%m-%d"))
            fetcher.fail = False
            controller.check_auto_open()
            self.assertTrue(controller.overlayOpen)
            self.assertEqual(str(controller._settings.value("lastAutoOpenDay")), now.strftime("%Y-%m-%d"))
            controller.deleteLater()

    def test_daily_notification_retries_without_duplicate_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime.datetime.now()
            fetcher = FakeFetcher()
            fetcher.fail = True
            controller = self.controller(
                directory,
                fetcher,
                {
                    "notificationEnabled": True,
                    "notificationTime": now.strftime("%H:%M"),
                    "fixedReference": "John 3:16",
                    "translation": "WEB",
                },
            )
            received = []
            controller.dailyNotificationReady.connect(lambda reference, translation: received.append(reference))
            controller.start_daily_events()
            self.assertFalse(controller.loading)
            self.assertEqual(received, [])
            self.assertNotEqual(str(controller._settings.value("lastNotificationDay", "")), now.strftime("%Y-%m-%d"))
            fetcher.fail = False
            controller.check_auto_open()
            self.assertEqual(received, ["John 3:16"])
            controller.mark_daily_notification_delivered()
            request_count = len(fetcher.requested)
            controller.check_auto_open()
            self.assertEqual(len(fetcher.requested), request_count)
            controller.deleteLater()

    def test_zero_and_near_zero_animation_speed_reveal_immediately(self):
        for speed in (0, 0.001, 0.049):
            with self.subTest(speed=speed), tempfile.TemporaryDirectory() as directory:
                fetcher = FakeFetcher()
                controller = self.controller(
                    directory,
                    fetcher,
                    {
                        "fixedReference": "John 3:16",
                        "translation": "WEB",
                        "animationSpeed": speed,
                    },
                )
                controller.refresh()
                self.assertGreater(controller._reveal_total, 0)
                self.assertEqual(controller._revealed_chars, controller._reveal_total)
                self.assertFalse(controller._reveal_timer.isActive())
                controller.deleteLater()

    def test_daily_due_and_tray_routing(self):
        now = datetime.datetime(2026, 1, 2, 7, 30)
        self.assertEqual(daily_event_due("07:30", "", now), ("2026-01-02", True))
        self.assertEqual(daily_event_due("07:30", "", now + datetime.timedelta(minutes=10)), ("2026-01-02", True))
        self.assertEqual(daily_event_due("07:30", "", now + datetime.timedelta(minutes=11)), ("2026-01-02", False))
        self.assertEqual(daily_event_due("23:55", "", datetime.datetime(2026, 1, 3, 0, 5)), ("2026-01-02", True))
        self.assertEqual(daily_event_due("07:30", "2026-01-02", now), ("2026-01-02", False))
        controller = mock.Mock()
        checker = mock.Mock()
        _route_tray_click(TrayNotification("daily", "John 3:16"), controller, checker)
        controller.show_daily_verse.assert_called_once_with("John 3:16")
        checker.download.assert_not_called()
        controller.reset_mock()
        _route_tray_click(TrayNotification("update", update_tag="v0.2.0"), controller, checker)
        checker.download.assert_called_once_with()

    def test_tray_router_serializes_reentrant_clicks(self):
        controller = mock.Mock()
        checker = mock.Mock()
        router = TrayNotificationRouter(controller, checker)
        controller.show_daily_verse.side_effect = lambda _reference: router.click()
        router.set_pending("daily")
        router.activate_next()
        router.click()
        controller.show_daily_verse.assert_called_once_with("")

    def test_tray_queue_serializes_exact_daily_then_update_snapshots(self):
        controller = mock.Mock()
        checker = mock.Mock()
        router = TrayNotificationRouter(controller, checker)
        snapshot = object()
        daily = router.enqueue("daily", reference="John 3:16", snapshot=snapshot)
        self.assertIs(router.activate_next(), daily)
        router.enqueue("update", update_tag="v0.2.0")
        self.assertIsNone(router.activate_next())
        router.click()
        controller.show_daily_snapshot.assert_called_once_with(snapshot)
        update = router.activate_next()
        self.assertEqual(update.update_tag, "v0.2.0")

    def test_daily_notification_click_keeps_exact_fetched_verse(self):
        with tempfile.TemporaryDirectory() as directory:
            fetcher = FakeFetcher()
            controller = self.controller(
                directory,
                fetcher,
                {"fixedReference": "John 3:16", "translation": "WEB"},
            )
            controller._fetch("John 3:16", True, notification_day="2026-01-02")
            snapshot = controller.daily_snapshot("John 3:16")
            request_count = len(fetcher.requested)
            controller._verse_text = "a later mutable verse"
            controller._verse_reference = "John 4:1"
            controller.show_daily_snapshot(snapshot)
            self.assertTrue(controller.overlayOpen)
            self.assertEqual(len(fetcher.requested), request_count)
            self.assertEqual(controller.verseReference, "John 3:16")
            self.assertEqual(controller.verseText, "[16] For God so loved the world.")
            controller.deleteLater()


if __name__ == "__main__":
    unittest.main()
