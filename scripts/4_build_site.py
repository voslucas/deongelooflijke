"""Inline episode data and logos into the page template -> site/dist/index.html (one self-contained file)."""
import base64, pathlib
ROOT=pathlib.Path(__file__).resolve().parent.parent
s=(ROOT/'site/src/index.template.html').read_text(encoding='utf-8')
d=(ROOT/'data/episodes.json').read_text(encoding='utf-8').replace('</','<\\/')
b64=lambda p,m:f"data:{m};base64,"+base64.b64encode((ROOT/p).read_bytes()).decode()
out=s.replace('__DATA__',d).replace('__LOGO__',b64('design-system/assets/logos/logo360.jpg','image/jpeg')).replace('__WORDMARK__',b64('design-system/assets/logos/wordmark672.png','image/png'))
(ROOT/'site/dist').mkdir(parents=True,exist_ok=True)
(ROOT/'site/dist/index.html').write_text(out,encoding='utf-8')
print('site/dist/index.html',len(out),'bytes')
