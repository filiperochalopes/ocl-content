"""ICD-10-CM FY27 XML/order inputs to manual OCL bulk-import artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOLS = str(Path(__file__).resolve().parents[4] / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

from ocl_artifacts import upload_ready_map, DEFAULT_METHOD, DEFAULT_PART_BYTES, METHODS, build_manifest, create_archive, sha256_file, write_bundle, write_json, write_parts
from ocl_pipeline_loader import load
import ocl_export as export_reader

TERMINOLOGY = "us-nchs/icd-10-cm"


def pipeline(module: str): return load(TERMINOLOGY, module)

assets = pipeline("assets")
release_reader = pipeline("release")
builder = pipeline("build_bulkimport")
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
ASSETS = ROOT / "assets"
OUT = ROOT / "output"


def size(value: str) -> int:
    text=value.strip().lower(); units={"b":1,"kb":1024,"mb":1024**2,"gb":1024**3}
    for suffix, multiplier in units.items():
        if text.endswith(suffix) and text[:-len(suffix)].isdigit(): return int(text[:-len(suffix)])*multiplier
    if text.isdigit(): return int(text)
    raise argparse.ArgumentTypeError("size must look like 2mb")


def relative(path: Path) -> str:
    try: return Path(path).resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError: return Path(path).name


def args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    verify=sub.add_parser("verify-assets")
    verify.add_argument("--tabular",type=Path,default=assets.tabular_path(ASSETS)); verify.add_argument("--order",type=Path,default=assets.order_path(ASSETS))
    build=sub.add_parser("build")
    build.add_argument("--tabular",type=Path,default=assets.tabular_path(ASSETS)); build.add_argument("--order",type=Path,default=assets.order_path(ASSETS)); build.add_argument("--output-dir",type=Path,default=None)
    build.add_argument("--export",type=Path,help="Source export of the TARGET environment (export.json, NDJSON or a ZIP): builds an update that preserves what the release does not govern")
    build.add_argument("--environment",choices=("local","staging","production"),help="target environment of this bundle; required with --export. local/staging write under exports/<environment>/build/icd10cm and carry the environment in the file names")
    build.add_argument("--max-part-size",type=size,default=DEFAULT_PART_BYTES); build.add_argument("--zip-method",choices=sorted(METHODS),default=DEFAULT_METHOD); build.add_argument("--no-archive",action="store_true")
    return parser.parse_args(argv)


def command_build(ns):
    if bool(ns.export)!=bool(ns.environment): raise ValueError("--export and --environment must be given together")
    assets.verify_local(ns.tabular,ns.order)
    release=release_reader.read(ns.tabular,ns.order); result=builder.build(release)
    env=ns.environment; update=None; export_meta=None; lines=result.lines
    if ns.export:
        existing=export_reader.load_concepts(ns.export,builder.TARGET_OWNER,builder.TARGET_SOURCE)
        update=builder.project_update(result,existing); lines=update.lines
        export_meta={"role":"target-export","environment":env,"path":relative(ns.export),"sha256":sha256_file(ns.export),"concepts":len(existing)}
    if ns.output_dir is not None: out=Path(ns.output_dir)
    elif env in ("local","staging"): out=REPO/"exports"/env/"build"/"icd10cm"
    else: out=OUT
    suffix=f".{env}" if env in ("local","staging") else ""
    bundle_name=f"bulkimport_icd10cm{suffix}.bundle.zip"; parts_name=f"bulkimport_icd10cm{suffix}.parts.zip"
    parts=write_parts(out,lines,ns.max_part_size); bundle=write_bundle(out,lines)
    target={"owner":builder.TARGET_OWNER,"source":builder.TARGET_SOURCE,"owner_type":builder.OWNER_TYPE}
    mode="source-export" if update else "full-source-refresh"
    ready=upload_ready_map(False,"pending tasks: no --export; legacy extras, CUI and semantic types would be overwritten; open decisions in TBD.md")
    if update:
        ready=upload_ready_map(False,"pending tasks: local rehearsal not run")
        if env=="local": ready["local"]={"status":True,"comment":"built from the local export; rehearse it, then verify with ocl_verify_update.py"}
        else: ready[env]={"status":False,"comment":f"bundle built from the {env} export; pending local rehearsal evidence and the TBD.md decisions"}
    ba=pa=None
    if not ns.no_archive:
        manifest=build_manifest(target=target,mode=mode,upload_ready=ready,parts=[p.__dict__ for p in parts],bundle=bundle.__dict__,method=ns.zip_method,bundle_archive=bundle_name,parts_archive=parts_name)
        ba=create_archive(out,files=[out/bundle.name],archive_name=bundle_name,method=ns.zip_method)
        pa=create_archive(out,files=[out/p.zip for p in parts],manifest=manifest,archive_name=parts_name,method=ns.zip_method)
    warning=("Update built from a Source export of the target environment. Existing synonyms, descriptions, CUI, Semantic Types and instructional extras are preserved; ids absent from the release are reported, not retired. concept_class and hierarchy follow the pre-decision model (see TBD.md). Rehearse locally before any import." if update else "Draft full-source refresh. Compare against a fresh US-NCHS/ICD-10-CM staging snapshot and complete a local rehearsal before manual import.")
    inputs=[{"role":"tabular-xml","path":relative(ns.tabular),"sha256":sha256_file(ns.tabular),"bytes":ns.tabular.stat().st_size,"url":assets.TABULAR.url},{"role":"order-file","path":relative(ns.order),"sha256":sha256_file(ns.order),"bytes":ns.order.stat().st_size,"url":assets.ORDER.url}]
    if export_meta: inputs.append(export_meta)
    omitted=["mappings","external_id","CUI","Semantic Types"] if update else ["mappings","CUI","semantic types","instructional notes","descriptions"]
    audit={"schema_version":1,"target":target,"environment":env,"mode":mode,"upload_ready":ready,"warning":warning,"inputs":inputs,"read":{"version":release.version,"chapters":result.chapter_nodes,"sections":result.section_nodes,"concrete_codes":result.diagnosis_codes,"lines":len(lines)},"projection":{"included":["id","names","concept_class","datatype","retired","extras","parent_concept_urls"],"omitted":omitted,"extension_parent_rule":"longest explicit XML diagnosis stem"},"output":{"parts":[p.__dict__ for p in parts],"bundle":bundle.__dict__,"bundle_archive":None if not ba else {"name":ba.name,"sha256":sha256_file(out/ba.name)},"parts_archive":None if not pa else {"name":pa.name,"sha256":sha256_file(out/pa.name)}},"upload":{"mechanism":"manual","api_upload":False,"update_existing_required":True}}
    if update:
        audit["update"]={**update.stats,"umls_policy":"temporary policy, every environment: no UMLS; CUI/Semantic Types dropped and T001-T204 retired until the TBD.md decision says otherwise","not_in_release":{k:len(v) for k,v in update.not_in_release.items()},"retirement":"T001-T204 only (UMLS Semantic Type ids); the 41 synthetic ranges and 33 extension codes are reported, not retired (TBD.md)"}
        audit["not_in_release_ids"]=update.not_in_release
    write_json(out/"bulkimport_audit.json",audit)
    print(f"FY{release.version[-2:]}: {len(lines):,} lines ({result.chapter_nodes} chapters, {result.section_nodes} sections, {result.diagnosis_codes} codes) mode={mode} environment={env}")
    if update: print("update:",json.dumps(audit["update"]))
    print(f"parts: {len(parts)} bundle: {bundle.name} ({bundle.bytes:,} bytes) -> {out}")


def main(argv=None):
    ns=args(argv)
    try:
        if ns.command=="verify-assets": assets.verify_local(ns.tabular,ns.order); print("ok: both FY27 assets hash-verified")
        else: command_build(ns)
        return 0
    except (OSError,ValueError,KeyError) as error:
        print(f"error: {error}",file=sys.stderr); return 1

if __name__=="__main__": raise SystemExit(main())
