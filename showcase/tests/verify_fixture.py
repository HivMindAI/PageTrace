"""Compare bundled sample bytes with only the original pure fixture generator.

This does not import, install, or run the PageTrace package/pipeline.
"""
import ast
import hashlib
from pathlib import Path

showcase = Path(__file__).resolve().parents[1]
source_path = showcase.parent / "src" / "pagetrace" / "portfolio.py"
parsed = ast.parse(source_path.read_text(encoding="utf-8"))
selected = []
for item in parsed.body:
    if isinstance(item, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "PORTFOLIO_PAGE_TEXTS"
        for target in item.targets
    ):
        selected.append(item)
    if isinstance(item, ast.FunctionDef) and item.name == "_portfolio_pdf_bytes":
        selected.append(item)
assert len(selected) == 2, "Expected the original text constant and pure PDF helper"
namespace = {}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec"), namespace)
expected = namespace["_portfolio_pdf_bytes"](namespace["PORTFOLIO_PAGE_TEXTS"])
actual = (showcase / "site" / "samples" / "northstar-fy2025.pdf").read_bytes()
assert actual == expected, "Bundled PDF differs from original fixture helper"
print(f"PASS: {len(actual)} PDF bytes match original generator; SHA-256 {hashlib.sha256(actual).hexdigest()}")
