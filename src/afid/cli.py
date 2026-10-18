"""afid command-line interface."""

from __future__ import annotations

import argparse
import platform
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from afid import __version__, audit, dependencies, ingest, reporting, updates
from afid.catalog import Store
from afid.catalog import index as catalog_index
from afid.catalog.validate import load_validators, validate
from afid.classification import Classifier
from afid.config import Config
from afid.config import load as load_config
from afid.errors import AfidError, CapabilityError, NotFoundError
from afid.extraction import tools
from afid.licensing import Policy
from afid.providers import registry
from afid.scanning import Scanner
from afid.utils import jsonio, log

Handler = Callable[[argparse.Namespace, Config], int]


def _out(args: argparse.Namespace, data: Any, text: str | None = None) -> None:
    if args.json or text is None:
        sys.stdout.write(jsonio.dumps(data))
    else:
        sys.stdout.write(text.rstrip("\n") + "\n")


def _table(rows: list[list[str]], header: list[str]) -> str:
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    return "\n".join(
        [fmt.format(*header), fmt.format(*("-" * w for w in widths))]
        + [fmt.format(*map(str, r)) for r in rows]
    )


# ---- commands --------------------------------------------------------------------------------
def cmd_version(args: argparse.Namespace, cfg: Config | None) -> int:
    _out(
        args,
        {"afid": __version__, "python": platform.python_version()},
        f"afid {__version__} (Python {platform.python_version()})",
    )
    return 0


def cmd_doctor(args: argparse.Namespace, cfg: Config) -> int:
    checks: list[dict[str, Any]] = []
    ok = True

    def add(name: str, status: str, detail: str) -> None:
        nonlocal ok
        ok &= status != "fail"
        checks.append({"check": name, "status": status, "detail": detail})

    add("python", "ok" if sys.version_info >= (3, 11) else "fail", platform.python_version())
    try:
        load_validators(cfg.schemas_dir)
        add("schemas", "ok", str(cfg.schemas_dir))
    except Exception as exc:  # noqa: BLE001
        add("schemas", "fail", str(exc))
    try:
        Classifier(cfg.rules)
        Policy.from_config(cfg.policy, cfg.allowlist)
        add("config", "ok", "rules, policy and allowlist load")
    except AfidError as exc:
        add("config", "fail", str(exc))
    for e in registry.entries(cfg):
        problems = registry.self_test(cfg, e)
        add(f"provider:{e['id']}", "fail" if problems else "ok", "; ".join(problems) or e["status"])
    for name, tool in tools.TOOLS.items():
        found = tools.which(name)
        add(
            f"tool:{name}",
            "ok" if found else "missing",
            (tools.version(name) or found)
            if found
            else f"{tool.purpose}; install: {tool.install_hint}",
        )
    add("git", "ok" if shutil.which("git") else "missing", "needed by lineageos_wiki discovery")
    _out(
        args,
        {"ok": ok, "checks": checks},
        _table(
            [[c["check"], c["status"], c["detail"][:90]] for c in checks],
            ["check", "status", "detail"],
        )
        + f"\n\n{'OK' if ok else 'PROBLEMS FOUND'}",
    )
    return 0 if ok else 1


def cmd_providers_list(args: argparse.Namespace, cfg: Config) -> int:
    rows = registry.entries(cfg)
    _out(
        args,
        rows,
        _table(
            [
                [
                    e["id"],
                    e["status"],
                    ",".join(e["brand_ids"]),
                    ",".join(k for k, v in e["capabilities"].items() if v) or "-",
                ]
                for e in rows
            ],
            ["provider", "status", "brands", "capabilities"],
        ),
    )
    return 0


def cmd_providers_test(args: argparse.Namespace, cfg: Config) -> int:
    results = []
    for e in registry.entries(cfg):
        if args.provider and e["id"] != args.provider:
            continue
        results.append({"provider_id": e["id"], "problems": registry.self_test(cfg, e)})
    if args.provider and not results:
        raise NotFoundError(f"unknown provider '{args.provider}'")
    bad = [r for r in results if r["problems"]]
    _out(
        args,
        results,
        "\n".join(
            f"{'FAIL' if r['problems'] else 'ok  '} {r['provider_id']}"
            + (": " + "; ".join(r["problems"]) if r["problems"] else "")
            for r in results
        ),
    )
    return 1 if bad else 0


def cmd_discover(args: argparse.Namespace, cfg: Config) -> int:
    outcome = updates.check(cfg, args.provider, args.brand, write=args.write)
    data = {
        "provider_status": outcome.provider_status,
        "candidates": sum(len(r.candidates) for r in outcome.results),
        "changes": [c.as_dict() for c in outcome.changes][: args.limit],
        "written": outcome.written,
    }
    text = _table(
        [
            [p["provider_id"], p["status"], (p["detail"] or "")[:100]]
            for p in outcome.provider_status
        ],
        ["provider", "status", "detail"],
    )
    text += f"\n\n{data['candidates']} candidate(s); {len(outcome.changes)} change(s)"
    text += (
        f"; {len(outcome.written)} file(s) written"
        if args.write
        else " (dry run: pass --write to store snapshots and staging candidates)"
    )
    _out(args, data, text)
    return 1 if outcome.failed else 0


def cmd_devices_list(args: argparse.Namespace, cfg: Config) -> int:
    devs = [
        d for d in Store(cfg.database).devices() if not args.brand or d["brand_id"] == args.brand
    ]
    _out(
        args,
        devs,
        _table(
            [[d["device_id"], d["codename"], ", ".join(d["product_names"])[:50]] for d in devs],
            ["device_id", "codename", "product names"],
        )
        if devs
        else "no verified devices in the catalog",
    )
    return 0


def cmd_devices_show(args: argparse.Namespace, cfg: Config) -> int:
    d = Store(cfg.database).find_device(args.device_id)
    _out(args, d, None)
    return 0


def cmd_firmware_list(args: argparse.Namespace, cfg: Config) -> int:
    store = Store(cfg.database)
    store.find_device(args.device)
    fws = [f for f in store.firmware() if f["device_id"] == args.device]
    _out(
        args,
        fws,
        _table(
            [
                [
                    f["firmware_id"],
                    f["android_release"] or "-",
                    f["security_patch"] or "-",
                    f["component_count"],
                ]
                for f in fws
            ],
            ["firmware_id", "android", "patch", "components"],
        )
        if fws
        else f"no firmware for {args.device}",
    )
    return 0


def cmd_firmware_inspect(args: argparse.Namespace, cfg: Config) -> int:
    store = Store(cfg.database)
    path, fw = store.find_firmware(args.firmware_id)
    comps = store.components_of(path)
    by_cat: dict[str, int] = {}
    for c in comps:
        by_cat[c["category"]] = by_cat.get(c["category"], 0) + 1
    data: dict[str, Any] = {"firmware": fw, "components_by_category": dict(sorted(by_cat.items()))}
    if args.components:
        data["components"] = comps
    _out(args, data, None)
    return 0


def cmd_ingest(args: argparse.Namespace, cfg: Config) -> int:
    if args.source:
        return _ingest_source(args, cfg)
    res = ingest.ingest_local(
        cfg,
        Path(args.local),
        args.provider,
        args.brand,
        args.codename,
        args.sha256,
        args.region,
        args.channel,
        args.dry_run,
        args.keep_work,
    )
    text = f"status: {res.status}"
    if res.firmware_id:
        text += (
            f"\nfirmware: {res.firmware_id}\ncomponents: {res.component_count}"
            f"\ndependency edges: {res.edge_counts}"
        )
    if res.detail:
        text += f"\nreason: {res.detail}"
    text += "".join(f"\nwrote: {w}" for w in res.written)
    text += "".join(f"\nwarning: {w}" for w in res.warnings[:20])
    _out(args, res.as_dict(), text)
    return 0 if res.status in ("cataloged", "dry_run") else 12


def _ingest_source(args: argparse.Namespace, cfg: Config) -> int:
    store = Store(cfg.database)
    for p in store.source_files():
        snap = jsonio.load(p)
        for item in snap["items"]:
            if (
                item["item_id"] == args.source
                or f"{snap['provider_id']}:{item['item_id']}" == args.source
            ):
                prov = registry.get(cfg, snap["provider_id"])
                if item["kind"] != "firmware":
                    raise CapabilityError(
                        f"source item '{args.source}' is a {item['kind']} record from "
                        f"'{snap['provider_id']}', not a downloadable firmware"
                    )
                raise CapabilityError(  # no provider can download yet; say so precisely
                    f"provider '{prov.provider_id}' cannot download: {prov.limitations}"
                )
    raise NotFoundError(f"source item '{args.source}' not found in database/sources/")


def _scanner(cfg: Config) -> Scanner:
    return Scanner(
        Classifier(cfg.rules),
        Policy.from_config(cfg.policy, cfg.allowlist),
        cfg.settings["scan"]["partitions"],
        cfg.limit("max_file_hash_bytes"),
    )


def cmd_scan(args: argparse.Namespace, cfg: Config) -> int:
    tree = Path(args.input)
    if not tree.is_dir():
        raise NotFoundError(f"{tree} is not a directory")
    scanner = _scanner(cfg)
    res = scanner.scan(tree, "adhoc", "local_firmware", user_supplied=True)
    edges = dependencies.build(tree, res, scanner, "adhoc", "local_firmware", True)
    data = {
        "files": len(res.inventory),
        "components": res.components,
        "edges": edges,
        "warnings": res.warnings,
    }
    if args.inventory:
        data["inventory"] = [vars(e) for e in res.inventory]
    if args.output:
        jsonio.write_if_changed(Path(args.output), data)
    by_cat: dict[str, int] = {}
    for c in res.components:
        by_cat[c["category"]] = by_cat.get(c["category"], 0) + 1
    _out(
        args,
        data if not args.output else {"output": args.output, "by_category": by_cat},
        f"{len(res.inventory)} files, {len(res.components)} catalog components, "
        f"{len(edges)} dependency edges\n"
        + _table(sorted([k, str(v)] for k, v in by_cat.items()), ["category", "count"]),
    )
    return 0


def cmd_classify(args: argparse.Namespace, cfg: Config) -> int:
    tree = Path(args.input)
    if not tree.is_dir():
        raise NotFoundError(f"{tree} is not a directory")
    res = _scanner(cfg).scan(tree, "adhoc", "local_firmware", user_supplied=True)
    rows = [
        [
            c["category"],
            c["subcategory"],
            f"{c['classification']['confidence']:.2f}",
            f"{c['partition']}/{c['path']}",
        ]
        for c in res.components
    ]
    _out(
        args,
        [
            {
                "path": f"{c['partition']}/{c['path']}",
                "category": c["category"],
                "subcategory": c["subcategory"],
                "classification": c["classification"],
            }
            for c in res.components
        ],
        _table(rows, ["category", "subcategory", "conf", "path"]) if rows else "nothing classified",
    )
    return 0


def cmd_dependencies_build(args: argparse.Namespace, cfg: Config) -> int:
    store = Store(cfg.database)
    _, _, libmap = catalog_index.build(store, cfg.brand_ids)
    path = cfg.database / "dependencies" / "library_map.json"
    changed = jsonio.write_if_changed(path, libmap)
    _out(
        args,
        {"libraries": len(libmap["libraries"]), "written": changed},
        f"{len(libmap['libraries'])} libraries mapped; "
        f"{'updated' if changed else 'unchanged'} {path.relative_to(cfg.root)}",
    )
    return 0


def cmd_db_validate(args: argparse.Namespace, cfg: Config) -> int:
    res = validate(cfg.database, cfg.schemas_dir, cfg.brand_ids)
    stale = catalog_index.check(Store(cfg.database), cfg.brand_ids) if args.check_index else []
    errors = res.errors + [f"{s}: stale or missing; run `afid database index`" for s in stale]
    data = {**res.as_dict(), "errors": errors, "ok": not errors}
    text = "\n".join([f"ERROR   {e}" for e in errors] + [f"WARNING {w}" for w in res.warnings])
    text += f"\n{res.counts}\n{'OK' if not errors else f'{len(errors)} error(s)'}"
    _out(args, data, text)
    fail = bool(errors) or (args.strict and bool(res.warnings))
    return 3 if fail else 0


def cmd_db_index(args: argparse.Namespace, cfg: Config) -> int:
    store = Store(cfg.database)
    if args.check:
        stale = catalog_index.check(store, cfg.brand_ids)
        _out(args, {"stale": stale}, "\n".join(stale) or "generated files are up to date")
        return 3 if stale else 0
    written = catalog_index.write(store, cfg.brand_ids)
    _out(
        args,
        {"written": [str(p) for p in written]},
        "\n".join(f"wrote {p.relative_to(cfg.root)}" for p in written) or "unchanged",
    )
    return 0


def cmd_db_stats(args: argparse.Namespace, cfg: Config) -> int:
    _, stats, _ = catalog_index.build(Store(cfg.database), cfg.brand_ids)
    flat = {k: v for k, v in stats.items() if isinstance(v, int)}
    _out(args, stats, _table([[k, str(v)] for k, v in flat.items()], ["metric", "value"]))
    return 0


def cmd_updates_check(args: argparse.Namespace, cfg: Config) -> int:
    outcome = updates.check(cfg, args.provider, args.brand, write=args.write)
    rep = outcome.report()
    if args.report_out and outcome.changes:
        jsonio.write_if_changed(Path(args.report_out), rep)
    _out(
        args,
        rep,
        f"{len(outcome.changes)} change(s): {rep['summary'] or 'none'}\n"
        + _table(
            [
                [p["provider_id"], p["status"], (p["detail"] or "")[:90]]
                for p in outcome.provider_status
            ],
            ["provider", "status", "detail"],
        ),
    )
    return 1 if outcome.failed else 0


def cmd_updates_report(args: argparse.Namespace, cfg: Config) -> int:
    reps = updates.history(Store(cfg.database), args.device)
    _out(
        args,
        reps,
        "\n".join(f"{r['from']} -> {r['to']}: {len(r['changes'])} change(s)" for r in reps)
        or "fewer than two builds per device; nothing to compare",
    )
    return 0


def cmd_report(args: argparse.Namespace, cfg: Config) -> int:
    rep = reporting.build(cfg)
    text = reporting.to_markdown(rep) if args.format == "markdown" else jsonio.dumps(rep)
    if args.output:
        Path(args.output).write_text(text)
    else:
        sys.stdout.write(text)
    return 0


def cmd_cache_clean(args: argparse.Namespace, cfg: Config) -> int:
    target = cfg.cache if args.all else cfg.cache / "work"
    existed = target.exists()
    if existed:
        shutil.rmtree(target)
    _out(
        args,
        {"removed": str(target) if existed else None},
        f"removed {target}" if existed else f"nothing to remove at {target}",
    )
    return 0


def cmd_policy_check(args: argparse.Namespace, cfg: Config) -> int:
    policy = Policy.from_config(cfg.policy, cfg.allowlist)
    problems = policy.check_publish_dir(cfg.path("redistributable"))
    store = Store(cfg.database)
    for p in store.component_files():
        for c in jsonio.load(p)["components"]:
            if c["distribution_status"] == "allowed" and c["sha256"] not in policy.allow_by_sha:
                problems.append(f"{p}: {c['component_id']} marked allowed without allowlist entry")
    for p in store.staging_files():
        cand = jsonio.load(p)
        lic = cand.get("license") or {}
        if cand.get("firmware_payload_ingested") is not False:
            problems.append(f"{p}: staging records must not carry firmware payloads")
        if (cand.get("verification") or {}).get("status") != "unverified":
            problems.append(f"{p}: staging records must stay unverified")
        if (lic.get("share_alike") or lic.get("status") != "unknown") and not lic.get(
            "attribution"
        ):
            problems.append(f"{p}: licensed third-party data without attribution")
        if lic.get("status") == "unknown" and policy.can_publish(
            cand.get("distribution_status", "")
        ):
            problems.append(f"{p}: unknown license marked publishable")
    _out(args, {"problems": problems}, "\n".join(problems) or "policy check passed")
    return 9 if problems else 0


def cmd_security_scan(args: argparse.Namespace, cfg: Config) -> int:
    findings = audit.scan(cfg.root)
    _out(args, {"findings": findings}, "\n".join(findings) or "no findings")
    return 9 if findings else 0


# ---- parser ----------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="afid", description="AFID - Android Firmware Intelligence Database tooling"
    )
    p.add_argument(
        "--root", help="repository root (default: search upward for config/settings.yml)"
    )
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def cmd(
        parent: Any, name: str, fn: Handler | Callable[..., int], help_: str
    ) -> argparse.ArgumentParser:
        sp: argparse.ArgumentParser = parent.add_parser(name, help=help_, description=help_)
        sp.set_defaults(fn=fn)
        return sp

    cmd(sub, "version", cmd_version, "print version")
    cmd(sub, "doctor", cmd_doctor, "check environment, config, providers and external tools")

    prov = sub.add_parser("providers", help="provider registry").add_subparsers(
        dest="sub", required=True
    )
    cmd(prov, "list", cmd_providers_list, "list providers, status and capabilities")
    t = cmd(
        prov, "test", cmd_providers_test, "offline consistency test of provider registry entries"
    )
    t.add_argument("--provider")

    d = cmd(sub, "discover", cmd_discover, "run metadata discovery for providers that support it")
    d.add_argument("--brand")
    d.add_argument("--provider")
    d.add_argument("--write", action="store_true", help="store snapshot and staging candidates")
    d.add_argument("--limit", type=int, default=200, help="max changes printed")

    dev = sub.add_parser("devices", help="verified device catalog").add_subparsers(
        dest="sub", required=True
    )
    dl = cmd(dev, "list", cmd_devices_list, "list verified devices")
    dl.add_argument("--brand")
    cmd(dev, "show", cmd_devices_show, "show a device record").add_argument("device_id")

    fw = sub.add_parser("firmware", help="firmware builds").add_subparsers(
        dest="sub", required=True
    )
    cmd(fw, "list", cmd_firmware_list, "list firmware builds of a device").add_argument(
        "--device", required=True
    )
    fi = cmd(fw, "inspect", cmd_firmware_inspect, "show a firmware record and its components")
    fi.add_argument("firmware_id")
    fi.add_argument("--components", action="store_true", help="include component records")

    ing = cmd(sub, "ingest", cmd_ingest, "ingest firmware into the catalog")
    src = ing.add_mutually_exclusive_group(required=True)
    src.add_argument("--source", help="discovered source item id (provider:item)")
    src.add_argument("--local", help="local archive, image or extracted directory")
    ing.add_argument(
        "--provider", default="local_firmware", help="provider id (default local_firmware)"
    )
    ing.add_argument("--brand")
    ing.add_argument("--codename", help="expected codename; must agree with firmware evidence")
    ing.add_argument("--sha256", help="official checksum to verify the archive against")
    ing.add_argument("--region")
    ing.add_argument("--channel")
    ing.add_argument("--dry-run", action="store_true", help="run everything except writing")
    ing.add_argument("--keep-work", action="store_true", help="keep extraction work directory")

    sc = cmd(sub, "scan", cmd_scan, "scan an extracted tree (no catalog write)")
    sc.add_argument("--input", required=True)
    sc.add_argument("--output", help="write full JSON result to this file")
    sc.add_argument("--inventory", action="store_true", help="include the full file inventory")
    cmd(sub, "classify", cmd_classify, "classify files in an extracted tree").add_argument(
        "--input", required=True
    )

    dep = sub.add_parser("dependencies", help="dependency map").add_subparsers(
        dest="sub", required=True
    )
    cmd(dep, "build", cmd_dependencies_build, "rebuild database/dependencies/library_map.json")

    db = sub.add_parser("database", help="catalog maintenance").add_subparsers(
        dest="sub", required=True
    )
    v = cmd(db, "validate", cmd_db_validate, "validate schemas, references and policy")
    v.add_argument("--strict", action="store_true", help="fail on warnings")
    v.add_argument("--check-index", action="store_true", help="also fail on stale index/statistics")
    ix = cmd(db, "index", cmd_db_index, "regenerate index.json and statistics.json")
    ix.add_argument("--check", action="store_true", help="only check that they are up to date")
    cmd(db, "stats", cmd_db_stats, "print statistics computed from the catalog")

    up = sub.add_parser("updates", help="update detection").add_subparsers(
        dest="sub", required=True
    )
    uc = cmd(up, "check", cmd_updates_check, "compare provider sources with stored snapshots")
    uc.add_argument("--provider")
    uc.add_argument("--brand")
    uc.add_argument("--write", action="store_true", help="store snapshots and staging candidates")
    uc.add_argument("--report-out", help="write the report here when there are changes")
    ur = cmd(up, "report", cmd_updates_report, "compare consecutive firmware builds per device")
    ur.add_argument("--device")

    r = cmd(sub, "report", cmd_report, "catalog report")
    r.add_argument("--format", choices=["json", "markdown"], default="json")
    r.add_argument("--output")

    cache = sub.add_parser("cache", help="local cache").add_subparsers(dest="sub", required=True)
    cmd(cache, "clean", cmd_cache_clean, "remove extraction work directories").add_argument(
        "--all", action="store_true", help="also remove provider caches"
    )

    pol = sub.add_parser("policy", help="distribution policy").add_subparsers(
        dest="sub", required=True
    )
    cmd(pol, "check", cmd_policy_check, "verify nothing unpublishable is staged for publication")
    sec = sub.add_parser("security", help="repository audit").add_subparsers(
        dest="sub", required=True
    )
    cmd(sec, "scan", cmd_security_scan, "scan for secrets, payloads, large files, workflow risks")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    log.setup(args.verbose)
    try:
        cfg = None if args.fn is cmd_version else load_config(args.root)
        return int(args.fn(args, cfg))
    except AfidError as exc:
        if args.json:
            sys.stdout.write(jsonio.dumps({"error": type(exc).__name__, "message": str(exc)}))
        print(f"afid: error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("afid: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
