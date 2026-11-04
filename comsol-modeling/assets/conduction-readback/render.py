"""Generate same-top-level-class conduction checks into a NEW Java source.

No Java/compiler/COMSOL runs. One maintained method fragment is inserted at the
class-level marker. Old callback calls are migrated only for exact forwarding
lambdas; arbitrary Java rewriting or auxiliary-class loading is not attempted.
"""
import argparse
import hashlib
from pathlib import Path
import re

MARKER = "// @CONDUCTION_READBACK@"
FRAGMENT = Path(__file__).with_name("ConductionChecks.java.inc")
RECORD_TOKEN = "__CONDUCTION_RECORD__"
IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"
HELPERS = ("crRequire", "crIds", "crExactIsotropic", "crDisabled", "crKnownFeature", "crCheck")


def code_mask(text, line_comments=None):
    """Mask comments/string/character literals without moving source offsets.

    This limited lexer deliberately rejects Java text blocks. It is not a Java
    type checker or a security sandbox; actual compilation is separate evidence.
    """
    masked = list(text)
    i = 0
    while i < len(text):
        if text.startswith('"""', i):
            raise ValueError("Java text blocks require a separately reviewed template")
        if text.startswith('//', i):
            if line_comments is not None: line_comments.append(i)
            end = text.find('\n', i)
            end = len(text) if end < 0 else end
        elif text.startswith('/*', i):
            end = text.find('*/', i + 2)
            if end < 0: raise ValueError("Unclosed Java comment")
            end += 2
        elif text[i] in ('"', "'"):
            quote, end = text[i], i + 1
            while end < len(text):
                if text[end] == "\\": end += 2; continue
                if text[end] == quote: end += 1; break
                end += 1
            else: raise ValueError("Unclosed Java literal")
        else:
            i += 1
            continue
        for j in range(i, min(end, len(text))):
            if text[j] not in "\r\n": masked[j] = ' '
        i = end
    return ''.join(masked)


def arguments(text, mask, open_at):
    """Return exact argument slices and close offset for a balanced Java call."""
    stack, start, args = ['('], open_at + 1, []
    pairs = {')': '(', ']': '[', '}': '{'}
    for i in range(start, len(mask)):
        c = mask[i]
        if c in '([{': stack.append(c)
        elif c in ')]}':
            if not stack or stack.pop() != pairs[c]: raise ValueError("Unbalanced call")
            if not stack:
                args.append(text[start:i].strip())
                return args, i
        elif c == ',' and len(stack) == 1:
            args.append(text[start:i].strip())
            start = i + 1
    raise ValueError("Unclosed call")


def migrate_calls(text, record_method):
    mask = code_mask(text)
    edits = []
    for match in re.finditer(r"\bConductionChecks\s*\.\s*check\s*\(", mask):
        args, end = arguments(text, mask, match.end() - 1)
        if len(args) != 11 or any(not x for x in args):
            raise ValueError("Legacy check must have ten inputs and one exact forwarding callback")
        callback = code_mask(args[-1]).strip()
        pattern = (r"\(\s*(" + IDENTIFIER + r")\s*,\s*(" + IDENTIFIER + r")\s*,\s*(" + IDENTIFIER +
                   r")\s*\)\s*->\s*" + re.escape(record_method) + r"\s*\(\s*\1\s*,\s*\2\s*,\s*\3\s*\)")
        if not re.fullmatch(pattern, callback):
            raise ValueError("Legacy callback must forward its three arguments unchanged to the declared recorder")
        edits.append((match.start(), end + 1, 'crCheck(' + ', '.join(args[:-1]) + ')'))
    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    return text, len(edits)


def render(source, output, *, record_method="recordConductionCheck"):
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    if output == source or output.exists():
        raise ValueError("Output must be a new Java file; preserve original and failed sources")
    if output.suffix != '.java': raise ValueError("Expected .java output")
    if not re.fullmatch(IDENTIFIER, record_method) or record_method in HELPERS or record_method == RECORD_TOKEN:
        raise ValueError("Recorder must be an explicit non-reserved Java method identifier")
    source_bytes = source.read_bytes()
    text = source_bytes.decode('utf-8-sig')
    if text.count(MARKER) != 1 or not any(line.strip() == MARKER for line in text.splitlines()):
        raise ValueError("Exactly one standalone class-level marker required")
    line_comments = []
    mask = code_mask(text, line_comments)
    marker_at = text.index(MARKER)
    if marker_at not in line_comments:
        raise ValueError("Marker must be a real standalone line comment, not inside another comment or literal")
    if mask[:marker_at].count('{') - mask[:marker_at].count('}') != 1:
        raise ValueError("Marker must be directly inside the one top-level class")
    types = re.findall(r"\b(class|interface|enum|record)\s+(" + IDENTIFIER + r")", mask)
    if len(types) != 1 or types[0] != ('class', output.stem):
        raise ValueError("Template must declare only the matching top-level class, with no auxiliary types")
    if re.search(r"\bpackage\s+", mask): raise ValueError("Use one package-free top-level class")
    if any(re.search(r"\b" + name + r"\b", mask) for name in HELPERS[:-1]) or re.search(r"\bvoid\s+crCheck\s*\(", mask):
        raise ValueError("Template must not contain an old or duplicate private copy of the helper methods")
    declaration = (r"\bstatic\s+void\s+" + re.escape(record_method) + r"\s*\(\s*boolean\s+" + IDENTIFIER +
                   r"\s*,\s*(?:java\.lang\.)?String\s+" + IDENTIFIER +
                   r"\s*,\s*(?:java\.lang\.)?String\s+" + IDENTIFIER + r"\s*\)\s*\{")
    if len(re.findall(declaration, mask)) != 1:
        raise ValueError("Declare exactly one static void recorder(boolean, String, String) body with no throws clause")
    text, migrated = migrate_calls(text, record_method)
    mask = code_mask(text)
    if re.search(r"\bConductionChecks\b|->", mask):
        raise ValueError("Unmigrated helper/callback remains; use direct same-class calls")
    # Anonymous classes would also reintroduce auxiliary class artifacts.
    if re.search(r"\bnew\s+[\w.$<>?,\s]+\([^;{}]*\)\s*\{", mask):
        raise ValueError("Anonymous classes require a separately reviewed loading mechanism")
    calls = list(re.finditer(r"\bcrCheck\s*\(", mask))
    if not calls: raise ValueError("Template must invoke crCheck in its task-specific checks")
    for call in calls:
        args, _ = arguments(text, mask, call.end() - 1)
        if len(args) != 10 or any(not x for x in args):
            raise ValueError("crCheck requires exactly ten explicit task inputs")
    fragment_bytes = FRAGMENT.read_bytes()
    fragment = fragment_bytes.decode('utf-8')
    if fragment.count(RECORD_TOKEN + '(') != 1: raise ValueError("Invalid maintained recorder binding")
    fragment = fragment.replace(RECORD_TOKEN + '(', record_method + '(')
    sha = hashlib.sha256(fragment_bytes).hexdigest()
    result = text.replace(MARKER, '// recipe_sha256=' + sha + '\n' + fragment)
    # Catch a source changed while generation was in progress, before creating output.
    if source.read_bytes() != source_bytes: raise ValueError("Source changed during generation")
    if FRAGMENT.read_bytes() != fragment_bytes: raise ValueError("Recipe changed during generation")
    with output.open('x', encoding='utf-8', newline='\n') as stream: stream.write(result)
    return {'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
            'recipe_sha256': sha, 'renderer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'record_method': record_method, 'legacy_calls_migrated': migrated,
            'delivery_form': 'same_top_level_class_methods',
            'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'java_compilation': 'not_run', 'comsol_execution': 'not_run'}


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--record-method', default='recordConductionCheck')
    args = parser.parse_args()
    print(json.dumps(render(args.source, args.output, record_method=args.record_method)))
