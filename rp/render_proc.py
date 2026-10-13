# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Отдельный процесс рендера страниц (PyMuPDF). Импортирует только pymupdf — запускается быстро."""


def worker(conn):
    import pymupdf
    pymupdf.TOOLS.mupdf_display_errors(False)
    docs = {}
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            break
        if msg is None:
            break
        cmd = msg[0]
        try:
            if cmd == "load":
                _, key, gen, data = msg
                old = docs.pop(key, None)
                if old:
                    old[1].close()
                docs[key] = (gen, pymupdf.open(stream=data, filetype="pdf"))
            elif cmd == "close":
                old = docs.pop(msg[1], None)
                if old:
                    old[1].close()
            elif cmd == "render":
                _, rid, key, gen, idx, zoom = msg
                entry = docs.get(key)
                if not entry or entry[0] != gen or idx >= entry[1].page_count:
                    conn.send(("skip", rid))
                    continue
                page = entry[1][idx]
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, annots=True)
                conn.send(("img", rid, pix.width, pix.height, pix.stride, pix.samples))
        except Exception as e:  # не роняем процесс из-за одной страницы
            if cmd == "render":
                conn.send(("err", msg[1], str(e)))
