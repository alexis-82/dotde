"""Every translation key used in the code exists in English and Italian, with the same placeholders."""

import json
import re
from importlib import resources
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "dotde"
DYNAMIC = {
    "pkg.source.native", "pkg.source.aur", "pkg.source.flatpak", "pkg.source.snap",
    "mode.immediate", "mode.deferred", "mode.offline",
    "reason.forbidden_path", "reason.excluded", "reason.outside_category", "reason.unknown_category", "reason.symlink", "reason.conflict",
    "pkg.reason_other_distro", "pkg.reason_no_aur_helper", "pkg.reason_missing_tool",
}


def catalog(lang):
    return json.loads(resources.files("dotde").joinpath("locales", f"{lang}.json").read_text("utf-8"))


def used_keys():
    keys = set(DYNAMIC)
    for f in SRC.glob("*.py"):
        text = f.read_text()
        keys |= set(re.findall(r"""\bt\(\s*["']([a-z_]+\.[a-z_.]+)["']""", text))
        keys |= set(re.findall(r"""Notice\(\s*["']([a-z_]+\.[a-z_.]+)["']""", text))
    return keys


def test_all_keys_translated():
    en, it = catalog("en"), catalog("it")
    keys = used_keys()
    assert len(keys) > 50
    assert not keys - set(en), sorted(keys - set(en))
    assert not keys - set(it), sorted(keys - set(it))


def test_same_placeholders():
    en, it = catalog("en"), catalog("it")
    for key in set(en) & set(it):
        assert set(re.findall(r"{(\w+)}", en[key])) == set(re.findall(r"{(\w+)}", it[key])), key
