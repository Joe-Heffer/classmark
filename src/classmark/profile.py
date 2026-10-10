"""Build a compact text state describing a dataset, using deterministic extraction only.

The state is what every backend sees. It contains:

* ``title`` and ``description`` (when known)
* ``files``: count, total size, extension counts and a listing with sizes and MIME types
* ``tables``: header and a few sample rows from CSV/TSV files
* ``readme`` and ``licence_file``: the start of README and LICENCE files
* ``scientific_metadata``: netCDF/HDF5 global attributes and variable names

Remote files are read with HTTP Range requests, so only their first few
kilobytes are downloaded. netCDF/HDF5 headers need the whole file, so they are
only read for files under ``config.SCIENTIFIC_FILE_MAX_BYTES``.

The state is capped at ``config.STATE_CAP_CHARS`` characters of JSON. When it
is too long, sections are shortened in a fixed order and every shortening is
recorded in the profile metadata (which is not sent to the model).
"""

import csv
import io
import json
import mimetypes
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from classmark import config

PROFILER_VERSION = "1"
TRUNCATION_MARK = " …[truncated]"

README_STEMS = ("readme",)
LICENCE_STEMS = ("licence", "license", "copying")
TEXT_EXT = {"", "md", "txt", "rst", "markdown"}
TABLE_EXT = {"csv": ",", "tsv": "\t"}
NETCDF_EXT = {"nc", "nc4", "cdf"}
HDF5_EXT = {"h5", "hdf5", "he5", "hdf"}

MAGIC = [
    (b"%PDF", "application/pdf"),
    (b"\x89PNG", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x1f\x8b", "application/gzip"),
    (b"\x89HDF", "application/x-hdf5"),
    (b"CDF\x01", "application/x-netcdf"),
    (b"CDF\x02", "application/x-netcdf"),
]


@dataclass
class FileEntry:
    name: str
    size: int
    url: str | None = None  # remote file
    path: Path | None = None  # local file


@dataclass
class Profile:
    state: dict
    meta: dict


def ext_of(name: str) -> str:
    base = name.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def stem_of(name: str) -> str:
    return name.rsplit("/", 1)[-1].split(".", 1)[0].lower()


def human_size(n: int) -> str:
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n} B"


def mime_type(name: str, head: bytes | None = None) -> str:
    guessed, _ = mimetypes.guess_type(name)
    if guessed:
        return guessed
    if head:
        for sig, mime in MAGIC:
            if head.startswith(sig):
                return mime
        try:
            if head[:512].decode("utf-8").isprintable() or "\n" in head[:512].decode("utf-8"):
                return "text/plain"
        except UnicodeDecodeError:
            pass
    if ext_of(name) in NETCDF_EXT:
        return "application/x-netcdf"
    if ext_of(name) in HDF5_EXT:
        return "application/x-hdf5"
    return "unknown"


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + TRUNCATION_MARK


def decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").replace("\x00", "")


def parse_table(data: bytes, delimiter: str, complete: bool) -> dict | None:
    text = decode(data)
    if not complete and "\n" in text:
        text = text[: text.rfind("\n")]  # drop the partial last line
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return None
    clip = lambda r: [truncate(c, config.CELL_CAP_CHARS) for c in r[: config.MAX_TABLE_COLUMNS]]
    table = {"columns": clip(rows[0]), "sample_rows": [clip(r) for r in rows[1 : 1 + config.SAMPLE_ROWS]]}
    if len(rows[0]) > config.MAX_TABLE_COLUMNS:
        table["columns_shown"] = f"{config.MAX_TABLE_COLUMNS} of {len(rows[0])}"
    return table


def scientific_attributes(path: Path, ext: str) -> dict | None:
    """Global attributes and variable names from a netCDF or HDF5 file, if readable."""
    try:
        if ext in NETCDF_EXT:
            import netCDF4

            with netCDF4.Dataset(path) as ds:
                attrs = {k: str(ds.getncattr(k)) for k in ds.ncattrs()}
                variables = {
                    name: " ".join(
                        str(getattr(v, a)) for a in ("long_name", "units") if hasattr(v, a)
                    )
                    for name, v in ds.variables.items()
                }
        else:
            import h5py

            with h5py.File(path, "r") as f:
                attrs = {k: str(v) for k, v in f.attrs.items()}
                variables = {}
                f.visititems(
                    lambda name, obj: variables.setdefault(name, str(getattr(obj, "shape", "")))
                    if isinstance(obj, h5py.Dataset) else None
                )
    except ImportError:
        return {"note": "netCDF4/h5py not installed; install the 'scientific' extra"}
    except Exception as e:  # unreadable or not really netCDF/HDF5
        return {"note": f"could not read: {type(e).__name__}"}
    cap = config.MAX_ATTRIBUTES
    return {
        "global_attributes": {k: truncate(v, 200) for k, v in list(attrs.items())[:cap]},
        "variables": {k: truncate(v, 80) for k, v in list(variables.items())[:cap]},
    }


def build_state(
    title: str | None,
    description: str | None,
    files: list[FileEntry],
    read_head: Callable[[FileEntry, int], bytes | None],
    local_copy: Callable[[FileEntry], Path | None],
    exclude: list[str] = (),
    cap: int = config.STATE_CAP_CHARS,
) -> Profile:
    meta = {"profiler_version": PROFILER_VERSION, "cap_chars": cap, "truncated": [], "notes": []}
    state: dict = {}
    if title:
        state["title"] = title.strip()
    if description:
        state["description"] = truncate(description, config.DESCRIPTION_CAP_CHARS)
        if len(description.strip()) > config.DESCRIPTION_CAP_CHARS:
            meta["truncated"].append(f"description to {config.DESCRIPTION_CAP_CHARS} chars")

    heads: dict[str, bytes] = {}
    readme = licence = None
    tables, scientific = [], []
    for f in sorted(files, key=lambda f: f.name.lower()):
        ext, stem = ext_of(f.name), stem_of(f.name)
        if readme is None and stem.startswith(README_STEMS) and ext in TEXT_EXT:
            data = read_head(f, config.TEXT_FETCH_BYTES)
            if data is not None:
                heads[f.name] = data
                readme = {"file": f.name, "text": truncate(decode(data), config.README_CAP_CHARS)}
        elif licence is None and stem.startswith(LICENCE_STEMS) and ext in TEXT_EXT:
            data = read_head(f, config.TEXT_FETCH_BYTES)
            if data is not None:
                heads[f.name] = data
                licence = {"file": f.name, "text": truncate(decode(data), config.LICENCE_CAP_CHARS)}
        elif ext in TABLE_EXT and len(tables) < config.MAX_TABLES:
            data = read_head(f, config.TABLE_FETCH_BYTES)
            if data is not None:
                heads[f.name] = data
                table = parse_table(data, TABLE_EXT[ext], complete=len(data) >= f.size)
                if table:
                    tables.append({"file": f.name, **table})
        elif ext in NETCDF_EXT | HDF5_EXT and len(scientific) < config.MAX_TABLES:
            if f.size > config.SCIENTIFIC_FILE_MAX_BYTES:
                meta["notes"].append(f"{f.name}: too large to read attributes ({human_size(f.size)})")
                continue
            path = local_copy(f)
            if path is not None:
                attrs = scientific_attributes(path, ext)
                if attrs:
                    scientific.append({"file": f.name, **attrs})

    exts: dict[str, int] = {}
    for f in files:
        key = ext_of(f.name) or "(none)"
        exts[key] = exts.get(key, 0) + 1
    def head_for_mime(f: FileEntry) -> bytes | None:
        # Local files with an unrecognised extension are sniffed by magic bytes;
        # remote files are not fetched just for this.
        if f.name in heads or f.path is None or mimetypes.guess_type(f.name)[0]:
            return heads.get(f.name)
        return read_head(f, 8)

    listing = [
        f"{f.name} | {human_size(f.size)} | {mime_type(f.name, head_for_mime(f))}"
        for f in sorted(files, key=lambda f: -f.size)[: config.MAX_LISTED_FILES]
    ]
    state["files"] = {
        "count": len(files),
        "total_size": human_size(sum(f.size for f in files)),
        "extensions": dict(sorted(exts.items(), key=lambda kv: -kv[1])),
        "listing (largest first)": listing,
    }
    if len(files) > config.MAX_LISTED_FILES:
        state["files"]["listing_note"] = f"{config.MAX_LISTED_FILES} of {len(files)} files listed"
    if tables:
        state["tables"] = tables
    if readme:
        state["readme"] = readme
    if licence:
        state["licence_file"] = licence
    if scientific:
        state["scientific_metadata"] = scientific

    for section in exclude:
        if state.pop(section, None) is not None:
            meta["notes"].append(f"excluded section '{section}' for this experiment")
    enforce_cap(state, cap, meta)
    meta["state_chars"] = len(state_json(state))
    return Profile(state=state, meta=meta)


def state_json(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False)


def enforce_cap(state: dict, cap: int, meta: dict) -> None:
    """Shorten sections in a fixed order until the JSON state fits within ``cap`` characters."""

    def shrink_text(path: tuple[str, ...], limit: int):
        def step():
            obj = state
            for key in path[:-1]:
                obj = obj.get(key) if isinstance(obj, dict) else None
                if obj is None:
                    return False
            if isinstance(obj, dict) and isinstance(obj.get(path[-1]), str) and len(obj[path[-1]]) > limit:
                obj[path[-1]] = truncate(obj[path[-1]].removesuffix(TRUNCATION_MARK), limit)
                return True
            return False
        return step, f"{'.'.join(path)} to {limit} chars"

    def trim_list(getter, keep: int, label: str):
        def step():
            items = getter()
            if items is not None and len(items) > keep:
                del items[keep:]
                return True
            return False
        return step, label

    def drop(section: str):
        return (lambda: state.pop(section, None) is not None), f"dropped {section}"

    def tables_rows(keep):
        def step():
            changed = False
            for t in state.get("tables", []):
                if len(t["sample_rows"]) > keep:
                    del t["sample_rows"][keep:]
                    changed = True
            return changed
        return step, f"table sample rows to {keep}"

    steps = [
        tables_rows(1),
        trim_list(lambda: state.get("tables"), 1, "tables to 1"),
        trim_list(lambda: state.get("scientific_metadata"), 1, "scientific_metadata to 1 file"),
        shrink_text(("readme", "text"), 600),
        shrink_text(("licence_file", "text"), 300),
        trim_list(lambda: state.get("files", {}).get("listing (largest first)"), 10, "file listing to 10"),
        shrink_text(("description",), 800),
        drop("scientific_metadata"),
        drop("tables"),
        shrink_text(("readme", "text"), 200),
        shrink_text(("description",), 300),
        drop("licence_file"),
        drop("readme"),
    ]
    for step, label in steps:
        if len(state_json(state)) <= cap:
            return
        if step():
            meta["truncated"].append(label)
    if len(state_json(state)) > cap:
        meta["notes"].append("state still exceeds cap after all shortening steps")


# --- Entry points --------------------------------------------------------------


def profile_record(record: dict, client, exclude: list[str] = (), cap: int = config.STATE_CAP_CHARS) -> Profile:
    """Profile a sampled Zenodo record (see ``classmark.sample``)."""
    files = [FileEntry(name=f["key"], size=f["size"], url=f["url"]) for f in record["files"]]
    tmp = tempfile.TemporaryDirectory()

    def read_head(f: FileEntry, n: int) -> bytes | None:
        try:
            return client.get_range(f.url, n)
        except Exception:
            return None

    def local_copy(f: FileEntry) -> Path | None:
        try:
            r = client.get(f.url)
            r.raise_for_status()
        except Exception:
            return None
        p = Path(tmp.name) / f"file.{ext_of(f.name)}"
        p.write_bytes(r.content)
        return p

    try:
        profile = build_state(record.get("title"), record.get("description"), files,
                              read_head, local_copy, exclude, cap)
    finally:
        tmp.cleanup()
    profile.meta["source"] = record.get("url") or record.get("doi")
    return profile


def profile_folder(
    folder: Path,
    title: str | None = None,
    description: str | None = None,
    exclude: list[str] = (),
    cap: int = config.STATE_CAP_CHARS,
) -> Profile:
    """Profile a local folder. Nothing is sent anywhere."""
    folder = Path(folder)
    files = [
        FileEntry(name=str(p.relative_to(folder)), size=p.stat().st_size, path=p)
        for p in sorted(folder.rglob("*"))
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(folder).parts)
    ]

    def read_head(f: FileEntry, n: int) -> bytes:
        with f.path.open("rb") as fh:
            return fh.read(n)

    profile = build_state(title, description, files, read_head, lambda f: f.path, exclude, cap)
    profile.meta["source"] = str(folder)
    return profile
