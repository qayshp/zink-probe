"""Audited, exact-source fixes for our pinned PAPPL snapshot only.

The upstream driver structure has copies_supported, but its IPP advertising and
validation still hardcode 999 for non-streaming formats. Honor the driver bound.
No reference checkout is changed: this runs only on CI's build source copy.
"""

from pathlib import Path


def patch(root):
    path = Path(root) / "pappl/printer-ipp.c"
    source = path.read_text()
    replacements = {
        'ippAddRange(client->response, IPP_TAG_PRINTER, "copies-supported", 1, 999);': 'ippAddRange(client->response, IPP_TAG_PRINTER, "copies-supported", 1, data->copies_supported);',
        "if (intvalue < 1 || intvalue > 999)": "if (intvalue < 1 || intvalue > driver_data.copies_supported)",
        "ippGetInteger(attr, 0) < 1 || ippGetInteger(attr, 0) > 999)": "ippGetInteger(attr, 0) < 1 || ippGetInteger(attr, 0) > printer->driver_data.copies_supported)",
    }
    for before, after in replacements.items():
        if source.count(before) != 1:
            raise ValueError(f"Pinned PAPPL patch precondition changed: {before}")
        source = source.replace(before, after)
    path.write_text(source)
