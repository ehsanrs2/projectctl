"""P3f tests: no actual hypervisor, VM, or custody proof."""
from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import p3f_host_capability_probe as p3f


@pytest.mark.parametrize("args", [[], ["--help"], ["--inspect-current-host-readonly", "--extra"], ["--candidate-dir", "/tmp"]])
def test_exact_opt_in_only(monkeypatch, capsys, args):
    monkeypatch.setattr(p3f, "observe", lambda: pytest.fail("must not probe"))
    assert p3f.main(args) == 2
    assert capsys.readouterr().err.strip() == "P3F_HOST_PROBE_REFUSED"


@pytest.mark.parametrize("ids", [(0, 0, 0, 0), (1000, 0, 1000, 1000), (1000, 1000, 1000, 0)])
def test_root_or_setid_refused(monkeypatch, capsys, ids):
    for name, val in zip(("getuid", "geteuid", "getgid", "getegid"), ids):
        monkeypatch.setattr(p3f.os, name, lambda v=val: v)
    monkeypatch.setattr(p3f, "observe", lambda: pytest.fail("no reads"))
    assert p3f.main([p3f._ACK]) == 2
    assert capsys.readouterr().err.strip() == "P3F_HOST_PROBE_REFUSED"


@pytest.mark.parametrize("raw,expected", [
    (b"processor: 0\nflags: fpu vmx sse\n", "VMX_SVM_CPU_FLAG_HINT"),
    (b"Features : aes svm neon\n", "VMX_SVM_CPU_FLAG_HINT"),
    (b"flags : vmexit pseudo_svm2\n", "NO_VMX_SVM_FLAG_OBSERVED"),
    (b"model name : vmx svm\n", "NO_VMX_SVM_FLAG_OBSERVED"),
    (b"flags: sse sse2\n", "NO_VMX_SVM_FLAG_OBSERVED"),
    (b"", "CPUINFO_UNKNOWN"),
])
def test_cpu_fixed_read_parse(monkeypatch, raw, expected):
    class Reader:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size):
            assert size == p3f._CPUINFO_LIMIT + 1
            return raw
    monkeypatch.setattr(p3f.Path, "open", lambda self, mode: Reader())
    assert p3f._cpu_hint() == expected


def test_oversized_cpuinfo_refused(monkeypatch):
    class Reader:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size): return b"flags : vmx\n" + b"x" * size
    monkeypatch.setattr(p3f.Path, "open", lambda self, mode: Reader())
    assert p3f._cpu_hint() == "CPUINFO_UNKNOWN"


@pytest.mark.parametrize("mode,accessible,expected", [
    (stat.S_IFCHR, True, "KVM_DEVICE_DAC_ACCESS_HINT"),
    (stat.S_IFCHR, False, "KVM_DEVICE_NO_DAC_ACCESS_HINT"),
    (stat.S_IFLNK, True, "KVM_DEVICE_UNEXPECTED_FILE_TYPE"),
    (stat.S_IFREG, True, "KVM_DEVICE_UNEXPECTED_FILE_TYPE"),
])
def test_kvm_is_never_opened(monkeypatch, mode, accessible, expected):
    monkeypatch.setattr(p3f.os, "lstat", lambda path: SimpleNamespace(st_mode=mode))
    monkeypatch.setattr(p3f.os, "access", lambda path, mask: accessible)
    assert p3f._kvm_hint() == expected


def test_missing_kvm_does_not_throw(monkeypatch):
    def missing(path): raise FileNotFoundError(path)
    monkeypatch.setattr(p3f.os, "lstat", missing)
    assert p3f._kvm_hint() == "KVM_DEVICE_NOT_OBSERVED"


def test_tools_are_only_stat_hints(monkeypatch):
    def hinted(path):
        return SimpleNamespace(st_mode=stat.S_IFLNK if "virsh" in path else stat.S_IFDIR)
    monkeypatch.setattr(p3f.os, "lstat", hinted)
    result = p3f._binary_hints()
    assert result["libvirt_virsh"] == "FILE_OR_SYMLINK_HINT"
    assert result["virtualbox"] == "NOT_OBSERVED"
    assert len(result) == 5


def test_all_outputs_are_fixed_and_deny_permissions(monkeypatch):
    monkeypatch.setattr(p3f, "_cpu_hint", lambda: "VMX_SVM_CPU_FLAG_HINT")
    monkeypatch.setattr(p3f, "_kvm_hint", lambda: "KVM_DEVICE_DAC_ACCESS_HINT")
    monkeypatch.setattr(p3f, "_binary_hints", lambda: {"libvirt_virsh": "FILE_OR_SYMLINK_HINT"})
    monkeypatch.setattr(p3f.platform, "system", lambda: "Linux")
    out = p3f.observe()
    assert out["decision"] == "P3F_NO_GO_HOST_CAPABILITY_ONLY"
    assert out["separate_disposable_guest_identified"] is False
    assert out["independent_administrator_verified"] is False
    assert out["p3_f01_to_f28_executed"] == 0
    assert not any(out["operational_authorizations"].values())
    assert "/dev/kvm" not in json.dumps(out)


def test_cli_on_nonroot_always_no_go(monkeypatch, capsys):
    for name in ("getuid", "geteuid", "getgid", "getegid"):
        monkeypatch.setattr(p3f.os, name, lambda: 1000)
    monkeypatch.setattr(p3f, "_cpu_hint", lambda: "CPUINFO_UNKNOWN")
    monkeypatch.setattr(p3f, "_kvm_hint", lambda: "KVM_DEVICE_NOT_OBSERVED")
    monkeypatch.setattr(p3f, "_binary_hints", lambda: {})
    assert p3f.main([p3f._ACK]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "P3F_NO_GO_HOST_CAPABILITY_ONLY"
    assert out["guest_creation_or_service_changes_authorized"] is False


def test_no_filesystem_changing_functions_in_module():
    source = Path(p3f.__file__).read_text()
    for forbidden in ("subprocess", "os.system(", "os.mkdir(", "os.chmod(", "os.chown(", "os.open(", "socket."):
        assert forbidden not in source


def test_missing_cpuinfo_yields_unknown(monkeypatch):
    def unreadable(self, mode):
        raise PermissionError("denied")
    monkeypatch.setattr(p3f.Path, "open", unreadable)
    assert p3f._cpu_hint() == "CPUINFO_UNKNOWN"


def test_checked_in_decision_remains_no_go():
    root = Path(__file__).resolve().parents[1]
    path = root / "docs/architecture/p3/p3f-host-capability-decision.json"
    obj = json.loads(path.read_text())
    assert obj["decision"] == "P3F_NO_GO_HOST_CAPABILITY_ONLY"
    assert obj["separate_disposable_vm_verified"] is False
    assert obj["p3_f01_to_f28_executed"] == 0
    assert all(v is False for v in obj["current_permissions"].values())
