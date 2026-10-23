#!/usr/bin/env python3
"""Compare the documented local HP500 FA/FS pair; no execution or download."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from inspect_rbn import inflate_main, partitions, sha256


EXPECTED = {
    "FA": "5c034fa7740eaf4ab30949faa45addd4270ff2fd79dc81069fe3d2926280b98f",
    "FS": "f9701b228b955ff8841974f9f5dba85fddd9a980b1c8d56aa32705462571cea0",
}


def compare(directory):
    parts, mains, inputs = {}, {}, {}
    for tag in ("FA", "FS"):
        name = f"P1L1{tag}2443AR.rbn"
        data = (directory / name).read_bytes()
        if sha256(data) != EXPECTED[tag]:
            raise ValueError(f"unexpected {tag} package")
        parts[tag] = partitions(data)
        mains[tag], _ = inflate_main(parts[tag]["FIRMWARE"][2])
        inputs[tag] = {
            "url": f"https://d1te6mvvpy6zcm.cloudfront.net/firmwares/HP500-P1L1{tag}/{name}",
            "file": name, "sha256": sha256(data), "md5": hashlib.md5(data).hexdigest(),
            "size": len(data), "main_size": len(mains[tag]),
            "main_sha256": sha256(mains[tag]),
            "main_code_copy_length": struct.unpack_from("<I", mains[tag], 0x1F8)[0],
        }
    names = sorted(set(parts["FA"]) | set(parts["FS"]))
    resources = {name: {
        "identical_payload": parts["FA"].get(name, (0, 0, None))[2] == parts["FS"].get(name, (0, 0, None))[2],
        **{tag: {"size": len(parts[tag][name][2]), "sha256": sha256(parts[tag][name][2])}
           for tag in ("FA", "FS") if name in parts[tag]},
    } for name in names}
    strings = {tag: set(re.findall(rb"[\x20-\x7e]{8,}", main)) for tag, main in mains.items()}
    return {
        "scope": "Different Sprocket family; not an exact Select FA image or compatibility test",
        "vendor_signature_verified": False, "inputs": inputs, "partitions": resources,
        "differing_partition_payloads": [name for name in names if not resources[name]["identical_payload"]],
        "exclusive_printable_strings_min8": {
            tag: [s.decode("ascii") for s in sorted(strings[tag] - strings[other])]
            for tag, other in (("FA", "FS"), ("FS", "FA"))},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(json.dumps(compare(parser.parse_args().directory), indent=2))
