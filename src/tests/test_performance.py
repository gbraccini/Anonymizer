import pytest

from anonymizer.performance import GIB, ExecutionProfile, Hardware, choose_profile


@pytest.mark.parametrize(
    "hardware,expected",
    [
        (Hardware(2, 2, 8 * GIB), (1, 1, False)),
        (Hardware(4, 2, 8 * GIB), (2, 2, False)),
        (Hardware(8, 4, 8 * GIB), (4, 3, True)),
        (Hardware(22, 16, 8 * GIB), (12, 8, True)),
        (Hardware(22, 16, 3 * GIB), (12, 4, False)),
        (Hardware(22, None, None), (12, 4, False)),
    ],
)
def test_conservative_profiles_use_effective_cpu_and_current_memory(hardware, expected):
    profile = choose_profile(hardware)
    assert (profile.cpu_budget, profile.ner_threads, profile.overlap) == expected
    assert profile.ocr_threads == 1 and profile.queue_size == 1
    if profile.overlap:
        assert profile.ner_threads + profile.ocr_threads <= profile.cpu_budget


def test_explicit_overrides_are_kept_and_cannot_oversubscribe_overlap():
    hardware = Hardware(4, 4, 8 * GIB)
    profile = choose_profile(hardware, ner_threads=8, ocr_threads=2)
    assert (profile.ner_threads, profile.ocr_threads, profile.overlap) == (8, 2, False)
    assert "explicit" in profile.reason
    assert not choose_profile(Hardware(22, 16, 8 * GIB), serial=True).overlap


@pytest.mark.parametrize("threads", [0, 33, True, 1.5])
def test_invalid_thread_overrides_fail_explicitly(threads):
    with pytest.raises(ValueError):
        choose_profile(Hardware(4, 4, 8 * GIB), ner_threads=threads)
    with pytest.raises(ValueError):
        choose_profile(Hardware(4, 4, 8 * GIB), ocr_threads=threads)


def test_invalid_overlap_budget_is_not_a_valid_profile():
    with pytest.raises(ValueError):
        ExecutionProfile(3, 3, 1, True, "invalid")


@pytest.mark.parametrize("quota,expected", [("max 100000", 4), ("150000 100000", 1)])
def test_probe_respects_affinity_and_container_quota(monkeypatch, quota, expected):
    from types import SimpleNamespace

    import anonymizer.performance as performance

    def read_text(path, *args, **kwargs):
        name = str(path).replace("\\", "/")
        if name.endswith("cpu.max"):
            return quota
        if name.endswith("memory.max"):
            return str(4 * GIB)
        if name.endswith("memory.current"):
            return str(GIB)
        raise OSError("unavailable")

    monkeypatch.setattr(
        performance,
        "os",
        SimpleNamespace(
            name="posix",
            sched_getaffinity=lambda pid: {2, 3, 6, 7},
            cpu_count=lambda: 64,
            sysconf=lambda name: 8 * GIB if name == "SC_AVPHYS_PAGES" else 1,
        ),
    )
    monkeypatch.setattr(performance.Path, "read_text", read_text)
    performance.probe_hardware.cache_clear()
    try:
        hardware = performance.probe_hardware()
        assert hardware == Hardware(expected, None, 3 * GIB)
        assert not choose_profile(hardware).overlap
    finally:
        performance.probe_hardware.cache_clear()


def test_probe_failure_uses_safe_serial_fallback(monkeypatch):
    from types import SimpleNamespace

    import anonymizer.performance as performance

    monkeypatch.setattr(performance, "os", SimpleNamespace(name="nt"))

    def failed_probe():
        raise OSError("unavailable")

    monkeypatch.setattr(performance, "_windows_hardware", failed_probe)
    performance.probe_hardware.cache_clear()
    try:
        hardware = performance.probe_hardware()
        assert hardware == Hardware(1, None, None)
        profile = choose_profile(hardware)
        assert (profile.ner_threads, profile.ocr_threads, profile.overlap) == (1, 1, False)
    finally:
        performance.probe_hardware.cache_clear()



def test_cli_startup_sets_native_pool_limits_once_before_model_import(monkeypatch):
    import argparse
    import os

    from anonymizer.cli import _execution_profile, _ner_options

    parser = argparse.ArgumentParser()
    _ner_options(parser)
    args = parser.parse_args(["--ner-threads", "3", "--ocr-threads", "1"])
    monkeypatch.setattr(
        "anonymizer.performance.probe_hardware", lambda: Hardware(8, 4, 8 * GIB)
    )
    for key in ("OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "MKL_NUM_THREADS"):
        monkeypatch.setenv(key, "9")
    monkeypatch.setenv("TOKENIZERS_PARALLELISM", "true")
    profile = _execution_profile(args)
    assert profile.ner_threads == 3
    assert all(
        os.environ[key] == "3"
        for key in ("OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "MKL_NUM_THREADS")
    )
    assert os.environ["TOKENIZERS_PARALLELISM"] == "false"
    monkeypatch.setenv("OMP_NUM_THREADS", "2")
    assert _execution_profile(args) is profile
    assert os.environ["OMP_NUM_THREADS"] == "2"
