"""Build only the checked public tree, never the investigation workspace."""
import hashlib,json,zipfile
from pathlib import Path
from check_public import ROOT,check
files=check()
manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.name!='RELEASE_MANIFEST.json'}
(ROOT/'RELEASE_MANIFEST.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
version=json.loads((ROOT/'custom_components/switchbot_frame_control/manifest.json').read_text())['version']
output=ROOT/'dist'/f'home-assistant-switchbot-art-frame-{version}.zip';output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
    for path in check():archive.write(path,path.relative_to(ROOT))
print(f'Built {output.name}; {output.stat().st_size} bytes; SHA256 {hashlib.sha256(output.read_bytes()).hexdigest()}')
