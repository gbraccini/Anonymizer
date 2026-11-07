"""!
@file performance.py
@brief Budget di esecuzione prudenti ricavati dalla CPU effettiva e dalla memoria disponibile.

Tiene conto dell'affinità del processo e dei limiti dei cgroup, e decide quanti thread
assegnare a NER e OCR e se possono lavorare in parallelo.
"""

import ctypes
import os
import struct
from dataclasses import dataclass
from functools import cache
from pathlib import Path

## Numero di byte in un gibibyte.
GIB = 1024**3


@dataclass(frozen=True)
class Hardware:
    """!
    @brief Risorse effettivamente utilizzabili dal processo.
    """

    ## CPU logiche disponibili, almeno una.
    logical_cpus: int
    ## Core fisici disponibili, se determinabili.
    physical_cpus: int | None
    ## Memoria disponibile in byte, se determinabile.
    available_memory: int | None


@dataclass(frozen=True)
class ExecutionProfile:
    """!
    @brief Ripartizione dei thread tra NER e OCR.
    """

    ## CPU complessivamente assegnate all'elaborazione.
    cpu_budget: int
    ## Thread per il NER.
    ner_threads: int
    ## Thread per l'OCR.
    ocr_threads: int
    ## Se vero, NER e OCR possono procedere in parallelo.
    overlap: bool
    ## Codice che motiva la scelta del profilo.
    reason: str
    ## Profondità della coda tra le fasi; è supportato solo 1.
    queue_size: int = 1

    def __post_init__(self):
        """!
        @brief Verifica i limiti dei thread e che il parallelo rientri nel budget.
        @throws ValueError Se un valore è fuori dominio o i thread in parallelo superano
            il budget di CPU.
        """
        if (
            any(
                type(n) is not int or not 1 <= n <= 32
                for n in (self.cpu_budget, self.ner_threads, self.ocr_threads)
            )
            or self.queue_size != 1
            or type(self.overlap) is not bool
        ):
            raise ValueError("invalid_execution_profile")
        if self.overlap and self.ner_threads + self.ocr_threads > self.cpu_budget:
            raise ValueError("execution_profile_exceeds_cpu_budget")


def _windows_hardware():
    """!
    @brief Rileva le risorse su Windows tramite le API di kernel32.

    Le CPU logiche derivano dalla maschera di affinità del processo. I core fisici sono
    contati solo con un unico gruppo di processori attivo, considerando i core che
    intersecano l'affinità; altrimenti restano indeterminati.
    @return Risorse rilevate.
    @throws OSError Se la maschera di affinità non è disponibile.
    """
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessAffinityMask.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_size_t),
    )
    if not kernel.GetProcessAffinityMask(
        kernel.GetCurrentProcess(), ctypes.byref(mask), ctypes.byref(system_mask)
    ):
        raise OSError("affinity_unavailable")
    physical = None
    if kernel.GetActiveProcessorGroupCount() == 1:
        size = wintypes.DWORD()
        kernel.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))
        if 0 < size.value <= 1024 * 1024:
            buffer = ctypes.create_string_buffer(size.value)
            if kernel.GetLogicalProcessorInformationEx(0, buffer, ctypes.byref(size)):
                offset, cores = 0, 0
                while offset + 32 <= size.value:
                    relation, length = struct.unpack_from("II", buffer, offset)
                    if length < 32 or offset + length > size.value:
                        break
                    groups = struct.unpack_from("H", buffer, offset + 30)[0]
                    if (
                        relation == 0
                        and groups == 1
                        and length >= 32 + ctypes.sizeof(ctypes.c_size_t)
                    ):
                        core_mask = int.from_bytes(
                            buffer[offset + 32 : offset + 32 + ctypes.sizeof(ctypes.c_size_t)],
                            "little",
                        )
                        cores += bool(core_mask & mask.value)
                    offset += length
                if offset == size.value and cores:
                    physical = cores

    class MemoryStatus(ctypes.Structure):
        """!
        @brief Struttura `MEMORYSTATUSEX` usata da `GlobalMemoryStatusEx`.
        """

        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong)
            for name in (
                "total",
                "available",
                "total_page",
                "available_page",
                "total_virtual",
                "available_virtual",
                "extended",
            )
        ]

    memory = MemoryStatus()
    memory.length = ctypes.sizeof(memory)
    available = memory.available if kernel.GlobalMemoryStatusEx(ctypes.byref(memory)) else None
    return Hardware(max(1, mask.value.bit_count()), physical, available)


def _read_integer(path):
    """!
    @brief Legge un intero da un file di sistema.
    @param path Percorso del file.
    @return Valore letto, oppure None se il file manca o non contiene un intero.
    """
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


@cache
def probe_hardware() -> Hardware:
    """!
    @brief Rileva una sola volta le risorse disponibili al processo.

    Su Windows usa le API di sistema e, in caso di errore, ricade su una sola CPU.
    Altrove considera l'affinità, la topologia dei core e i limiti di CPU e memoria
    dei cgroup v2 o, in assenza, v1.
    @return Risorse rilevate, memorizzate per le chiamate successive.
    """
    if os.name == "nt":
        try:
            return _windows_hardware()
        except (OSError, AttributeError, ValueError):
            return Hardware(1, None, None)
    affinity = os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else None
    logical = len(affinity) if affinity else os.cpu_count() or 1
    physical = None
    if affinity:
        cores = set()
        for cpu in affinity:
            base = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
            package, core = (
                _read_integer(base / "physical_package_id"),
                _read_integer(base / "core_id"),
            )
            if package is None or core is None:
                break
            cores.add((package, core))
        else:
            physical = len(cores) or None
    try:
        available = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        available = None
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max" and int(period) > 0:
            logical = min(logical, max(1, int(quota) // int(period)))
    except (OSError, ValueError):
        quota = _read_integer("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
        period = _read_integer("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if quota and quota > 0 and period and period > 0:
            logical = min(logical, max(1, quota // period))
    maximum, current = (
        _read_integer("/sys/fs/cgroup/memory.max"),
        _read_integer("/sys/fs/cgroup/memory.current"),
    )
    if maximum is not None and current is not None:
        available = (
            min(available, max(0, maximum - current))
            if available is not None
            else max(0, maximum - current)
        )
    return Hardware(max(1, logical), physical, available)


def choose_profile(
    hardware: Hardware | None = None, *, ner_threads=None, ocr_threads=None, serial=False
):
    """!
    @brief Sceglie il profilo di esecuzione per le risorse disponibili.

    Il budget lascia libera una CPU logica, non supera i core fisici ed è al massimo 12.
    Il parallelo tra OCR e NER richiede almeno 3 CPU e 4 GiB liberi; il NER usa 8 thread
    con almeno 9 CPU e 6 GiB, altrimenti 4. Se i thread imposti esplicitamente non
    rientrano nel budget, l'esecuzione diventa seriale.
    @param hardware Risorse da considerare; se None vengono rilevate.
    @param ner_threads Thread NER imposti, da 1 a 32.
    @param ocr_threads Thread OCR imposti, da 1 a 32; altrimenti 1.
    @param serial Se vero, esclude il parallelo tra OCR e NER.
    @return Profilo di esecuzione validato.
    @throws ValueError Se un valore imposto non è un intero tra 1 e 32.
    """
    hardware = hardware or probe_hardware()
    for override in (ner_threads, ocr_threads):
        if override is not None and (type(override) is not int or not 1 <= override <= 32):
            raise ValueError("invalid_thread_override")
    budget = min(
        12, max(1, hardware.logical_cpus - 1), hardware.physical_cpus or hardware.logical_cpus
    )
    memory = hardware.available_memory or 0
    overlap = not serial and budget >= 3 and memory >= 4 * GIB
    ocr = ocr_threads if ocr_threads is not None else 1
    default = 8 if budget >= 9 and memory >= 6 * GIB else 4
    ner = (
        ner_threads
        if ner_threads is not None
        else max(1, min(default, budget - ocr if overlap else budget))
    )
    if overlap and ner + ocr > budget:
        overlap = False
        reason = "explicit_threads_require_serial_execution"
    else:
        reason = "bounded_overlap" if overlap else "conservative_serial_execution"
    return ExecutionProfile(budget, ner, ocr, overlap, reason)


def configure_ner_worker(ner):
    """!
    @brief Imposta il numero di thread di PyTorch secondo la configurazione del NER.

    Non ha effetto se il rilevatore non espone una configurazione o usa ONNX.
    @param ner Rilevatore NER, con attributo facoltativo `config`.
    """
    config = getattr(ner, "config", None)
    if config is not None and config.runtime == "torch":
        import torch

        torch.set_num_threads(config.cpu_threads)


def configure_process_startup(profile: ExecutionProfile):
    """!
    @brief Applica i limiti dei pool nativi a livello di processo.

    Va chiamata una sola volta, prima di caricare le librerie di inferenza, che leggono
    queste variabili d'ambiente all'avvio.
    @param profile Profilo da cui ricavare il numero di thread NER.
    """
    os.environ.update(
        OMP_NUM_THREADS=str(profile.ner_threads),
        OMP_THREAD_LIMIT=str(profile.ner_threads),
        MKL_NUM_THREADS=str(profile.ner_threads),
        TOKENIZERS_PARALLELISM="false",
    )
