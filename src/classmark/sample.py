"""Draw a stratified sample of public Zenodo records with DataCite labels.

Labels come from DataCite (what the depositor entered, as registered). File
listings and descriptions come from the Zenodo REST API. The sample is written
to ``data/<experiment>/records.jsonl`` with the queries used in ``query.json``.
DataCite's random sampling is not seedable, so the stored records file, not the
query, is the reproducible artefact.

Depositor-entered labels are noisy. Each record gets ``noise_flags`` from simple
heuristics, and a ``handcheck.csv`` is written for manual labelling.
"""

import csv
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path

from classmark import config
from classmark.questions import QuestionSet, load_question_set
from classmark.sources import (
    DATACITE_API,
    PoliteClient,
    datacite_search,
    html_to_text,
    zenodo_record,
    zenodo_record_id,
)

FOS_SCHEME = "Fields of Science and Technology (FOS)"
HANDCHECK_SIZE = 50

# File-extension groups used by the label-noise heuristics.
DATA_EXT = {
    "csv",
    "tsv",
    "xlsx",
    "xls",
    "ods",
    "json",
    "nc",
    "nc4",
    "h5",
    "hdf5",
    "he5",
    "mat",
    "npy",
    "npz",
    "parquet",
    "feather",
    "sav",
    "dta",
    "rds",
    "rdata",
    "sqlite",
    "db",
    "shp",
    "geojson",
    "gpkg",
    "fits",
    "dat",
    "xml",
    "jsonl",
}
CODE_EXT = {
    "py",
    "r",
    "m",
    "jl",
    "cpp",
    "c",
    "h",
    "java",
    "js",
    "ts",
    "go",
    "rs",
    "ipynb",
    "sh",
    "f90",
    "f",
    "pl",
    "rb",
    "scala",
    "cs",
}
DOC_EXT = {"pdf", "doc", "docx", "odt", "ppt", "pptx", "odp", "epub", "tex"}
IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "tif", "tiff", "svg", "bmp", "webp"}
AV_EXT = {"mp4", "mov", "avi", "mkv", "webm", "m4v"}
SOUND_EXT = {"mp3", "wav", "flac", "ogg", "m4a", "aac"}
ARCHIVE_EXT = {"zip", "gz", "tgz", "tar", "7z", "bz2", "xz", "rar"}
TEXT_TYPES = {
    "Text",
    "JournalArticle",
    "Preprint",
    "Report",
    "Book",
    "BookChapter",
    "ConferencePaper",
    "Dissertation",
    "DataPaper",
}


def norm(s: str) -> str:
    """Normalise a vocabulary term for matching: lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


# --- Experiment-specific strata and labels ---------------------------------


def e1_strata(client: PoliteClient, qs: QuestionSet) -> list[tuple[str, str]]:
    """One stratum per resourceTypeGeneral value, most common first."""
    options = list(qs.questions["resource_type"].options)
    meta = client.get_json(
        DATACITE_API,
        params={"client-id": "cern.zenodo", "page[size]": 1, "disable-facets": "false", "facets": "resourceTypes"},
    )["meta"]
    counts = {norm(f["id"]): f["count"] for f in meta.get("resourceTypes", [])}
    options.sort(key=lambda o: -counts.get(norm(o), 0))
    return [(o, f"types.resourceTypeGeneral:{o}") for o in options if counts.get(norm(o))]


def fos_vocabulary(qs: QuestionSet) -> tuple[dict[str, str], dict[str, str]]:
    """Map normalised names to (top-level names) and (subfield name -> parent)."""
    tops = {norm(name): name for name in qs.hierarchy.options}
    parent_of = {}
    for top, node in qs.hierarchy.options.items():
        for child in node.children or {}:
            parent_of[norm(child)] = top
    return tops, parent_of


def e2_strata(client: PoliteClient, qs: QuestionSet) -> list[tuple[str, str]]:
    """One stratum per broad field, matching any of its FOS subjects, datasets only."""
    strata = []
    for top, node in qs.hierarchy.options.items():
        names = [top, *(node.children or {})]
        subjects = " OR ".join(f'"FOS: {n}"' for n in names)
        strata.append((top, f"types.resourceTypeGeneral:Dataset AND subjects.subject:({subjects})"))
    return strata


def datacite_fos(attrs: dict) -> list[str]:
    out = []
    for s in attrs.get("subjects") or []:
        subj = s.get("subject", "")
        if s.get("subjectScheme") == FOS_SCHEME or subj.startswith("FOS: "):
            out.append(subj.removeprefix("FOS: ").strip())
    return list(dict.fromkeys(out))


def labels_for(experiment: str, attrs: dict, qs: QuestionSet) -> dict:
    labels = {"resource_type_general": (attrs.get("types") or {}).get("resourceTypeGeneral")}
    if experiment.startswith("e2"):
        tops, parent_of = fos_vocabulary(qs)
        raw = datacite_fos(attrs)
        top_set, subs, unknown = [], [], []
        for name in raw:
            n = norm(name)
            if n in tops:
                top_set.append(tops[n])
            elif n in parent_of:
                subs.append(name)
                top_set.append(parent_of[n])
            else:
                unknown.append(name)
        labels["fos"] = {
            "top": list(dict.fromkeys(top_set)),
            "sub": subs,
            "raw": raw,
            "unrecognised": unknown,
        }
    return labels


def noise_flags(experiment: str, labels: dict, files: list[dict]) -> list[str]:
    """Heuristics for labels that look inconsistent with the record's own files."""
    flags = []
    exts = {extension(f["key"]) for f in files}
    if experiment.startswith("e1"):
        rt = labels.get("resource_type_general")
        if rt == "Dataset" and exts and exts <= DOC_EXT:
            flags.append("dataset_with_only_documents")
        if rt in TEXT_TYPES and exts & DATA_EXT and not exts & DOC_EXT:
            flags.append("text_type_with_data_files_and_no_documents")
        if rt == "Software" and not exts & (CODE_EXT | ARCHIVE_EXT):
            flags.append("software_without_code_or_archives")
        if rt == "Image" and not exts & (IMAGE_EXT | ARCHIVE_EXT):
            flags.append("image_without_image_files")
        if rt == "Audiovisual" and not exts & (AV_EXT | ARCHIVE_EXT):
            flags.append("audiovisual_without_video_files")
        if rt == "Sound" and not exts & (SOUND_EXT | ARCHIVE_EXT):
            flags.append("sound_without_audio_files")
    if experiment.startswith("e2"):
        fos = labels["fos"]
        if len(fos["top"]) > 1:
            flags.append("multiple_fos_fields")
        if not fos["sub"]:
            flags.append("fos_broad_field_only")
        if len(fos["sub"]) > 2:
            flags.append("many_fos_subfields")
        if fos["unrecognised"]:
            flags.append("unrecognised_fos_term")
    return flags


STRATA = {"e1": e1_strata, "e2": e2_strata}


# --- Sampling ----------------------------------------------------------------


def build_record(experiment: str, item: dict, zen: dict, qs: QuestionSet, stratum: str) -> dict | None:
    meta = zen.get("metadata", {})
    if meta.get("access_right") != "open":
        return None
    files = [{"key": f["key"], "size": f.get("size", 0), "url": f["links"]["self"]} for f in zen.get("files") or []]
    if not files:
        return None
    attrs = item["attributes"]
    labels = labels_for(experiment, attrs, qs)
    return {
        "doi": item["id"],
        "zenodo_id": str(zen["id"]),
        "url": zen.get("links", {}).get("self_html"),
        "title": meta.get("title", ""),
        "description": html_to_text(meta.get("description", "")),
        "files": files,
        "labels": labels,
        # Depositor metadata kept for label-noise review; never placed in the state.
        "depositor": {
            "zenodo_resource_type": meta.get("resource_type"),
            "license": (meta.get("license") or {}).get("id"),
            "keywords": meta.get("keywords", []),
        },
        "noise_flags": noise_flags(experiment, labels, files),
        "stratum": stratum,
    }


def sample(experiment_name: str, n: int, out_dir: Path | None = None, oversample: int = 3) -> Path:
    qs = load_question_set(experiment_name)
    exp = qs.experiment
    key = exp.split("_")[0]
    out_dir = out_dir or config.DATA_DIR / exp
    out_dir.mkdir(parents=True, exist_ok=True)
    client = PoliteClient()

    strata = STRATA[key](client, qs)
    per_stratum = math.ceil(n / len(strata))
    pools: dict[str, list[dict]] = {}
    for name, query in strata:
        pools[name] = datacite_search(client, query, per_stratum * oversample)
        print(f"  {name}: {len(pools[name])} candidates")

    # Round-robin over strata so labels stay balanced where the pool allows.
    records, seen, concepts, checked = [], set(), set(), 0
    queues = {name: list(pool) for name, pool in pools.items()}
    while len(records) < n and any(queues.values()):
        for name in list(queues):
            if len(records) >= n:
                break
            while queues[name]:
                item = queues[name].pop(0)
                rid = zenodo_record_id(item["id"])
                if rid is None or item["id"] in seen:
                    continue  # concept DOIs and duplicates
                seen.add(item["id"])
                checked += 1
                zen = zenodo_record(client, rid)
                if not zen or zen.get("conceptrecid") in concepts:
                    continue  # another version of a record already sampled
                rec = build_record(exp, item, zen, qs, name)
                if rec:
                    concepts.add(zen.get("conceptrecid"))
                    records.append(rec)
                    break

    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (out_dir / "query.json").write_text(
        json.dumps(
            {
                "experiment": exp,
                "drawn_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "source": f"{DATACITE_API} (random=true, client-id=cern.zenodo) "
                "joined to https://zenodo.org/api/records/<id>",
                "strata": dict(strata),
                "requested": n,
                "candidates_checked": checked,
                "kept": len(records),
                "filters": [
                    "version DOIs only (no concept DOIs)",
                    "one version per Zenodo concept record",
                    "access_right == open",
                    "at least one file",
                ],
                "note": "DataCite random sampling has no seed; records.jsonl is the reproducible sample.",
            },
            indent=2,
        )
    )
    write_handcheck(out_dir, records, qs)
    return out_dir / "records.jsonl"


def write_handcheck(out_dir: Path, records: list[dict], qs: QuestionSet) -> None:
    """A CSV for manual labelling. Flagged records first, then the rest, up to the limit."""
    path = out_dir / "handcheck.csv"
    if path.exists():
        print(f"  {path} exists; not overwriting your labels")
        return
    chosen = sorted(records, key=lambda r: not r["noise_flags"])[:HANDCHECK_SIZE]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["doi", "url", "title", "depositor_label", "noise_flags", "checked_label", "notes"])
        for r in chosen:
            gold = r["labels"].get(qs.label)
            if isinstance(gold, dict):
                gold = "; ".join(gold["raw"])
            w.writerow([r["doi"], r["url"], r["title"], gold, " ".join(r["noise_flags"]), "", ""])


def load_records(experiment: str) -> list[dict]:
    path = config.DATA_DIR / experiment / "records.jsonl"
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_handcheck(experiment: str) -> dict[str, str]:
    """DOI -> hand-checked label, for rows where someone has filled ``checked_label``."""
    path = config.DATA_DIR / experiment / "handcheck.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {row["doi"]: row["checked_label"].strip() for row in csv.DictReader(f) if row["checked_label"].strip()}
