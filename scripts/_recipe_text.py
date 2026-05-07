"""Tokenizer + document-text builder shared by recipe index/search/eval."""
import re

CJK_RE = re.compile(r'[一-鿿]')
ASCII_TOK_RE = re.compile(r'[a-z][a-z0-9]+')

EN_STOP = {
    'the', 'a', 'an', 'of', 'and', 'or', 'to', 'in', 'for',
    'on', 'with', 'by', 'at', 'from', 'is', 'are',
}


def tokenize(text):
    if not text:
        return []
    text = text.lower()
    tokens = []
    for m in ASCII_TOK_RE.finditer(text):
        t = m.group(0)
        if t in EN_STOP or len(t) < 2:
            continue
        tokens.append(t)
    run = []
    for ch in text:
        if CJK_RE.match(ch):
            run.append(ch)
            continue
        if run:
            if len(run) == 1:
                tokens.append(run[0])
            else:
                for i in range(len(run) - 1):
                    tokens.append(run[i] + run[i + 1])
            run = []
    if run:
        if len(run) == 1:
            tokens.append(run[0])
        else:
            for i in range(len(run) - 1):
                tokens.append(run[i] + run[i + 1])
    return tokens


NUM_PREFIX_RE = re.compile(r'(?<![A-Za-z一-鿿])\d+(?:\.\d+)?')


def strip_numerics(text):
    return NUM_PREFIX_RE.sub(' ', text)


def doc_text(recipe):
    """Build the indexable text for a recipe.

    Excludes `top_method_describes` so it can be held out for retrieval eval.
    """
    k = recipe.get('key', {})
    parts = [
        k.get('gender', ''), k.get('dept', ''), k.get('gt', ''),
        k.get('it', ''), k.get('wk', ''), k.get('l1', ''),
        recipe.get('category_zh', ''),
    ]
    for p in recipe.get('top_parts', []) or []:
        parts.append(p.get('name', ''))
    for c in recipe.get('top_method_codes', []) or []:
        parts.append(c.get('code', ''))
    for m in recipe.get('top_machines', []) or []:
        parts.append(m.get('name', ''))
    for s in recipe.get('top_sections', []) or []:
        parts.append(s.get('section', ''))
    for s in recipe.get('top_shape_designs', []) or []:
        parts.append(s.get('shape', ''))
    for m in recipe.get('methods', []) or []:
        parts.append(m.get('name', ''))
    for iso in (recipe.get('iso_distribution') or [])[:5]:
        parts.append('iso_' + str(iso.get('iso', '')))
    return ' '.join(p for p in parts if p)


def query_text_from_describes(recipe):
    """Held-out eval query: the recipe's method-describe text, numerics stripped."""
    descs = recipe.get('top_method_describes') or []
    text = ' '.join(d.get('text', '') for d in descs)
    return strip_numerics(text)
