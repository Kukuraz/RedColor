"""Short-lived compatibility worker for the Python formula engine.

The Rust GUI sends a single UTF-8 JSON request over stdin and receives a single
JSON response. The process exits afterwards, releasing matplotlib and Qt.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(req):
    from rp import formula
    kind = req.get("kind")
    if kind == "html":
        from rp.clipboard import html_to_runs
        runs = html_to_runs(req.get("html", ""), strict=True)
        if not runs:
            return {"blocks": [], "formulas": {}}
        keys = {r[1] for _, block in runs for r in block if r[0] == "f"}
        return {"blocks": runs, "formulas": {k: formula.REGISTRY[k].to_dict() for k in keys if k in formula.REGISTRY}}
    if kind == "latex":
        f = formula.from_latex(req.get("latex", ""))
        return {"key": f.key, "formula": f.to_dict()}
    if kind == "recover":
        from rp.svg2tex import svg_to_latex
        return {"latex": svg_to_latex(req.get("svg", ""))}
    if kind == "dialog":
        from PySide6.QtWidgets import QApplication
        from rp.dialogs import FormulaDialog
        app = QApplication(["RedColor Formula"])
        latex = req.get("latex", "")
        hint = ""
        if not latex and req.get("svg"):
            try:
                from rp.svg2tex import svg_to_latex
                latex = svg_to_latex(req["svg"])
                hint = "Формула вставлена с сайта картинкой. LaTeX восстановлен автоматически — проверьте и поправьте."
            except Exception:
                hint = "Не удалось восстановить LaTeX — введите формулу заново."
        dlg = FormulaDialog(latex, hint)
        if not dlg.exec() or dlg.result is None:
            return {"cancelled": True}
        return {"key": dlg.result.key, "formula": dlg.result.to_dict()}
    raise ValueError("Unknown formula operation")


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        result = {"ok": True, "result": main(request)}
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
