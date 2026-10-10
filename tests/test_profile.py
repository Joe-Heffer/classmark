import json

import pytest

from classmark import config
from classmark.profile import (
    TRUNCATION_MARK,
    FileEntry,
    build_state,
    human_size,
    mime_type,
    parse_table,
    profile_folder,
    state_json,
)


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "obs.csv").write_text("site,date,temp_c\nA,2020-01-01,3.2\nB,2020-01-02,4.1\n"
                                      "C,2020-01-03,5.0\nD,2020-01-04,6.3\n")
    (tmp_path / "README.md").write_text("# Weather observations\nDaily temperature in degrees Celsius.\n")
    (tmp_path / "LICENCE").write_text("Creative Commons Attribution 4.0 International\n")
    (tmp_path / "blob").write_bytes(b"\x89HDF\r\n\x1a\n" + b"\x00" * 8)
    (tmp_path / ".hidden").write_text("ignored")
    return tmp_path


def test_folder_profile_sections(folder):
    p = profile_folder(folder, title="Weather", description="Temperatures")
    s = p.state
    assert s["title"] == "Weather"
    assert s["files"]["count"] == 4  # hidden file skipped
    assert s["tables"][0]["columns"] == ["site", "date", "temp_c"]
    assert len(s["tables"][0]["sample_rows"]) == config.SAMPLE_ROWS
    assert "degrees Celsius" in s["readme"]["text"]
    assert s["licence_file"]["file"] == "LICENCE"
    assert p.meta["truncated"] == []
    assert p.meta["state_chars"] == len(state_json(s))


def test_magic_bytes_identify_unlabelled_file(folder):
    listing = profile_folder(folder).state["files"]["listing (largest first)"]
    assert any(line.startswith("blob") and "application/x-hdf5" in line for line in listing)


def test_exclude_section(folder):
    p = profile_folder(folder, exclude=["licence_file"])
    assert "licence_file" not in p.state
    assert any("licence_file" in n for n in p.meta["notes"])


def test_partial_table_drops_incomplete_last_line():
    data = b"a,b\n1,2\n3,4\n5,"  # cut off mid-row by a Range request
    table = parse_table(data, ",", complete=False)
    assert table["sample_rows"] == [["1", "2"], ["3", "4"]]


def test_long_cells_and_wide_tables_are_clipped():
    header = ",".join(f"c{i}" for i in range(config.MAX_TABLE_COLUMNS + 5))
    row = ",".join("x" * 100 for _ in range(config.MAX_TABLE_COLUMNS + 5))
    table = parse_table(f"{header}\n{row}\n".encode(), ",", complete=True)
    assert len(table["columns"]) == config.MAX_TABLE_COLUMNS
    assert table["sample_rows"][0][0].endswith(TRUNCATION_MARK)
    assert "columns_shown" in table


def test_state_respects_cap_and_records_truncation():
    files = [FileEntry(name=f"file_{i:03}.dat", size=1000 * i) for i in range(200)]
    p = build_state("T", "word " * 2000, files, lambda f, n: None, lambda f: None, cap=1500)
    assert len(state_json(p.state)) <= 1500
    assert p.meta["truncated"]  # description and listing were shortened
    assert p.state["files"]["count"] == 200  # the count stays exact


def test_cap_too_small_is_reported_not_hidden():
    files = [FileEntry(name="a" * 300 + ".csv", size=1)]
    p = build_state("T" * 400, None, files, lambda f, n: None, lambda f: None, cap=100)
    assert any("exceeds cap" in n for n in p.meta["notes"])


def test_large_scientific_files_are_skipped():
    big = FileEntry(name="model.nc", size=config.SCIENTIFIC_FILE_MAX_BYTES + 1)
    called = []
    p = build_state("T", None, [big], lambda f, n: None, lambda f: called.append(f) or None)
    assert not called
    assert any("too large" in n for n in p.meta["notes"])


def test_netcdf_attributes(tmp_path):
    netCDF4 = pytest.importorskip("netCDF4")
    path = tmp_path / "sst.nc"
    with netCDF4.Dataset(path, "w") as ds:
        ds.title = "Sea surface temperature"
        ds.createDimension("t", 2)
        v = ds.createVariable("sst", "f4", ("t",))
        v.units = "K"
        v.long_name = "sea surface temperature"
    sci = profile_folder(tmp_path).state["scientific_metadata"][0]
    assert sci["global_attributes"]["title"] == "Sea surface temperature"
    assert sci["variables"]["sst"] == "sea surface temperature K"


def test_mime_and_sizes():
    assert mime_type("x.csv") == "text/csv"
    assert mime_type("noext", b"%PDF-1.7") == "application/pdf"
    assert human_size(999) == "999 B"
    assert human_size(1_500_000) == "1.5 MB"


def test_state_is_json_serialisable(folder):
    json.dumps(profile_folder(folder).state)
