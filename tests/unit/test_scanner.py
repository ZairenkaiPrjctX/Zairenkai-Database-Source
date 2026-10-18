from afid import dependencies
from afid.classification import Classifier
from afid.licensing import Policy
from afid.scanning import Scanner
from tests.conftest import build_tree


def scanner(repo):
    return Scanner(
        Classifier(repo.rules),
        Policy.from_config(repo.policy, repo.allowlist),
        repo.settings["scan"]["partitions"],
        repo.limit("max_file_hash_bytes"),
    )


def scan(repo, tree):
    s = scanner(repo)
    res = s.scan(tree, "google_pixel_fixturecode__FIX1", "local_firmware", True)
    edges = dependencies.build(
        tree, res, s, "google_pixel_fixturecode__FIX1", "local_firmware", True
    )
    return res, edges, {f"{c['partition']}/{c['path']}": c for c in res.components}


def test_thermal_hal_and_configs_from_several_locations(repo, tree):
    _, _, by = scan(repo, tree)
    hal = by["vendor/bin/hw/android.hardware.thermal-service.fixture"]
    assert hal["category"] == "thermal_hal" and hal["file_type"] == "elf"
    assert hal["details"]["elf"]["machine"] == "aarch64"
    assert by["vendor/etc/thermal_info_config.json"]["details"]["config"]["sensors"] == [
        "VIRTUAL-SKIN",
        "cpu0",
    ]
    engine = by["odm/etc/thermal/thermal-engine.conf"]
    assert engine["category"] == "thermal_config" and engine["details"]["config"]["sections"] == [
        "SKIN-MONITOR"
    ]
    assert by["vendor/etc/powerhint.json"]["category"] == "power_json"


def test_power_json_absent_is_not_invented(repo, tmp_path):
    t = build_tree(tmp_path / "t", powerhint=False)
    res, _, _ = scan(repo, t)
    assert not [c for c in res.components if c["category"] == "power_json"]


def test_init_relevance_and_unknown_inventory(repo, tree):
    res, _, by = scan(repo, tree)
    rc = by["vendor/etc/init/android.hardware.thermal-service.fixture.rc"]
    assert rc["category"] == "init_service" and rc["details"]["relevant_services"] == [
        "vendor.thermal-hal"
    ]
    assert "vendor/etc/init/unrelated.rc" not in by  # unrelated init stays inventory-only
    assert by["vendor/bin/hw/vendor.example.unknown-service"]["category"] == "unknown"
    assert "vendor/app/README.txt" not in by
    assert any(e.path == "app/README.txt" for e in res.inventory)  # but it is inventoried


def test_duplicates_and_same_name_different_content(repo, tree):
    _, _, by = scan(repo, tree)
    impl = by["vendor/lib64/hw/thermal.fixture.so"]
    lib = by["vendor/lib64/libthermal_fixture.so"]
    assert impl["sha256"] == lib["sha256"]
    # Path order puts lib64/hw/ before lib64/lib..., so the library is the duplicate.
    assert lib["duplicate_of"] == impl["component_id"] and impl["duplicate_of"] is None

    # Same file name, different content: two independent records, neither a duplicate.
    from tests.conftest import write

    write(tree / "vendor/etc/thermal/thermal_info_config.json", '{"Sensors": []}')
    _, _, by = scan(repo, tree)
    a = by["vendor/etc/thermal_info_config.json"]
    b = by["vendor/etc/thermal/thermal_info_config.json"]
    assert a["sha256"] != b["sha256"] and a["duplicate_of"] is None and b["duplicate_of"] is None


def test_symlinks_recorded_not_followed(repo, tree):
    res, _, _ = scan(repo, tree)
    links = {e.path: e for e in res.inventory if e.is_symlink}
    assert links["lib64/libthermal_link.so"].symlink_target == "libthermal_fixture.so"
    assert any("libescape.so" in w and "escapes" in w for w in res.warnings)


def test_dependency_edges(repo, tree):
    _, edges, by = scan(repo, tree)
    svc = by["vendor/bin/hw/android.hardware.thermal-service.fixture"]["component_id"]
    lib = by["vendor/lib64/libthermal_fixture.so"]["component_id"]

    def needed(src):
        return {
            (e["to_name"], e["status"])
            for e in edges
            if e["from"] == src and e["type"] == "dt_needed"
        }

    assert needed(svc) == {("libthermal_fixture.so", "resolved")}
    # Transitive: the library's own DT_NEEDED entries, one of them absent from the tree.
    assert needed(lib) == {
        ("libfixture_dep.so", "resolved"),
        ("libmissing_fixture.so", "unresolved"),
    }
    rc = by["vendor/etc/init/android.hardware.thermal-service.fixture.rc"]["component_id"]
    (init_edge,) = [e for e in edges if e["type"] == "init_service_binary"]
    assert init_edge["from"] == rc and init_edge["to"] == svc and init_edge["status"] == "resolved"
    vintf = [e for e in edges if e["type"] == "vintf_declares_hal"]
    assert {(e["to_name"], e["status"]) for e in vintf} == {
        ("android.hardware.thermal", "resolved"),
        ("android.hardware.power", "unresolved"),
    }
    cfg = [e for e in edges if e["type"] == "hal_config"]
    assert cfg and cfg[0]["status"] == "inferred" and "string" in cfg[0]["evidence"]


def test_scan_is_deterministic(repo, tree):
    a = scan(repo, tree)
    b = scan(repo, tree)
    assert a[0].components == b[0].components and a[1] == b[1]
