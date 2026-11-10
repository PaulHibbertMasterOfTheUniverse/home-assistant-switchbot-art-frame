"""Fail closed on unexpected release files or common private-data patterns."""
from pathlib import Path
import json,re,sys
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
ROOT_FILES={'.gitignore','README.md','LICENSE','THIRD_PARTY_NOTICES.md','CONTRIBUTING.md','hacs.json','requirements-test.txt','RELEASE_MANIFEST.json','CHANGELOG.md'}
SUFFIXES={'.py','.js','.cjs','.json','.md','.yaml','.yml','.txt'}
PATTERNS=[r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',r'gh[pousr]_[A-Za-z0-9]{20,}',
 r'AKIA[A-Z0-9]{16}',r'eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}',
 r'/(?:Users|Volumes)/',r'https?://[^\s"\x27]*\.ui\.nabu\.casa',
 r'(?<![\d.])(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\d.])']

def release_files():
    for path in sorted(ROOT.rglob('*')):
        rel=path.relative_to(ROOT)
        if any(part in {'.git','__pycache__','.venv','dist','.pytest_cache'} for part in rel.parts):continue
        if path.is_symlink():raise ValueError(f'Symlink is not allowed: {rel}')
        if path.is_file():yield path

def check():
    files=list(release_files())
    for path in files:
        rel=path.relative_to(ROOT)
        if len(rel.parts)==1 and rel.name not in ROOT_FILES:raise ValueError(f'Unexpected root file: {rel}')
        if len(rel.parts)>1 and rel.parts[0] not in {'custom_components','docs','tests','tools','.github','extras'}:raise ValueError(f'Unexpected directory: {rel}')
        if path.suffix=='.jpg':
            if str(rel) not in {'custom_components/switchbot_frame_control/examples/'+name for name in ('baby-asleep.jpg','blue-bin.jpg','black-bin.jpg','none-bin.jpg')}:raise ValueError('Unexpected image')
            with Image.open(path) as image:
                if image.getexif() or any(k in image.info for k in ('exif','comment','xmp','XML:com.adobe.xmp','icc_profile')):raise ValueError('Example photo contains metadata')
            continue
        if path.suffix not in SUFFIXES and rel.name not in {'LICENSE','.gitignore'}:raise ValueError(f'Unexpected binary or capture: {rel}')
        text=path.read_text()
        if any(re.search(pattern,text) for pattern in PATTERNS):raise ValueError(f'Potential private data: {rel}')
        if path.suffix=='.json':json.loads(text)
    print(f'Public-file and metadata checks passed: {len(files)} files; approved example images only.')
    return files
if __name__=='__main__':
    try:check()
    except (ValueError,UnicodeError) as error:print(error,file=sys.stderr);raise SystemExit(1)
