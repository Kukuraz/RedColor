# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Защищённое сохранение PDF.

Склейка документа с пометками выполняется в отдельном процессе: если библиотека PDF упадёт на «странном»
файле (PDF из любой программы), основная программа не закрывается, а пробует следующий способ:
  1. mupdf       — пометки отдельным слоем (остаются редактируемыми), сжатие только своих шрифтов;
  2. mupdf_safe  — то же без сжатия шрифтов и без пересборки объектов документа;
  3. pypdf       — резервный движок на чистом Python (пометки вклеиваются в страницу).
Задание передаётся через папку: src.pdf (документ), ov.pdf (страницы с пометками), job.json.
"""
import json
import os
import sys
from pathlib import Path

STRATEGIES = ("mupdf", "mupdf_safe", "pypdf")


def worker(job_dir, strategy):
    """Точка входа дочернего процесса. Код выхода 0 — out.pdf готов."""
    job_dir = Path(job_dir)
    try:
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        out = job_dir / f"out_{strategy}.pdf"
        if strategy == "pypdf":
            _save_pypdf(job_dir, job, out)
        else:
            _save_mupdf(job_dir, job, out, safe=(strategy == "mupdf_safe"))
        (job_dir / f"ok_{strategy}").write_text("ok", encoding="utf-8")
    except BaseException as e:  # noqa: BLE001 — любая ошибка = следующий способ
        try:
            (job_dir / f"error_{strategy}.txt").write_text(f"{type(e).__name__}: {e}", encoding="utf-8")
        except OSError:
            pass
        sys.exit(2)


def merge_mupdf(doc, ov, pages, editable=True, subset=True):
    """Накладывает страницы пометок ov на документ doc отдельным слоем (+ описание объектов для правки).
    Сжимаются только шрифты пометок — шрифты самого документа не трогаются (на некоторых PDF это роняло MuPDF)."""
    import pymupdf
    if not pages:
        return
    if subset:
        try:
            ov.subset_fonts()
            ov = pymupdf.open("pdf", ov.tobytes())
        except Exception:
            pass
    for m in pages:
        page = doc[m["page"]]
        target = page.rect * page.derotation_matrix
        target.normalize()
        before = set(page.get_contents())
        page.show_pdf_page(target, ov, m["ov"], overlay=True, keep_proportion=False, rotate=page.rotation)
        added = [x for x in page.get_contents() if x not in before]
        added = [x for x in added if b"Do" in doc.xref_stream(x)]
        if editable and len(added) == 1:
            try:
                sx = doc.get_new_xref()
                doc.update_object(sx, "<<>>")
                doc.update_stream(sx, json.dumps({"v": 1, "items": m["items"]}, ensure_ascii=False).encode("utf-8"))
                doc.xref_set_key(page.xref, "RedColorItems", f"{sx} 0 R")
                doc.xref_set_key(page.xref, "RedColorContent", f"{added[0]} 0 R")
            except Exception as e:
                print("layer save error:", e, file=sys.stderr)


def _save_mupdf(job_dir, job, out, safe):
    import pymupdf
    pymupdf.TOOLS.mupdf_display_errors(False)
    doc = pymupdf.open(str(job_dir / "src.pdf"))
    if job["pages"]:
        ov = pymupdf.open(str(job_dir / "ov.pdf"))
        merge_mupdf(doc, ov, job["pages"], editable=job.get("editable", True), subset=not safe)
    if job.get("indices") is not None:
        doc.select(job["indices"])
    try:
        meta = dict(doc.metadata or {})
        meta["creator"] = job.get("creator", "RedColor")
        doc.set_metadata(meta)
    except Exception:
        pass
    if safe:
        doc.save(str(out), garbage=0, deflate=False)
    else:
        doc.save(str(out), garbage=3, deflate=True)
    doc.close()


def _save_pypdf(job_dir, job, out):
    """Резервный способ без MuPDF: пометки вклеиваются в содержимое страницы."""
    from pypdf import PdfReader, PdfWriter, Transformation
    writer = PdfWriter(clone_from=PdfReader(str(job_dir / "src.pdf"), strict=False))
    if job["pages"]:
        ovr = PdfReader(str(job_dir / "ov.pdf"), strict=False)
        for m in job["pages"]:
            page = writer.pages[m["page"]]
            ovp = ovr.pages[m["ov"]]
            box = page.cropbox
            x0, y0 = float(box.left), float(box.bottom)
            w, h = float(box.width), float(box.height)
            rot = (page.get("/Rotate", 0) or 0) % 360
            t = Transformation()
            if rot == 90:
                t = t.rotate(90).translate(w, 0)
            elif rot == 180:
                t = t.rotate(180).translate(w, h)
            elif rot == 270:
                t = t.rotate(270).translate(0, h)
            t = t.translate(x0, y0)
            page.merge_transformed_page(ovp, t, over=True, expand=False)
    if job.get("indices") is not None:
        keep = set(job["indices"])
        for i in reversed(range(len(writer.pages))):
            if i not in keep:
                del writer.pages[i]
    try:
        writer.add_metadata({"/Creator": job.get("creator", "RedColor")})
    except Exception:
        pass
    with open(out, "wb") as f:
        writer.write(f)


def run(job_dir, timeout=180):
    """Пробует способы по очереди в отдельных процессах. Возвращает (путь к результату, способ) или ошибку."""
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    if sys.executable.lower().endswith("pythonw.exe"):
        ctx.set_executable(sys.executable)
    errors = []
    for strategy in STRATEGIES:
        p = ctx.Process(target=worker, args=(str(job_dir), strategy), daemon=True)
        p.start()
        p.join(timeout)
        if p.is_alive():
            p.terminate()
            errors.append(f"{strategy}: превышено время")
            continue
        out = Path(job_dir) / f"out_{strategy}.pdf"
        if p.exitcode == 0 and (Path(job_dir) / f"ok_{strategy}").exists() and out.exists() and out.stat().st_size > 0:
            return out, strategy, errors
        err_file = Path(job_dir) / f"error_{strategy}.txt"
        msg = err_file.read_text(encoding="utf-8") if err_file.exists() else f"процесс завершился с кодом {p.exitcode}"
        errors.append(f"{strategy}: {msg}")
        print(f"save strategy {strategy} failed: {msg}", file=sys.stderr)
    return None, None, errors
