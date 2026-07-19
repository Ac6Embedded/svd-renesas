#!/usr/bin/env python3
"""Fetch Renesas CMSIS SVD files and organize them into <Family>/.

Sources:
  1. Renesas RA Device Family Pack (Keil MDK pack mirror at www2.renesas.eu).
     Version is taken from the newest <release> in the pdsc.
  2. GitHub release assets of renesas/rzt-fsp and renesas/rzn-fsp
     (RZ*_FSP_Packs_*.zip, SVDs live in nested Renesas.RZ*_mcu_*.pack files).

Incremental: every run starts with a cheap metadata check (the pdsc for
RA_DFP, the GitHub releases API for the RZ repos) and compares each upstream
version against the one recorded in manifest.json. Sources that did not
change are not downloaded and their files are left untouched. If nothing
changed at all the script prints 'up to date' and exits 0 without writing
anything. Deleting manifest.json (or the family dirs) forces a full rebuild.

Stdlib only, runs on Linux and Windows. Artifact downloads are cached in
.work/ and skipped when already present. Delete .work/ to force a fresh
download.
"""

import datetime
import io
import json
import os
import re
import shutil
import stat
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".work"
# SVD output base is the repo root itself: family dirs live at <root>/<Family>/.
SVD_BASE = ROOT
LIC_DIR = ROOT / "LICENSES"

# Never removed by the full-rebuild family-dir cleanup. Everything at the repo
# root that is not a family directory is listed here so clean_family_dirs()
# can never delete the repo itself, its git data, the script, or its metadata.
PROTECTED = {".git", ".github", ".gitignore", ".work",
             "LICENSES", "README.md", "manifest.json", "fetch.py"}


def _force_remove(func, path, _exc):
    """rmtree onerror handler: clear read-only bit (Windows) and retry."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def clean_family_dirs():
    """Full-rebuild cleanup: delete only family directories at the repo root.

    Removes every child directory of ROOT that is not in PROTECTED. It never
    targets ROOT, .git, .github, LICENSES or any repo metadata, so a full
    rebuild can never destroy the repository.
    """
    for child in ROOT.iterdir():
        if child.is_dir() and child.name not in PROTECTED:
            shutil.rmtree(child, onerror=_force_remove)

PDSC_URL = "https://www2.renesas.eu/Keil_MDK_Packs/Renesas.RA_DFP.pdsc"
PACK_BASE = "https://www2.renesas.eu/Keil_MDK_Packs/"
GH_API = "https://api.github.com/repos/renesas/{repo}/releases/latest"
GH_RAW_LICENSE = "https://raw.githubusercontent.com/renesas/{repo}/{tag}/LICENSE.md"

UA = {"User-Agent": "Mozilla/5.0"}
LICENSE_KEYS = ("license", "eula", "terms", "notice", "copying")

# (manifest source name, family directory at repo root)
SOURCE_DEFS = (
    ("Renesas.RA_DFP", "RA"),
    ("rzt-fsp", "RZT"),
    ("rzn-fsp", "RZN"),
)
SRC_BY_FAMILY = {family: name for name, family in SOURCE_DEFS}

# Prefixes used to attribute a manifest issue string to its source so that
# issues of unchanged sources survive an incremental update.
ISSUE_PREFIXES = {
    "Renesas.RA_DFP": ("RA_DFP", "Renesas.RA_DFP", "removed RA/"),
    "rzt-fsp": ("rzt-fsp", "removed RZT/"),
    "rzn-fsp": ("rzn-fsp", "removed RZN/"),
}

# URLs actually fetched as artifacts (packs / release zips) this run.
ARTIFACT_DOWNLOADS = []


def fetch_bytes(url, retries=3):
    headers = dict(UA)
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"download failed after {retries} tries: {url}: {last}")


def download(url, dest):
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  cached (no download): {dest.name}")
        return dest
    print(f"  ARTIFACT DOWNLOAD: {url}")
    ARTIFACT_DOWNLOADS.append(url)
    data = fetch_bytes(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"  saved {dest.name} ({len(data)} bytes)")
    return dest


def ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def validate_svd(path):
    """Return None if OK, else an error string."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        return f"XML parse error: {e}"
    tag = root.tag.split("}")[-1]
    if tag != "device":
        return f"root element is '{tag}', expected 'device'"
    return None


def check_ra():
    """Cheap metadata check: fetch only the pdsc, in memory.

    Returns (newest upstream version, parsed pdsc tree).
    """
    print(f"  metadata: {PDSC_URL}")
    tree = ET.ElementTree(ET.fromstring(fetch_bytes(PDSC_URL)))
    releases = tree.getroot().findall("./releases/release")
    if not releases:
        raise RuntimeError("no <release> elements in pdsc")
    version = max((r.get("version") for r in releases), key=ver_tuple)
    return version, tree


def check_rz(repo):
    """Cheap metadata check: latest release tag via the GitHub API.

    Returns (tag, release json).
    """
    url = GH_API.format(repo=repo)
    print(f"  metadata: {url}")
    rel = json.loads(fetch_bytes(url))
    return rel["tag_name"], rel


def fetch_ra(issues, covers, tree):
    """Download and extract the RA_DFP pack. Returns the manifest source entry."""
    print("== Source: Renesas.RA_DFP -> RA/ ==")
    root = tree.getroot()
    releases = root.findall("./releases/release")
    version = max((r.get("version") for r in releases), key=ver_tuple)
    lic_el = root.find("license")
    lic_text = (lic_el.text or "").strip() if lic_el is not None else None
    print(f"  newest release: {version}, pdsc <license> element: {lic_text!r}")

    # One SVD per family in this pack; a family covers several devices.
    # Record the full device list per SVD so also_covers can be filled in.
    parent = {c: p for p in root.iter() for c in p}
    for dbg in root.iter("debug"):
        svd_ref = dbg.get("svd")
        if svd_ref:
            fam_el = parent[dbg]
            covers[Path(svd_ref).name] = [
                d.get("Dname") for d in fam_el.iter("device")]

    pack_url = f"{PACK_BASE}Renesas.RA_DFP.{version}.pack"
    pack_path = download(pack_url, WORK / f"Renesas.RA_DFP.{version}.pack")

    out_dir = SVD_BASE / "RA"
    out_dir.mkdir(parents=True, exist_ok=True)
    LIC_DIR.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.svd"):
        old.unlink()
    for old in LIC_DIR.glob("RA_DFP-*"):
        old.unlink()

    count = 0
    lic_found = []
    with zipfile.ZipFile(pack_path) as z:
        for m in z.namelist():
            low = m.lower()
            if low.endswith(".svd") and m.startswith("SVD/"):
                name = Path(m).name
                (out_dir / name).write_bytes(z.read(m))
                count += 1
            base = Path(m).name.lower()
            if base and any(k in base for k in LICENSE_KEYS) and not m.endswith("/"):
                lic_found.append(m)
                dest = LIC_DIR / ("RA_DFP-" + Path(m).name)
                dest.write_bytes(z.read(m))
    print(f"  extracted {count} SVD files, license-like files in pack: {lic_found or 'NONE'}")
    if not lic_found:
        issues.append(
            "RA_DFP: pdsc <license> element is empty and no license/EULA/terms "
            "file exists inside the pack. No redistribution grant found."
        )
    return {
        "name": "Renesas.RA_DFP",
        "url": pack_url,
        "version": version,
        "license": "UNSPECIFIED (empty <license> element in pdsc"
                   + (", no license file in pack)" if not lic_found
                      else f", pack contains: {', '.join(lic_found)})"),
        "files": count,
    }


def fetch_rz(repo, family, issues, rel):
    """Download and extract one RZ FSP release. Returns the source entry or None."""
    print(f"== Source: {repo} -> {family}/ ==")
    tag = rel["tag_name"]
    asset = None
    for a in rel["assets"]:
        if re.fullmatch(r"RZ[TN]_FSP_Packs_.*\.zip", a["name"]):
            asset = a
            break
    if asset is None:
        issues.append(f"{repo}: no RZ*_FSP_Packs_*.zip asset in release {tag}, skipped")
        return None
    zip_path = download(asset["browser_download_url"], WORK / asset["name"])

    out_dir = SVD_BASE / family
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.svd"):
        old.unlink()
    count = 0
    with zipfile.ZipFile(zip_path) as z:
        mcu_packs = [m for m in z.namelist()
                     if re.search(r"Renesas\.RZ[TN]_mcu_.*\.pack$", m)]
        for pack_member in mcu_packs:
            with zipfile.ZipFile(io.BytesIO(z.read(pack_member))) as inner:
                for m in inner.namelist():
                    if m.lower().endswith(".svd"):
                        name = Path(m).name
                        (out_dir / name).write_bytes(inner.read(m))
                        count += 1
    print(f"  extracted {count} SVD files from {len(mcu_packs)} mcu packs")

    # License: repo LICENSE.md at the release tag. The nested mcu packs
    # themselves carry no license file (checked); LICENSE.md covers the packs.
    LIC_DIR.mkdir(parents=True, exist_ok=True)
    try:
        lic = fetch_bytes(GH_RAW_LICENSE.format(repo=repo, tag=tag))
        (LIC_DIR / f"{repo}-LICENSE.md").write_bytes(lic)
    except RuntimeError as e:
        issues.append(f"{repo}: could not fetch LICENSE.md at {tag}: {e}")

    return {
        "name": repo,
        "url": asset["browser_download_url"],
        "version": tag,
        "license": "BSD-3-Clause for Renesas BSP components per repo LICENSE.md "
                   "(no license file inside the mcu packs themselves)",
        "files": count,
    }


def issue_owner(text):
    """Map a manifest issue string to the source it belongs to, or None."""
    for name, prefixes in ISSUE_PREFIXES.items():
        if any(text.startswith(p) for p in prefixes):
            return name
    return None


def main():
    mpath = ROOT / "manifest.json"
    old_manifest = None
    if mpath.exists():
        try:
            old_manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"manifest.json unreadable ({e}), doing a full rebuild")
    old_sources = {s.get("name"): s
                   for s in (old_manifest or {}).get("sources", [])}

    # Phase 1: cheap metadata check only. No artifact is downloaded here.
    print("== Metadata check ==")
    contexts = {}
    changed = []
    for name, family in SOURCE_DEFS:
        if name == "Renesas.RA_DFP":
            upstream, ctx = check_ra()
        else:
            upstream, ctx = check_rz(name)
        contexts[name] = ctx
        recorded = old_sources.get(name, {}).get("version")
        have_files = any((SVD_BASE / family).glob("*.svd"))
        need = old_manifest is None or recorded != upstream or not have_files
        print(f"  {name}: recorded={recorded} upstream={upstream} "
              f"[{'update needed' if need else 'up to date'}]")
        if need:
            changed.append((name, family))

    if not changed:
        print(f"artifact downloads this run: {len(ARTIFACT_DOWNLOADS)}")
        print("up to date")
        return 0

    # Phase 2: download and re-extract only the changed sources.
    issues = []
    covers = {}
    new_entries = {}
    changed_families = set()
    # A missing manifest means a full rebuild: every source is in `changed`
    # and will be re-extracted below, so clear the existing family dirs first.
    # This only ever deletes family directories, never ROOT or PROTECTED
    # entries. The incremental path (manifest present) is left untouched and
    # still deletes only the individual files owned by each changed source.
    if old_manifest is None:
        clean_family_dirs()
    for name, family in changed:
        try:
            if name == "Renesas.RA_DFP":
                entry = fetch_ra(issues, covers, contexts[name])
            else:
                entry = fetch_rz(name, family, issues, contexts[name])
        except Exception as e:  # noqa: BLE001
            issues.append(f"{name}: failed, skipped: {e}")
            print(f"  WARNING: {name} failed: {e}")
            entry = None
        if entry is not None:
            new_entries[name] = entry
            changed_families.add(family)

    # Phase 3: validate the refreshed families; reuse manifest entries for
    # untouched families so their metadata (also_covers etc.) is preserved.
    print("== Validation ==")
    old_by_path = {f["path"]: f
                   for f in (old_manifest or {}).get("files", [])}
    files = []
    total_bytes = 0
    # Scan only the family directories at the repo root (skip PROTECTED
    # entries such as .git, .github and LICENSES now that the base is ROOT).
    svd_paths = [p for child in SVD_BASE.iterdir()
                 if child.is_dir() and child.name not in PROTECTED
                 for p in child.glob("*.svd")]
    for svd in sorted(svd_paths):
        rel = svd.relative_to(ROOT).as_posix()
        family = svd.parent.name
        if family not in changed_families and rel in old_by_path:
            files.append(old_by_path[rel])
            total_bytes += svd.stat().st_size
            continue
        err = validate_svd(svd)
        if err:
            issues.append(f"removed {rel}: {err}")
            print(f"  REMOVED {rel}: {err}")
            svd.unlink()
            continue
        total_bytes += svd.stat().st_size
        entry = {
            "path": rel,
            "device": svd.stem,
            "family": family,
            "source": SRC_BY_FAMILY.get(family, "unknown"),
            "provenance": "pristine",
        }
        also = [d for d in covers.get(svd.name, []) if d != svd.stem]
        if also:
            entry["also_covers"] = also
        files.append(entry)

    # Keep issues that belong to sources this run did not touch.
    changed_names = {name for name, _ in changed}
    kept = [i for i in (old_manifest or {}).get("issues", [])
            if issue_owner(i) not in changed_names]
    issues = kept + issues

    sources = []
    for name, _family in SOURCE_DEFS:
        if name in new_entries:
            sources.append(new_entries[name])
        elif name in old_sources:
            sources.append(old_sources[name])

    manifest = {
        "vendor": "Renesas",
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
        "sources": sources,
        "files": files,
        "stats": {
            "total_files": len(files),
            "total_bytes": total_bytes,
        },
    }
    if issues:
        manifest["issues"] = issues
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Total: {len(files)} files, {total_bytes / 1e6:.1f} MB")
    for i in issues:
        print(f"ISSUE: {i}")
    print(f"artifact downloads this run: {len(ARTIFACT_DOWNLOADS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
