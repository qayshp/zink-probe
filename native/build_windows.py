"""Reuse PAPPL's pinned native dependency project; build our small front end."""

import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(sys.argv[1]).resolve()
namespace = "http://schemas.microsoft.com/developer/msbuild/2003"
ET.register_namespace("", namespace)
tree = ET.parse(root / "vcnet/testpappl.vcxproj")
for node in tree.iter():
    if node.text:
        node.text = node.text.replace("testpappl", "zink-ipp")
for group in tree.findall(f"{{{namespace}}}ItemGroup"):
    for node in list(group):
        if node.tag == f"{{{namespace}}}ClCompile":
            group.remove(node)
group = ET.SubElement(tree.getroot(), f"{{{namespace}}}ItemGroup")
ET.SubElement(group, f"{{{namespace}}}ClCompile", Include="select-app.c")
tree.write(root / "vcnet/zink-ipp.vcxproj", encoding="utf-8", xml_declaration=True)
shutil.copyfile(Path(__file__).with_name("select-app.c"), root / "vcnet/select-app.c")
