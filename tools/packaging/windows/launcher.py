"""!
@file packaging/windows/launcher.py
@brief Piccolo bootstrap a finestra compilato in Anonymizer.exe.

Avvia l'applicazione desktop con il runtime Python affiancato, dove resta tutto
lo stack di machine learning, e lega il processo figlio a un Job Object di
Windows perché termini insieme al launcher. Questo file contiene solo
docstring come documentazione perché viene compilato nell'eseguibile.
"""

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


class BasicLimits(ctypes.Structure):
    """!
    @brief Struttura JOBOBJECT_BASIC_LIMIT_INFORMATION dell'API Win32.

    I campi in `_fields_` ricalcano la definizione di Windows; serve `LimitFlags`.
    """

    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IoCounters(ctypes.Structure):
    """!
    @brief Struttura IO_COUNTERS dell'API Win32, necessaria per il layout dei limiti estesi.
    """

    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class ExtendedLimits(ctypes.Structure):
    """!
    @brief Struttura JOBOBJECT_EXTENDED_LIMIT_INFORMATION dell'API Win32.

    Passata a SetInformationJobObject per attivare la chiusura dei processi del job.
    """

    _fields_ = [
        ("BasicLimitInformation", BasicLimits),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class ProcessJob:
    """!
    @brief Job Object di Windows che termina i processi assegnati alla sua chiusura.

    Mantiene in `api` il riferimento a kernel32 con le firme delle funzioni usate
    e in `handle` l'handle del job, None dopo la chiusura.
    """

    def __init__(self):
        """!
        @brief Crea il job con il flag JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
        @throws OSError Se la creazione o la configurazione del job falliscono.
        """
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        self.api.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        self.api.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("job_create_failed")
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000
        if not self.api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.close()
            raise OSError("job_setup_failed")

    def assign(self, process):
        """!
        @brief Assegna un processo figlio al job.
        @param process Processo avviato con subprocess.Popen.
        @throws OSError Se l'assegnazione fallisce.
        """
        if not self.api.AssignProcessToJobObject(self.handle, wintypes.HANDLE(process._handle)):
            raise OSError("job_assignment_failed")

    def close(self):
        """!
        @brief Chiude l'handle del job, terminando i processi ancora assegnati.
        """
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def main():
    """!
    @brief Avvia l'applicazione desktop nel runtime affiancato e ne attende la fine.

    Ripulisce l'ambiente dalle variabili che altererebbero il runtime (Python,
    PyInstaller, Qt) e, in caso di errore, termina il figlio e mostra un messaggio.
    @return Codice di uscita dell'applicazione, oppure 1 se l'avvio non riesce.
    """
    root = Path(sys.executable).resolve().parent
    python = root / "runtime" / "pythonw.exe"
    process, job = None, None
    try:
        if not python.is_file():
            raise OSError("missing_runtime")
        job = ProcessJob()
        # The frozen bootloader's DLL directory must not leak into external CPython.
        ctypes.windll.kernel32.SetDllDirectoryW(None)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX")
            and not key.upper().startswith("_PYI_")
            and not key.upper().startswith(("QT_", "QTWEBENGINE", "QML_", "QML2_"))
        }
        process = subprocess.Popen(
            [str(python), "-I", "-B", "-m", "anonymizer.desktop", "--bundle-root", str(root)],
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        job.assign(process)
        return process.wait()
    except (OSError, ValueError):
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        ctypes.windll.user32.MessageBoxW(
            None,
            "Avvio non riuscito. Mantieni Anonymizer.exe nella cartella portable completa.",
            "Anonymizer",
            0x10,
        )
        return 1
    finally:
        if job is not None:
            job.close()


if __name__ == "__main__":
    sys.exit(main())
