"""Accès aux secrets Akasha dans le Gestionnaire d’identification Windows."""

import ctypes
from ctypes import wintypes
import sys
from uuid import UUID

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
SECRET_MAX_BYTES = 5 * 512
TARGET_PREFIX = "AkashaBrain/vault/"


class KeyStoreUnavailable(RuntimeError):
    pass


class SecretMissing(LookupError):
    pass


class Credential(ctypes.Structure):
    _fields_ = [
        ("flags", wintypes.DWORD),
        ("type", wintypes.DWORD),
        ("target", wintypes.LPWSTR),
        ("comment", wintypes.LPWSTR),
        ("last_written", wintypes.FILETIME),
        ("size", wintypes.DWORD),
        ("blob", ctypes.POINTER(ctypes.c_ubyte)),
        ("persistence", wintypes.DWORD),
        ("attribute_count", wintypes.DWORD),
        ("attributes", ctypes.c_void_p),
        ("target_alias", wintypes.LPWSTR),
        ("username", wintypes.LPWSTR),
    ]


class WindowsKeyStore:
    def __init__(self):
        if sys.platform != "win32":
            raise KeyStoreUnavailable("Le gestionnaire d’identification Windows est indisponible.")
        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True, winmode=0x00000800)
        self.write = api.CredWriteW
        self.write.argtypes = (ctypes.POINTER(Credential), wintypes.DWORD)
        self.write.restype = wintypes.BOOL
        self.read = api.CredReadW
        self.read.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(Credential)))
        self.read.restype = wintypes.BOOL
        self.delete = api.CredDeleteW
        self.delete.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
        self.delete.restype = wintypes.BOOL
        self.free = api.CredFree
        self.free.argtypes = (ctypes.c_void_p,)
        self.free.restype = None

    @staticmethod
    def target(handle: UUID) -> str:
        if not isinstance(handle, UUID):
            raise ValueError("Référence de secret invalide.")
        return TARGET_PREFIX + str(handle)

    def put(self, handle: UUID, secret: bytearray) -> None:
        if type(secret) is not bytearray or not 1 <= len(secret) <= SECRET_MAX_BYTES:
            raise ValueError("Taille de secret hors du périmètre accepté.")
        view = (ctypes.c_ubyte * len(secret)).from_buffer(secret)
        credential = Credential(type=CRED_TYPE_GENERIC, target=self.target(handle), size=len(secret),
                                blob=ctypes.cast(view, ctypes.POINTER(ctypes.c_ubyte)),
                                persistence=CRED_PERSIST_LOCAL_MACHINE, username="Akasha Brain")
        if not self.write(ctypes.byref(credential), 0):
            raise KeyStoreUnavailable("Windows a refusé l’enregistrement du secret.")

    def get(self, handle: UUID) -> bytearray:
        pointer = ctypes.POINTER(Credential)()
        if not self.read(self.target(handle), CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == ERROR_NOT_FOUND:
                raise SecretMissing("Secret introuvable dans Windows.")
            raise KeyStoreUnavailable("La lecture du secret a échoué dans Windows.")
        try:
            size, blob = pointer.contents.size, pointer.contents.blob
            if not 1 <= size <= SECRET_MAX_BYTES or not blob:
                raise KeyStoreUnavailable("Le secret lu ne respecte pas le format du coffre.")
            value = bytearray(size)
            ctypes.memmove((ctypes.c_ubyte * size).from_buffer(value), blob, size)
            ctypes.memset(blob, 0, size)
            return value
        finally:
            self.free(pointer)

    def erase(self, handle: UUID) -> None:
        if not self.delete(self.target(handle), CRED_TYPE_GENERIC, 0) and ctypes.get_last_error() != ERROR_NOT_FOUND:
            raise KeyStoreUnavailable("Windows a refusé l’effacement du secret.")
