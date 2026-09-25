import ctypes
import os
import secrets
import stat
import tempfile
from ctypes import wintypes
from pathlib import Path

_DACL_SECURITY_INFORMATION = 0x00000004
_OWNER_SECURITY_INFORMATION = 0x00000001
_PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
_SDDL_REVISION_1 = 1
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_ERROR_INSUFFICIENT_BUFFER = 122
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_READ_CONTROL = 0x00020000
_WRITE_DAC = 0x00040000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_CREATE_NEW = 1
_CREATE_ALWAYS = 2
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_TEMPORARY = 0x00000100
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_SE_FILE_OBJECT = 1
_SE_DACL_PROTECTED = 0x00001000
_ACCESS_ALLOWED_ACE_TYPE = 0x0000
_FILE_ALL_ACCESS = 0x001F01FF
_ACL_SIZE_INFORMATION_CLASS = 2
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class TOKEN_USER_STRUCT(ctypes.Structure):
    _fields_ = [("Sid", ctypes.POINTER(ctypes.c_ubyte)), ("Attributes", wintypes.DWORD)]


class BY_HANDLE_FILE_INFORMATION_STRUCT(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class ACL_SIZE_INFORMATION_STRUCT(ctypes.Structure):
    _fields_ = [
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    ]


class ACCESS_ALLOWED_ACE_STRUCT(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", wintypes.WORD),
        ("Mask", wintypes.DWORD),
        ("SidStart", ctypes.c_size_t),
    ]


def windows_system_library(name: str):
    if os.name != "nt":
        return None
    library_name = os.path.basename(str(name or ""))
    if not library_name or library_name in {".", ".."} or library_name != str(name or ""):
        raise OSError("invalid Windows system library name")
    kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    get_system_directory = kernel32.GetSystemDirectoryW
    get_system_directory.argtypes = [wintypes.LPWSTR, wintypes.DWORD]
    get_system_directory.restype = wintypes.DWORD
    required = get_system_directory(None, 0)
    if not required or required > 32767:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(required + 1)
    length = get_system_directory(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    return ctypes.WinDLL(str(Path(buffer.value) / library_name), use_last_error=True)


def _validated_path(path: str) -> str:
    target = os.path.abspath(str(path or ""))
    if not target or len(target) > 32767 or any(ord(char) < 32 for char in target):
        raise OSError("invalid protected path")
    return target


def _current_user_sid():
    advapi32 = windows_system_library("advapi32.dll")
    kernel32 = windows_system_library("kernel32.dll")
    open_process_token = advapi32.OpenProcessToken
    open_process_token.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    open_process_token.restype = wintypes.BOOL
    get_token_information = advapi32.GetTokenInformation
    get_token_information.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    get_token_information.restype = wintypes.BOOL
    convert_sid = advapi32.ConvertSidToStringSidW
    convert_sid.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    convert_sid.restype = wintypes.BOOL
    get_length_sid = advapi32.GetLengthSid
    get_length_sid.argtypes = [ctypes.c_void_p]
    get_length_sid.restype = wintypes.DWORD
    copy_sid = advapi32.CopySid
    copy_sid.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    copy_sid.restype = wintypes.BOOL
    local_alloc = kernel32.LocalAlloc
    local_alloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    local_alloc.restype = ctypes.c_void_p
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = wintypes.HANDLE
    token = wintypes.HANDLE()
    sid_text = wintypes.LPWSTR()
    sid_copy = ctypes.c_void_p()
    token_buffer = None
    try:
        if not open_process_token(get_current_process(), _TOKEN_QUERY, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        size = wintypes.DWORD()
        get_token_information(token, _TOKEN_USER, None, 0, ctypes.byref(size))
        if size.value <= 0 or ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER:
            raise ctypes.WinError(ctypes.get_last_error())
        token_buffer = ctypes.create_string_buffer(size.value)
        if not get_token_information(token, _TOKEN_USER, token_buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        user = ctypes.cast(token_buffer, ctypes.POINTER(TOKEN_USER_STRUCT)).contents
        source_sid = ctypes.cast(user.Sid, ctypes.c_void_p)
        sid_length = get_length_sid(source_sid)
        if not sid_length:
            raise ctypes.WinError(ctypes.get_last_error())
        if not convert_sid(source_sid, ctypes.byref(sid_text)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid_copy = local_alloc(0x0040, sid_length)
        if not sid_copy:
            raise ctypes.WinError(ctypes.get_last_error())
        if not copy_sid(sid_length, sid_copy, source_sid):
            raise ctypes.WinError(ctypes.get_last_error())
        value = sid_copy
        sid_copy = ctypes.c_void_p()
        return advapi32, kernel32, token, value, sid_text, local_free, close_handle
    except Exception:
        error = ctypes.get_last_error()
        if sid_copy:
            local_free(sid_copy)
        if sid_text:
            local_free(sid_text)
        if token.value:
            close_handle(token)
        if error:
            raise ctypes.WinError(error)
        raise


def _owner_only_descriptor():
    advapi32, _kernel32, token, sid, sid_text_pointer, local_free, close_handle = _current_user_sid()
    descriptor = ctypes.c_void_p()
    try:
        convert_descriptor = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert_descriptor.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        convert_descriptor.restype = wintypes.BOOL
        sddl = "D:P(A;;FA;;;%s)" % sid_text_pointer.value
        if not convert_descriptor(sddl, _SDDL_REVISION_1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        value = descriptor
        descriptor = ctypes.c_void_p()
        return advapi32, value, local_free
    finally:
        if descriptor:
            local_free(descriptor)
        if sid:
            local_free(sid)
        if sid_text_pointer:
            local_free(sid_text_pointer)
        if token.value:
            close_handle(token)


def _descriptor_owner_only_valid(descriptor, owner, dacl, expected_sid) -> bool:
    if not descriptor or not owner or not dacl or not expected_sid:
        return False
    advapi32 = windows_system_library("advapi32.dll")
    get_owner = advapi32.GetSecurityDescriptorOwner
    get_owner.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    get_owner.restype = wintypes.BOOL
    get_dacl = advapi32.GetSecurityDescriptorDacl
    get_dacl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.BOOL),
    ]
    get_dacl.restype = wintypes.BOOL
    get_control = advapi32.GetSecurityDescriptorControl
    get_control.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    get_control.restype = wintypes.BOOL
    get_acl_info = advapi32.GetAclInformation
    get_acl_info.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int]
    get_acl_info.restype = wintypes.BOOL
    get_ace = advapi32.GetAce
    get_ace.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    get_ace.restype = wintypes.BOOL
    equal_sid = advapi32.EqualSid
    equal_sid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    equal_sid.restype = wintypes.BOOL
    descriptor_owner = ctypes.c_void_p()
    owner_defaulted = wintypes.BOOL()
    if not get_owner(descriptor, ctypes.byref(descriptor_owner), ctypes.byref(owner_defaulted)):
        return False
    if not descriptor_owner or owner_defaulted.value:
        return False
    control = wintypes.WORD()
    revision = wintypes.DWORD()
    if not get_control(descriptor, ctypes.byref(control), ctypes.byref(revision)) or not control.value & _SE_DACL_PROTECTED:
        return False
    dacl_present = wintypes.BOOL()
    dacl_defaulted = wintypes.BOOL()
    dacl_pointer = ctypes.c_void_p()
    if not get_dacl(descriptor, ctypes.byref(dacl_present), ctypes.byref(dacl_pointer), ctypes.byref(dacl_defaulted)):
        return False
    if not dacl_present.value or dacl_defaulted.value or not dacl_pointer:
        return False
    acl_size = ACL_SIZE_INFORMATION_STRUCT()
    if not get_acl_info(
        dacl_pointer,
        ctypes.byref(acl_size),
        ctypes.sizeof(acl_size),
        _ACL_SIZE_INFORMATION_CLASS,
    ) or acl_size.AceCount != 1:
        return False
    ace_pointer = ctypes.c_void_p()
    if not get_ace(dacl_pointer, 0, ctypes.byref(ace_pointer)) or not ace_pointer:
        return False
    ace = ctypes.cast(ace_pointer, ctypes.POINTER(ACCESS_ALLOWED_ACE_STRUCT)).contents
    if ace.AceType != _ACCESS_ALLOWED_ACE_TYPE or ace.AceFlags != 0 or ace.Mask != _FILE_ALL_ACCESS:
        return False
    ace_sid = ctypes.cast(ctypes.byref(ace, ACCESS_ALLOWED_ACE_STRUCT.SidStart.offset), ctypes.c_void_p)
    return bool(equal_sid(ace_sid, expected_sid))


def _windows_handle_path(path: str):
    kernel32 = windows_system_library("kernel32.dll")
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    get_info = kernel32.GetFileInformationByHandle
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION_STRUCT)]
    get_info.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        _validated_path(path),
        _READ_CONTROL | _WRITE_DAC,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE or not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    info = BY_HANDLE_FILE_INFORMATION_STRUCT()
    if not get_info(handle, ctypes.byref(info)) or info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        error = ctypes.get_last_error()
        close_handle(handle)
        raise ctypes.WinError(error)
    return handle, info, close_handle


def _windows_security_info(handle: int, named_path: str = ""):
    advapi32 = windows_system_library("advapi32.dll")
    kernel32 = windows_system_library("kernel32.dll")
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    get_security_info = advapi32.GetSecurityInfo
    get_security_info.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_security_info.restype = wintypes.DWORD
    get_named_security_info = advapi32.GetNamedSecurityInfoW
    get_named_security_info.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_named_security_info.restype = wintypes.DWORD
    owner = ctypes.c_void_p()
    group = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    sacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    if named_path:
        status = get_named_security_info(
            _validated_path(named_path),
            _SE_FILE_OBJECT,
            _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            ctypes.byref(owner),
            ctypes.byref(group),
            ctypes.byref(dacl),
            ctypes.byref(sacl),
            ctypes.byref(descriptor),
        )
    else:
        status = get_security_info(
            wintypes.HANDLE(handle),
            _SE_FILE_OBJECT,
            _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            ctypes.byref(owner),
            ctypes.byref(group),
            ctypes.byref(dacl),
            ctypes.byref(sacl),
            ctypes.byref(descriptor),
        )
    return status, owner, dacl, descriptor, local_free


def _restrict_handle_windows(handle: int) -> None:
    advapi32, descriptor, local_free = _owner_only_descriptor()
    try:
        get_dacl = advapi32.GetSecurityDescriptorDacl
        get_dacl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.BOOL),
        ]
        get_dacl.restype = wintypes.BOOL
        set_security_info = advapi32.SetSecurityInfo
        set_security_info.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        set_security_info.restype = wintypes.DWORD
        present = wintypes.BOOL()
        dacl = ctypes.c_void_p()
        defaulted = wintypes.BOOL()
        if not get_dacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)) or not present.value or not dacl:
            raise ctypes.WinError(ctypes.get_last_error())
        status = set_security_info(
            wintypes.HANDLE(handle),
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            dacl,
            None,
        )
        if status != 0:
            raise ctypes.WinError(status)
    finally:
        if descriptor:
            local_free(descriptor)


def _windows_native_handle(handle: int) -> int:
    if os.name != "nt":
        raise OSError("Windows handles are unavailable")
    import msvcrt

    native_handle = msvcrt.get_osfhandle(int(handle))
    if native_handle == -1:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(native_handle)


def restrict_handle_owner_only(handle: int) -> None:
    if os.name != "nt":
        os.fchmod(int(handle), stat.S_IRUSR | stat.S_IWUSR)
        return
    try:
        _restrict_handle_windows(_windows_native_handle(handle))
    except (AttributeError, TypeError, ValueError, ctypes.ArgumentError) as exc:
        raise OSError("could not apply owner-only handle permissions") from exc


def restrict_owner_only(path: str, directory: bool = False) -> None:
    target = _validated_path(path)
    if os.name != "nt":
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        if directory:
            flags |= getattr(os, "O_DIRECTORY", 0)
        fd = os.open(target, flags)
        try:
            os.fchmod(fd, stat.S_IRWXU if directory else stat.S_IRUSR | stat.S_IWUSR)
        finally:
            os.close(fd)
        return
    handle, _info, close_handle = _windows_handle_path(target)
    try:
        _restrict_handle_windows(handle)
    finally:
        close_handle(handle)


def owner_only_handle_valid(handle: int) -> bool:
    if os.name != "nt":
        try:
            info = os.fstat(int(handle))
        except OSError:
            return False
        return stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o077
    try:
        native_handle = _windows_native_handle(handle)
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        return False
    status, owner, dacl, descriptor, descriptor_free = _windows_security_info(native_handle)
    current = None
    try:
        current = _current_user_sid()
        _advapi32, _kernel32, token, sid, sid_text, local_free, close_handle = current
        return status == 0 and _descriptor_owner_only_valid(descriptor, owner, dacl, sid)
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        return False
    finally:
        if current is not None:
            _advapi32, _kernel32, token, sid, sid_text, local_free, close_handle = current
            if token.value:
                close_handle(token)
            if sid:
                local_free(sid)
            if sid_text:
                local_free(sid_text)
        if descriptor:
            descriptor_free(descriptor)


def owner_only_dacl_valid(path: str) -> bool:
    target = _validated_path(path)
    if os.name != "nt":
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(target, flags)
        except OSError:
            return False
        try:
            return owner_only_handle_valid(fd)
        finally:
            os.close(fd)
    try:
        handle, _info, close_handle = _windows_handle_path(target)
        try:
            return owner_only_handle_valid(handle)
        finally:
            close_handle(handle)
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        return False


def _validate_private_directory_fd(fd: int) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise OSError("private directory validation failed")


def create_owner_only_directory(path: str) -> str:
    target = _validated_path(path)
    missing = []
    cursor = target
    while True:
        try:
            existing = os.lstat(cursor)
            attributes = getattr(existing, "st_file_attributes", 0)
            if stat.S_ISLNK(existing.st_mode) or attributes & _FILE_ATTRIBUTE_REPARSE_POINT or not stat.S_ISDIR(existing.st_mode):
                raise OSError("private directory path contains a link or non-directory")
            break
        except FileNotFoundError:
            missing.append(cursor)
            parent = os.path.dirname(cursor)
            if not parent or parent == cursor:
                raise OSError("could not resolve private directory parent")
            cursor = parent
        except OSError as exc:
            raise OSError("could not inspect private directory parent") from exc
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise OSError("could not create private directory") from exc
        restrict_owner_only(directory, directory=True)
    restrict_owner_only(target, directory=True)
    if os.name != "nt":
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(target, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise OSError("private directory validation failed")
        finally:
            os.close(fd)
    elif not owner_only_dacl_valid(target):
        raise OSError("private directory validation failed")
    return target


def windows_handle_identity(handle: int) -> tuple:
    if os.name != "nt":
        raise OSError("Windows handle identity is unavailable")
    kernel32 = windows_system_library("kernel32.dll")
    get_info = kernel32.GetFileInformationByHandle
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION_STRUCT)]
    get_info.restype = wintypes.BOOL
    info = BY_HANDLE_FILE_INFORMATION_STRUCT()
    if not get_info(wintypes.HANDLE(handle), ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    if info.dwFileAttributes & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT):
        raise OSError("handle does not reference a regular file")
    return (
        "windows",
        info.dwVolumeSerialNumber,
        info.nFileIndexHigh,
        info.nFileIndexLow,
    )


def descriptor_identity(fd: int) -> tuple:
    if os.name != "nt":
        info = os.fstat(fd)
        return "posix", info.st_dev, info.st_ino, info.st_mode, info.st_uid
    import msvcrt

    handle = msvcrt.get_osfhandle(fd)
    kernel32 = windows_system_library("kernel32.dll")
    get_info = kernel32.GetFileInformationByHandle
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION_STRUCT)]
    get_info.restype = wintypes.BOOL
    info = BY_HANDLE_FILE_INFORMATION_STRUCT()
    if not get_info(wintypes.HANDLE(handle), ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    if info.dwFileAttributes & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT):
        raise OSError("cache path is not a regular file")
    return (
        "windows",
        info.dwVolumeSerialNumber,
        info.nFileIndexHigh,
        info.nFileIndexLow,
    )


def open_file_no_follow(path: str, flags: int = os.O_RDONLY) -> int:
    target = _validated_path(path)
    if os.name != "nt":
        return os.open(target, flags | getattr(os, "O_NOFOLLOW", 0))
    import msvcrt

    kernel32 = windows_system_library("kernel32.dll")
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    access = _GENERIC_READ
    if flags & os.O_WRONLY:
        access = _GENERIC_WRITE
    if flags & os.O_RDWR:
        access = _GENERIC_READ | _GENERIC_WRITE
    handle = create_file(
        target,
        access,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE or not handle:
        error = ctypes.get_last_error()
        if error in {2, 3}:
            raise FileNotFoundError(error, os.strerror(error), target)
        raise ctypes.WinError(error)
    try:
        return msvcrt.open_osfhandle(handle, flags | getattr(os, "O_BINARY", 0))
    except Exception:
        kernel32.CloseHandle(handle)
        raise


def secure_replace(temp_path: str, destination: str, expected_identity: tuple, directory: str) -> None:
    fd = open_file_no_follow(temp_path, os.O_RDONLY)
    try:
        if descriptor_identity(fd) != expected_identity or not owner_only_handle_valid(fd):
            raise OSError("temporary file identity or permissions changed")
    finally:
        os.close(fd)
    os.replace(temp_path, destination)
    fd = open_file_no_follow(destination, os.O_RDONLY)
    try:
        if descriptor_identity(fd) != expected_identity or not owner_only_handle_valid(fd):
            raise OSError("committed file identity or permissions changed")
    finally:
        os.close(fd)
    fsync_directory(directory)


def secure_atomic_write_bytes(destination: str, data: bytes) -> str:
    target = _validated_path(destination)
    payload = bytes(data)
    if not payload or len(payload) > 64 * 1024 * 1024:
        raise OSError("secure atomic payload is invalid")
    parent = os.path.dirname(target)
    if not parent or not os.path.isdir(parent):
        raise OSError("secure atomic parent is unavailable")
    try:
        existing = os.lstat(target)
    except FileNotFoundError:
        existing = None
    except OSError as exc:
        raise OSError("could not inspect secure atomic destination") from exc
    if existing is not None:
        attributes = getattr(existing, "st_file_attributes", 0)
        if stat.S_ISLNK(existing.st_mode) or attributes & _FILE_ATTRIBUTE_REPARSE_POINT or stat.S_ISDIR(existing.st_mode):
            raise OSError("secure atomic destination is unavailable")
    if os.name != "nt":
        fd = -1
        temp_path = ""
        try:
            fd, temp_path = tempfile.mkstemp(prefix=".secure-write.", suffix=".tmp", dir=parent)
            restrict_handle_owner_only(fd)
            identity = descriptor_identity(fd)
            buffer = memoryview(payload)
            while buffer:
                written = os.write(fd, buffer)
                if written <= 0:
                    raise OSError("secure atomic write failed")
                buffer = buffer[written:]
            os.fsync(fd)
            os.close(fd)
            fd = -1
            secure_replace(temp_path, target, identity, parent)
            temp_path = ""
        finally:
            if fd >= 0:
                os.close(fd)
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
        return target
    kernel32 = windows_system_library("kernel32.dll")
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    write_file = kernel32.WriteFile
    write_file.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    write_file.restype = wintypes.BOOL
    flush = kernel32.FlushFileBuffers
    flush.argtypes = [wintypes.HANDLE]
    flush.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = None
    temp_path = ""
    for _attempt in range(32):
        candidate = os.path.join(parent, ".secure-write-%s.tmp" % secrets.token_hex(16))
        handle = create_file(
            candidate,
            _GENERIC_READ | _GENERIC_WRITE | _READ_CONTROL | _WRITE_DAC,
            0,
            None,
            _CREATE_NEW,
            _FILE_ATTRIBUTE_TEMPORARY,
            None,
        )
        if handle != _INVALID_HANDLE_VALUE and handle:
            temp_path = candidate
            break
        error = ctypes.get_last_error()
        if error not in {80, 183}:
            raise ctypes.WinError(error)
    if handle is None or handle == _INVALID_HANDLE_VALUE:
        raise OSError("could not create a secure temporary file")
    try:
        _restrict_handle_windows(int(handle))
        identity = windows_handle_identity(int(handle))
        buffer = ctypes.create_string_buffer(payload, len(payload))
        offset = 0
        while offset < len(payload):
            written = wintypes.DWORD()
            if not write_file(
                wintypes.HANDLE(handle),
                ctypes.byref(buffer, offset),
                len(payload) - offset,
                ctypes.byref(written),
                None,
            ) or written.value <= 0:
                raise ctypes.WinError(ctypes.get_last_error())
            offset += written.value
        if not flush(wintypes.HANDLE(handle)):
            raise ctypes.WinError(ctypes.get_last_error())
    except Exception:
        try:
            close_handle(handle)
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise
    else:
        close_handle(handle)
    try:
        os.replace(temp_path, target)
        temp_path = ""
        fd = open_file_no_follow(target, os.O_RDONLY)
        try:
            if descriptor_identity(fd) != identity or not owner_only_handle_valid(fd):
                raise OSError("committed secure file identity or permissions changed")
        finally:
            os.close(fd)
        fsync_directory(parent)
    except OSError:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise
    return target


def fsync_directory(path: str) -> None:
    target = _validated_path(path)
    if os.name != "nt":
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(target, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return
    kernel32 = windows_system_library("kernel32.dll")
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    flush = kernel32.FlushFileBuffers
    flush.argtypes = [wintypes.HANDLE]
    flush.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    get_info = kernel32.GetFileInformationByHandle
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION_STRUCT)]
    get_info.restype = wintypes.BOOL
    handle = create_file(
        target,
        _GENERIC_READ | _GENERIC_WRITE,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE or not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = BY_HANDLE_FILE_INFORMATION_STRUCT()
        if not get_info(handle, ctypes.byref(info)) or not info.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY or info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise ctypes.WinError(ctypes.get_last_error())
        if not flush(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close_handle(handle)
