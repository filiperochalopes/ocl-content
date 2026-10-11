#!/usr/bin/env python3
"""Verify, offline, that a bulk import did exactly what its artifact proposed.

Two modes. ``--mode update`` (default) compares an export taken BEFORE with one taken AFTER an
update. ``--mode create`` is for a brand-new Source: there is no "before", so the export taken after
the load is compared directly with the artifact.

    python3 tools/ocl_verify_update.py \\
        --before exports/api.ocl.localhost/before/WHO_ICD-10-WHO_HEAD.zip \\
        --after  exports/api.ocl.localhost/WHO_ICD-10-WHO_HEAD.zip \\
        --artifact terminologies/icd/icd-10/output/bulkimport_icd10-who.zip \\
        --audit terminologies/icd/icd-10/output/bulkimport_audit.json \\
        --report reports/icd10-local-update.json

``before`` and ``after`` are exports of the same Source taken from the instance that received the
update (a local replica), ``artifact`` is the bundle that was uploaded. The tool reads files only;
it needs no token and makes no network call. It exits 0 only when every check passes, so the report
is evidence a reviewer can rely on:

* every targeted concept existed before and after;
* no existing name was removed or changed, and the only added names are the ones the artifact
  proposed, in the expected locales, typed ``Fully Specified``, preferred and active;
* descriptions, extras, class and the retired flag of the targeted concepts are unchanged;
* every concept the artifact did *not* target is identical before and after;
* the update created no concept.

In ``create`` mode the checks are: every artifact concept exists after the load, with exactly the
names, extras, and class the artifact carried, and the Source holds no concept the artifact did not.

The report records each input by file name and SHA-256 (no absolute paths, no timestamp), so the same
inputs give a byte-identical report.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ocl_export  # noqa: E402

BUNDLE_NAME = "bulkimport_bundle.ndjson"
DEFAULT_LOCALES = ("pt_BR", "fr")
DEFAULT_NAME_TYPE = "Fully Specified"
MAX_EXAMPLES = 10


@dataclass
class Check:
    id: str
    description: str
    failures: int = 0
    examples: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    def fail(self, message: str) -> None:
        self.failures += 1
        if len(self.examples) < MAX_EXAMPLES:
            self.examples.append(message)

    @property
    def status(self) -> str:
        return "pass" if self.failures == 0 else "fail"


def name_key(name: dict) -> tuple:
    return (
        name.get("name"),
        name.get("locale"),
        name.get("name_type"),
        bool(name.get("locale_preferred")),
        bool(name.get("retired")),
    )


def description_key(description: dict) -> tuple:
    return (
        description.get("description"),
        description.get("locale"),
        description.get("description_type") or description.get("type"),
        bool(description.get("locale_preferred")),
        bool(description.get("retired")),
    )


def names_of(concept: dict) -> set[tuple]:
    return {name_key(n) for n in concept.get("names") or [] if isinstance(n, dict)}


def descriptions_of(concept: dict) -> set[tuple]:
    return {description_key(d) for d in concept.get("descriptions") or [] if isinstance(d, dict)}


def scalar_state(concept: dict) -> tuple:
    return (concept.get("concept_class"), bool(concept.get("retired")))


def read_artifact(path: Path) -> list[dict]:
    """Concept lines of a bundle ``.ndjson``, a zip holding the bundle, or a directory of parts."""
    path = Path(path)
    if path.is_dir():
        raw = b"".join(part.read_bytes() for part in sorted(path.glob("*_part_*.ndjson")))
    elif path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            if BUNDLE_NAME not in archive.namelist():
                raise ValueError(f"{path.name}: no {BUNDLE_NAME} member")
            raw = archive.read(BUNDLE_NAME)
    elif path.is_file():
        raw = path.read_bytes()
    else:
        raise FileNotFoundError(f"artifact not found: {path}")
    lines: list[dict] = []
    for number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if line.strip():
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"{path.name} line {number}: not valid JSON ({error})") from None
    return [line for line in lines if line.get("type") == "Concept"]


def verify(
    before: dict[str, dict],
    after: dict[str, dict],
    artifact: list[dict],
    *,
    locales: tuple[str, ...] = DEFAULT_LOCALES,
    name_type: str = DEFAULT_NAME_TYPE,
) -> list[Check]:
    wellformed = Check("artifact-well-formed", "artifact lines are unique Concept resources with an id")
    present_before = Check("targets-present-before", "every targeted concept exists in the before export")
    present_after = Check("targets-present-after", "every targeted concept exists in the after export")
    kept = Check("existing-names-kept", "no existing name of a targeted concept was removed or changed")
    additions = Check("additions-match-artifact", "the names added are exactly the ones the artifact proposed")
    policy = Check("additions-policy", f"added names are in {list(locales)}, typed {name_type!r}, preferred and active")
    descriptions = Check("descriptions-unchanged", "descriptions of targeted concepts are unchanged")
    extras = Check("extras-unchanged", "extras of targeted concepts are unchanged")
    scalars = Check("class-and-retired-unchanged", "concept class and retired flag of targeted concepts are unchanged")
    untouched = Check("untouched-concepts-identical", "every concept the artifact did not target is identical before and after")
    created = Check("no-concept-created", "the update created no concept")

    targets: dict[str, dict] = {}
    for line in artifact:
        concept_id = str(line.get("id") or "")
        if not concept_id:
            wellformed.fail("a Concept line without an id")
        elif concept_id in targets:
            wellformed.fail(f"{concept_id}: appears twice in the artifact")
        else:
            targets[concept_id] = line

    added_by_locale: dict[str, int] = {}
    for concept_id, line in targets.items():
        old, new = before.get(concept_id), after.get(concept_id)
        if old is None:
            present_before.fail(f"{concept_id}: not in the before export")
        if new is None:
            present_after.fail(f"{concept_id}: not in the after export")
        if old is None or new is None:
            continue
        old_names, new_names = names_of(old), names_of(new)
        for lost in sorted(old_names - new_names, key=str):
            kept.fail(f"{concept_id}: name lost or changed: {lost}")
        expected = {name_key(n) for n in line.get("names") or []} - old_names
        actual = new_names - old_names
        if actual != expected:
            additions.fail(
                f"{concept_id}: expected +{sorted(expected - actual, key=str)} / unexpected +{sorted(actual - expected, key=str)}"
            )
        for key in actual:
            added_by_locale[key[1]] = added_by_locale.get(key[1], 0) + 1
            if key[1] not in locales or key[2] != name_type or not key[3] or key[4]:
                policy.fail(f"{concept_id}: {key}")
        if descriptions_of(old) != descriptions_of(new):
            descriptions.fail(f"{concept_id}: descriptions differ")
        if (old.get("extras") or {}) != (new.get("extras") or {}):
            extras.fail(f"{concept_id}: extras differ")
        if scalar_state(old) != scalar_state(new):
            scalars.fail(f"{concept_id}: {scalar_state(old)} -> {scalar_state(new)}")

    for concept_id, old in before.items():
        if concept_id in targets:
            continue
        new = after.get(concept_id)
        if new is None:
            untouched.fail(f"{concept_id}: missing after the update")
        elif (names_of(old), descriptions_of(old), old.get("extras") or {}, scalar_state(old)) != (
            names_of(new), descriptions_of(new), new.get("extras") or {}, scalar_state(new)
        ):
            untouched.fail(f"{concept_id}: changed although the artifact did not target it")
    for concept_id in after:
        if concept_id not in before:
            created.fail(f"{concept_id}: new concept after the update")

    present_before.info = {"targeted": len(targets), "before_concepts": len(before)}
    present_after.info = {"after_concepts": len(after)}
    additions.info = {"added_names_by_locale": dict(sorted(added_by_locale.items()))}
    untouched.info = {"checked": len([c for c in before if c not in targets])}
    return [wellformed, present_before, present_after, kept, additions, policy, descriptions, extras, scalars, untouched, created]


def verify_creation(after: dict[str, dict], artifact: list[dict]) -> list[Check]:
    """Checks for a new Source: the export after the load must equal the artifact, concept by concept."""
    wellformed = Check("artifact-well-formed", "artifact lines are unique Concept resources with an id")
    present = Check("all-concepts-loaded", "every artifact concept exists in the Source after the load")
    names = Check("names-match-artifact", "each concept carries exactly the names the artifact carried")
    extras = Check("extras-match-artifact", "each concept carries exactly the extras the artifact carried")
    scalars = Check("class-and-retired-match-artifact", "concept class and retired flag match the artifact")
    unexpected = Check("no-concept-beyond-artifact", "the Source holds no concept the artifact did not carry")
    targets: dict[str, dict] = {}
    for line in artifact:
        concept_id = str(line.get("id") or "")
        if not concept_id:
            wellformed.fail("a Concept line without an id")
        elif concept_id in targets:
            wellformed.fail(f"{concept_id}: appears twice in the artifact")
        else:
            targets[concept_id] = line
    for concept_id, line in targets.items():
        loaded = after.get(concept_id)
        if loaded is None:
            present.fail(f"{concept_id}: not in the export taken after the load")
            continue
        if names_of(loaded) != {name_key(n) for n in line.get("names") or []}:
            names.fail(f"{concept_id}: names differ from the artifact")
        if (loaded.get("extras") or {}) != (line.get("extras") or {}):
            extras.fail(f"{concept_id}: extras differ from the artifact")
        if scalar_state(loaded) != scalar_state(line):
            scalars.fail(f"{concept_id}: {scalar_state(line)} in the artifact, {scalar_state(loaded)} after the load")
    for concept_id in after:
        if concept_id not in targets:
            unexpected.fail(f"{concept_id}: in the Source but not in the artifact")
    present.info = {"artifact_concepts": len(targets), "after_concepts": len(after)}
    return [wellformed, present, names, extras, scalars, unexpected]


def audit_check(audit_path: Path | None, before_path: Path) -> Check | None:
    """When an audit is given, the artifact must have been built from this exact before export."""
    if audit_path is None:
        return None
    check = Check("artifact-built-from-before-export", "the audit records this before export's SHA-256")
    audit = json.loads(Path(audit_path).read_text(encoding="utf-8"))
    recorded = (audit.get("export") or {}).get("sha256")
    actual = ocl_export.sha256_path(before_path)
    if not recorded:
        check.fail("the audit has no export record: it was built from the offline baseline, not from an export")
    elif recorded != actual:
        check.fail(f"audit export sha256 {recorded[:12]}… != before export {actual[:12]}…")
    check.info = {"audit_export_sha256": recorded, "before_sha256": actual}
    return check


def describe_input(path: Path) -> dict:
    path = Path(path)
    return {"file": path.name, "bytes": path.stat().st_size if path.is_file() else None,
            "sha256": ocl_export.sha256_path(path) if path.is_file() else None}


def build_report(checks: list[Check], inputs: dict, target: dict) -> dict:
    return {
        "schema_version": 1,
        "target": target,
        "result": "pass" if all(check.status == "pass" for check in checks) else "fail",
        "inputs": inputs,
        "checks": [
            {"id": c.id, "description": c.description, "status": c.status, "failures": c.failures,
             "examples": c.examples, **({"info": c.info} if c.info else {})}
            for c in checks
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("update", "create"), default="update",
                        help="update: compare before and after; create: compare the export after a new load with the artifact")
    parser.add_argument("--before", type=Path, help="export of the Source before the update (update mode)")
    parser.add_argument("--after", type=Path, required=True, help="export of the Source after the update")
    parser.add_argument("--artifact", type=Path, required=True, help="bundle .ndjson, bulk-import zip, or directory of parts")
    parser.add_argument("--audit", type=Path, help="bulkimport_audit.json; checks it names the before export")
    parser.add_argument("--owner", default="WHO")
    parser.add_argument("--source", default="ICD-10-WHO")
    parser.add_argument("--locale", action="append", dest="locales", help="expected locale of an added name (repeatable)")
    parser.add_argument("--name-type", default=DEFAULT_NAME_TYPE)
    parser.add_argument("--report", type=Path, help="write the JSON report here")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        after = ocl_export.load_concepts(args.after, args.owner, args.source)
        artifact = read_artifact(args.artifact)
        if args.mode == "create":
            checks = verify_creation(after, artifact)
            inputs = {"after": describe_input(args.after), "artifact": describe_input(args.artifact)}
        else:
            if not args.before:
                raise ValueError("--before is required in update mode")
            before = ocl_export.load_concepts(args.before, args.owner, args.source)
            checks = verify(before, after, artifact, locales=tuple(args.locales or DEFAULT_LOCALES), name_type=args.name_type)
            extra = audit_check(args.audit, args.before)
            if extra:
                checks.insert(0, extra)
            inputs = {"before": describe_input(args.before), "after": describe_input(args.after),
                      "artifact": describe_input(args.artifact)}
        if args.audit:
            inputs["audit"] = describe_input(args.audit)
        report = build_report(checks, inputs, {"owner": args.owner, "source": args.source, "mode": args.mode})
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for check in checks:
        print(f"[{check.status.upper():4}] {check.id}: {check.description}"
              + (f"  ({check.failures} failures)" if check.failures else ""))
        for example in check.examples[:3]:
            print(f"        e.g. {example}")
    print(f"result: {report['result'].upper()}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"report: {args.report}")
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
