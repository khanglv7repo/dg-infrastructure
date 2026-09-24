from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SECURITY_XML = ROOT / "docker" / "trino" / "etc" / "ranger-trino-security.xml"


def _properties() -> dict[str, str]:
    root = ET.parse(SECURITY_XML).getroot()
    result: dict[str, str] = {}
    for prop in root.findall("property"):
        name = prop.findtext("name")
        value = prop.findtext("value")
        if name:
            result[name] = value or ""
    return result


def test_ranger_group_mapping_is_additive_not_exclusive() -> None:
    props = _properties()

    assert props["ranger.plugin.trino.use.rangerGroups"] == "true"
    assert props["ranger.plugin.trino.use.only.rangerGroups"] == "false"


def test_trino_uses_expected_ranger_resource_service() -> None:
    props = _properties()
    assert props["ranger.plugin.trino.service.name"] == "dev_trino"
