"""Per-execution integrity receipts; metadata changes always require fresh hashes.

No receipt is persisted. Read leases prevent concurrent content writes/deletes;
ChangeTime and directory membership detect metadata changes and new artifacts.
Unsupported platforms retain full verification rather than allowing a cache hit.
"""
from contextvars import ContextVar
from functools import wraps
import os
from pathlib import Path
import stat


receipts = ContextVar('knowledge_verification_receipts', default=None)
supports_read_leases = os.name == 'nt'


def verified_execution(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        cache = {}
        token = receipts.set(cache)
        try:
            return function(*args, **kwargs)
        finally:
            for _, lease in cache.values():
                lease.close()
            receipts.reset(token)
    return wrapped


if os.name == 'nt':
    import ctypes
    import struct
    from ctypes import wintypes

    class _BasicInfo(ctypes.Structure):
        _fields_ = [(name, ctypes.c_longlong) for name in
                    ('CreationTime', 'LastAccessTime', 'LastWriteTime', 'ChangeTime')]
        _fields_ += [('FileAttributes', wintypes.DWORD)]

    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _open = _kernel.CreateFileW
    _open.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _open.restype = wintypes.HANDLE
    _info = _kernel.GetFileInformationByHandleEx
    _info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _info.restype = wintypes.BOOL
    _close = _kernel.CloseHandle
    _close.argtypes = [wintypes.HANDLE]
    _close.restype = wintypes.BOOL

    class ReadLease:
        """Keep verified file bytes immutable until the execution ends.

        FILE_SHARE_READ permits other readers, but denies writers and replacement.
        Acquire before hashing, so an already open writer also rejects reuse.
        Directory enumeration alone can report stale times for open writers.
        """
        def __init__(self, observed):
            self.handles = []
            try:
                for name, signature in observed.items():
                    if signature is None or signature[0] == 'directory':
                        continue
                    handle = _open(name, 0x80000000, 1, None, 3, 0x02000000, None)
                    if handle == wintypes.HANDLE(-1).value:
                        raise ctypes.WinError(ctypes.get_last_error())
                    self.handles.append(handle)
            except BaseException:
                self.close()
                raise

        def close(self):
            for handle in self.handles:
                _close(handle)
            self.handles.clear()

    def _change_time(path):
        handle = _open(str(path), 0x80, 7, None, 3, 0x02000000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            value = _BasicInfo()
            if not _info(handle, 0, ctypes.byref(value), ctypes.sizeof(value)):
                raise ctypes.WinError(ctypes.get_last_error())
            return value.ChangeTime
        finally:
            _close(handle)

    def _directory_entries(path):
        """Bulk NTFS metadata, including ChangeTime and 128-bit file identity.

        FILE_ID_EXTD_DIR_INFO layout (Windows 8+):
        https://learn.microsoft.com/windows/win32/api/winbase/ns-winbase-file_id_extd_dir_info
        """
        handle = _open(str(path), 1, 7, None, 3, 0x02000000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            buffer = ctypes.create_string_buffer(65536)
            while _info(handle, 19, buffer, len(buffer)):
                offset = 0
                while True:
                    row = struct.unpack_from('<II6q4I16s', buffer, offset)
                    name = ctypes.string_at(ctypes.addressof(buffer) + offset + 88, row[9]).decode('utf-16-le')
                    if name not in ('.', '..'):
                        attributes = row[8]
                        signature = (row[12], attributes, row[6], row[4], row[5])
                        yield name, attributes, signature
                    if not row[0]:
                        break
                    offset += row[0]
            error = ctypes.get_last_error()
            if error != 18:  # ERROR_NO_MORE_FILES; other errors cannot produce a receipt.
                raise ctypes.WinError(error)
        finally:
            _close(handle)
else:
    def _change_time(path):
        return path.stat().st_ctime_ns


def snapshot(paths):
    """Observe names, identities and write metadata without reading artifact bytes."""
    rows = {}

    def visit(path, observed=None, attributes=None):
        path = Path(path)
        name = str(path)
        if name in rows:
            return
        if observed is None:
            try:
                st = path.lstat()
            except FileNotFoundError:
                rows[name] = None
                return
            attributes = getattr(st, 'st_file_attributes', 0)
            if stat.S_ISLNK(st.st_mode) or attributes & 0x400:
                raise ValueError('Integrity receipt cannot follow links: ' + name)
            directory = stat.S_ISDIR(st.st_mode)
            observed = (('directory', st.st_dev, st.st_ino) if directory else
                        (st.st_dev, st.st_ino, st.st_mode, st.st_size,
                         st.st_mtime_ns, _change_time(path)))
        else:
            if attributes & 0x400:
                raise ValueError('Integrity receipt cannot follow links: ' + name)
            directory = bool(attributes & 0x10)
            if directory:
                observed = ('directory', observed[0])
        rows[name] = observed
        if directory:
            if os.name == 'nt':
                for child, child_attributes, signature in _directory_entries(path):
                    visit(path / child, signature, child_attributes)
            else:
                with os.scandir(path) as entries:
                    for entry in entries:
                        visit(Path(entry.path))

    for path in paths:
        visit(path)
    return rows
