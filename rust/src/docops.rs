// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Страницы документа: поворот, удаление, вставка (файлы, пустые, бланки), извлечение, порядок.
//! Каждая операция — новая версия байтов документа; отмена возвращает и байты, и пометки.

use std::rc::Rc;

use mupdf::pdf::{InsertPdfOptions, InsertPosition, PdfDocument};

use crate::items::{Item, p};
use crate::{App, PageSlot};

#[derive(Clone)]
pub struct Snap {
    pub items: Vec<Vec<Item>>,
    pub src: Rc<Vec<u8>>,
}

fn e(err: mupdf::Error) -> String {
    err.to_string()
}

pub fn page_sizes(data: &[u8]) -> Vec<(f32, f32)> {
    let Ok(doc) = mupdf::Document::from_bytes(data, "application/pdf") else { return vec![] };
    let n = doc.page_count().unwrap_or(0);
    (0..n)
        .map(|i| doc.load_page(i).and_then(|pg| pg.bounds()).map(|r| (r.x1 - r.x0, r.y1 - r.y0)).unwrap_or((595.0, 842.0)))
        .collect()
}

fn to_bytes(doc: &PdfDocument) -> Result<Vec<u8>, String> {
    let mut out = Vec::new();
    doc.write_to(&mut out).map_err(e)?;
    Ok(out)
}

/// PDF из файла (изображения превращаются в PDF).
pub fn file_as_pdf(path: &std::path::Path) -> Result<Vec<u8>, String> {
    let data = std::fs::read(path).map_err(|x| x.to_string())?;
    let ext = path.extension().and_then(|x| x.to_str()).unwrap_or("pdf").to_lowercase();
    if ext == "pdf" {
        return Ok(data);
    }
    let img = mupdf::Document::from_bytes(&data, &ext).map_err(e)?;
    let pdf = img.convert_to_pdf(0, -1, 0).map_err(e)?;
    to_bytes(&pdf)
}

impl App {
    /// Байты документа сменились — заново размеры страниц и рендер.
    pub(crate) fn reload_src(&mut self) {
        let Some(c) = self.cur else { return };
        let sizes = page_sizes(&self.docs[c].src);
        let d = &mut self.docs[c];
        d.ver += 1;
        d.pages = sizes.iter().map(|&(w, h)| PageSlot { w, h, y: 0.0, img: None }).collect();
        while d.items.len() < d.pages.len() {
            d.items.push(Vec::new());
        }
        d.items.truncate(d.pages.len());
        d.sel.clear();
        d.ov_page = usize::MAX;
        d.relayout();
        let (key, ver, data) = (d.key, d.ver, (*d.src).clone());
        self.render.load(key, ver, data);
        self.push_layout();
        self.update_render();
    }

    /// Изменение структуры: снимок для отмены, новые байты, новые пометки.
    fn apply_structure(&mut self, src: Vec<u8>, items: Vec<Vec<Item>>) {
        self.checkpoint();
        let Some(c) = self.cur else { return };
        self.docs[c].src = Rc::new(src);
        self.docs[c].items = items;
        self.reload_src();
    }

    pub(crate) fn current_page_index(&self) -> usize {
        let vh = self.win().get_view_h();
        self.cur.map(|c| self.docs[c].current_page(vh)).unwrap_or(0)
    }

    /// Поворот страниц на delta (кратно 90), пометки поворачиваются вместе со страницей.
    pub(crate) fn rotate_pages(&mut self, pages: &[usize], delta: i32) {
        let Some(c) = self.cur else { return };
        let r = (|| -> Result<(Vec<u8>, Vec<Vec<Item>>), String> {
            let doc = PdfDocument::from_bytes(&self.docs[c].src).map_err(e)?;
            let mut items = self.docs[c].items.clone();
            for &i in pages {
                let mut pg = doc.load_pdf_page(i as i32).map_err(e)?;
                let rot = pg.rotation().map_err(e)?;
                pg.set_rotation((rot + delta).rem_euclid(360)).map_err(e)?;
                let steps = (delta / 90).rem_euclid(4);
                let (mut w, mut h) = (self.docs[c].pages[i].w as f64, self.docs[c].pages[i].h as f64);
                for _ in 0..steps {
                    for it in items[i].iter_mut() {
                        let (x, y) = it.pos();
                        it.set_pos(h - y, x);
                        match it {
                            Item::Shape(s) => s.rot = (s.rot + 90.0) % 360.0,
                            Item::Ink(s) => s.rot = (s.rot + 90.0) % 360.0,
                            Item::Text(s) => s.rot = (s.rot + 90.0) % 360.0,
                            Item::Image(s) => s.rot = (s.rot + 90.0) % 360.0,
                        }
                    }
                    std::mem::swap(&mut w, &mut h);
                }
            }
            Ok((to_bytes(&doc)?, items))
        })();
        match r {
            Ok((src, items)) => self.apply_structure(src, items),
            Err(err) => self.toast(&format!("Не удалось повернуть: {err}")),
        }
    }

    pub(crate) fn delete_pages(&mut self, pages: &[usize]) {
        let Some(c) = self.cur else { return };
        let n = self.docs[c].pages.len();
        let keep: Vec<usize> = (0..n).filter(|i| !pages.contains(i)).collect();
        if keep.is_empty() {
            self.toast("Нельзя удалить все страницы");
            return;
        }
        self.reorder(keep);
    }

    /// Новый порядок страниц (и удаление тех, что не вошли).
    pub(crate) fn reorder(&mut self, order: Vec<usize>) {
        let Some(c) = self.cur else { return };
        let r = (|| -> Result<Vec<u8>, String> {
            let mut doc = PdfDocument::from_bytes(&self.docs[c].src).map_err(e)?;
            doc.select_pages(order.clone()).map_err(e)?;
            to_bytes(&doc)
        })();
        match r {
            Ok(src) => {
                let items = order.iter().map(|&i| self.docs[c].items[i].clone()).collect();
                self.apply_structure(src, items);
            }
            Err(err) => self.toast(&format!("Не удалось изменить страницы: {err}")),
        }
    }

    /// Вставка всех страниц PDF (байты) на позицию at. Возвращает номер первой вставленной.
    pub(crate) fn insert_pdf_bytes(&mut self, at: usize, data: &[u8]) -> Option<usize> {
        let c = self.cur?;
        let r = (|| -> Result<(Vec<u8>, usize), String> {
            let mut doc = PdfDocument::from_bytes(&self.docs[c].src).map_err(e)?;
            let src = PdfDocument::from_bytes(data).map_err(e)?;
            let n = src.page_count().map_err(e)? as usize;
            let opts = InsertPdfOptions { target: InsertPosition::Before(at), copy_annotations: true, copy_links: true, copy_widgets: true, ..Default::default() };
            let opts = if at >= self.docs[c].pages.len() { InsertPdfOptions { target: InsertPosition::Append, ..opts } } else { opts };
            doc.insert_pdf(&src, opts).map_err(e)?;
            Ok((to_bytes(&doc)?, n))
        })();
        match r {
            Ok((src, n)) => {
                let mut items = self.docs[c].items.clone();
                let at = at.min(items.len());
                for _ in 0..n {
                    items.insert(at, Vec::new());
                }
                self.apply_structure(src, items);
                Some(at)
            }
            Err(err) => {
                self.toast(&format!("Не удалось вставить страницы: {err}"));
                None
            }
        }
    }

    pub(crate) fn insert_blank_page(&mut self, at: usize) {
        let Some(c) = self.cur else { return };
        let refp = at.saturating_sub(1).min(self.docs[c].pages.len().saturating_sub(1));
        let (w, h) = self.docs[c].pages.get(refp).map(|p| (p.w, p.h)).unwrap_or((595.0, 842.0));
        let r = (|| -> Result<Vec<u8>, String> {
            let mut doc = PdfDocument::new();
            doc.new_page(mupdf::Size::new(w, h)).map_err(e)?;
            to_bytes(&doc)
        })();
        match r {
            Ok(b) => {
                if let Some(i) = self.insert_pdf_bytes(at, &b) {
                    self.go_to_page(i as i64);
                }
            }
            Err(err) => self.toast(&format!("Не удалось: {err}")),
        }
    }

    pub(crate) fn insert_from_file_dialog(&mut self) {
        let Some(c) = self.cur else { return };
        let files = rfd::FileDialog::new()
            .set_title("Вставить страницы из файла")
            .add_filter("PDF и изображения", &["pdf", "png", "jpg", "jpeg", "bmp", "gif", "tif", "tiff", "webp"])
            .pick_files();
        let Some(files) = files else { return };
        let mut at = self.current_page_index() + 1;
        let _ = c;
        for f in files {
            match file_as_pdf(&f) {
                Ok(b) => {
                    let n = page_sizes(&b).len();
                    if self.insert_pdf_bytes(at, &b).is_some() {
                        at += n;
                    }
                }
                Err(err) => self.toast(&format!("{}: {err}", f.display())),
            }
        }
    }

    /// Извлечь страницы (с пометками) в отдельный файл.
    pub(crate) fn extract_pages_dialog(&mut self, pages: Vec<usize>) {
        let Some(c) = self.cur else { return };
        if pages.is_empty() {
            return;
        }
        let stem = self.docs[c].title.trim_end_matches(".pdf").to_string();
        let name = if pages.len() == 1 { format!("{stem} (стр. {}).pdf", pages[0] + 1) } else { format!("{stem} (извлечено).pdf") };
        let Some(path) = rfd::FileDialog::new().set_title("Извлечь страницы").add_filter("PDF", &["pdf"]).set_file_name(&name).save_file() else {
            return;
        };
        match self.output_bytes(Some(&pages)) {
            Ok(b) => match crate::pdfio::replace_file(&b, &path) {
                Ok(()) => self.toast(&format!("Извлечено страниц: {} → {}", pages.len(), path.display())),
                Err(err) => self.toast(&format!("Не удалось записать: {err}")),
            },
            Err(err) => self.toast(&format!("Не удалось: {err}")),
        }
    }

    /// Готовый PDF с пометками (для сохранения, печати, экспорта); pages — только эти страницы.
    pub(crate) fn output_bytes(&self, pages: Option<&[usize]>) -> Result<Vec<u8>, String> {
        let c = self.cur.ok_or("нет документа")?;
        let d = &self.docs[c];
        let creator = format!("RedColor {} - Maksim Belonoskin, Zelenograd, Moscow, Russia", crate::APP_VERSION);
        let out = crate::pdfio::build_output(&d.src, &d.items, &creator, &self.fonts, &self.text_cache)?;
        match pages {
            None => Ok(out),
            Some(sel) => {
                let mut doc = PdfDocument::from_bytes(&out).map_err(e)?;
                doc.select_pages(sel.to_vec()).map_err(e)?;
                to_bytes(&doc)
            }
        }
    }

    /// Замена страниц: текущая заменяется страницами из файла.
    pub(crate) fn replace_page_dialog(&mut self) {
        let cur = self.current_page_index();
        let Some(f) = rfd::FileDialog::new()
            .set_title("Заменить текущую страницу")
            .add_filter("PDF и изображения", &["pdf", "png", "jpg", "jpeg"])
            .pick_file()
        else {
            return;
        };
        match file_as_pdf(&f) {
            Ok(b) => {
                if self.insert_pdf_bytes(cur + 1, &b).is_some() {
                    self.delete_pages(&[cur]);
                }
            }
            Err(err) => self.toast(&err),
        }
    }

    /// Перемещение текущей страницы на delta позиций.
    pub(crate) fn move_page(&mut self, delta: i64) {
        let Some(c) = self.cur else { return };
        let n = self.docs[c].pages.len();
        let cur = self.current_page_index();
        let to = (cur as i64 + delta).clamp(0, n as i64 - 1) as usize;
        if to == cur {
            return;
        }
        let mut order: Vec<usize> = (0..n).collect();
        let pg = order.remove(cur);
        order.insert(to, pg);
        self.reorder(order);
        self.go_to_page(to as i64);
    }
}

/// Номера страниц из строки «1-3, 5, 8-» (как parse_ranges в версии на Python).
pub fn parse_ranges(text: &str, n: usize) -> Vec<usize> {
    let mut out = Vec::new();
    for part in text.split([',', ';', ' ']) {
        let part = part.trim();
        if part.is_empty() {
            continue;
        }
        if let Some((a, b)) = part.split_once(['-', '–']) {
            let a = a.trim().parse::<usize>().unwrap_or(1).max(1);
            let b = if b.trim().is_empty() { n } else { b.trim().parse::<usize>().unwrap_or(n) };
            for i in a..=b.min(n) {
                if !out.contains(&(i - 1)) {
                    out.push(i - 1);
                }
            }
        } else if let Ok(i) = part.parse::<usize>() {
            if i >= 1 && i <= n && !out.contains(&(i - 1)) {
                out.push(i - 1);
            }
        }
    }
    let _ = p;
    out
}
