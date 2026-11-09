// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Команды: бланки, цитаты, подписи, файлы, поиск, печать, экспорт, диалоги, меню.

use std::path::{Path, PathBuf};
use std::rc::Rc;

use serde_json::json;
use slint::{Global, ModelRc, SharedString, VecModel};

use crate::items::{Item, Shape, p};
use crate::text::Run;
use crate::{App, MenuItem, SelView, blanks, images, panel, with_app};

pub fn menu(id: &str, text: &str) -> MenuItem {
    MenuItem { id: id.into(), text: text.into(), header: false, indent: 0, checked: false }
}
fn header(text: &str) -> MenuItem {
    MenuItem { id: "".into(), text: text.into(), header: true, indent: 0, checked: false }
}

impl App {
    // ------------------------------------------------------------------ меню
    pub(crate) fn show_menu(&mut self, title: &str, items: Vec<MenuItem>) {
        let w = self.win();
        w.set_menu_title(title.into());
        w.set_menu_items(ModelRc::new(VecModel::from(items)));
        w.set_menu_visible(true);
    }

    pub(crate) fn blank_menu(&mut self) {
        let files = self.blanks.clone();
        let mut items = Vec::new();
        if files.is_empty() {
            items.push(header(if self.settings.str("blanks_dir", "").is_empty() { "Папка бланков не выбрана" } else { "В папке нет PDF-бланков" }));
        }
        let mut last_group = String::new();
        for (label, path) in &files {
            let (group, name) = label.rsplit_once(" / ").map(|(a, b)| (a.to_string(), b.to_string())).unwrap_or((String::new(), label.clone()));
            if group != last_group && !group.is_empty() {
                items.push(header(&group));
            }
            last_group = group.clone();
            let mut m = menu(&format!("blank.insert:{}", path.display()), &name);
            m.indent = if group.is_empty() { 0 } else { 1 };
            items.push(m);
        }
        if !files.is_empty() {
            items.push(header("Полные бланки (все «+» и баллы)"));
            for (label, path) in &files {
                let mut m = menu(&format!("blank.full:{}", path.display()), label);
                m.indent = 1;
                items.push(m);
            }
        }
        items.push(header(""));
        let mut auto = menu("blank.toggle_quote", "Случайная цитата при вставке");
        auto.checked = self.settings.bool("auto_quote_on_blank", true);
        items.push(auto);
        for id in ["app.quotes", "blank.choose_dir", "blank.open_dir", "blank.clean_doc", "blank.clean_folder"] {
            items.push(menu(id, panel::action_name(id)));
        }
        self.show_menu("Вставить бланк", items);
    }

    pub(crate) fn app_menu(&mut self) {
        let mut items = Vec::new();
        for id in ["file.new", "file.open"] {
            items.push(menu(id, panel::action_name(id)));
        }
        items.push(header("Недавние"));
        for p in self.settings.recent().into_iter().take(10) {
            let name = Path::new(&p).file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or(p.clone());
            let mut m = menu(&format!("open:{p}"), &name);
            m.indent = 1;
            items.push(m);
        }
        items.push(header(""));
        for id in [
            "file.save", "file.save_as", "file.print", "file.merge", "file.compress", "file.export_images", "page.extract",
            "page.insert_file", "page.insert_blank", "page.rotate_cw", "page.rotate_ccw", "page.delete", "page.move_up",
            "page.move_down", "page.replace", "app.quotes", "blank.choose_dir", "app.hotkeys", "app.settings",
            "app.default_pdf", "app.info", "app.about", "file.close", "file.quit",
        ] {
            items.push(menu(id, panel::action_name(id)));
        }
        self.show_menu("Меню", items);
    }

    pub(crate) fn sign_menu(&mut self) {
        let mut items = Vec::new();
        for x in images::sig_index() {
            let id = x.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let name = x.get("name").and_then(|v| v.as_str()).unwrap_or("Подпись").to_string();
            items.push(menu(&format!("sign.arm:{id}"), &name));
        }
        items.push(header(""));
        items.push(menu("sign.new", "Добавить подпись…"));
        items.push(menu("sign.new_initials", "Добавить инициалы…"));
        self.show_menu("Подписи", items);
    }

    pub(crate) fn signature_context(&mut self, sid: &str) {
        self.show_menu(
            "Подпись",
            vec![
                menu(&format!("sign.arm:{sid}"), "Поставить на страницу"),
                menu(&format!("sign.rename:{sid}"), "Переименовать…"),
                menu(&format!("sign.delete:{sid}"), "Удалить"),
            ],
        );
    }

    /// Команды с параметром (из меню).
    pub(crate) fn param_action(&mut self, id: &str) -> bool {
        if let Some(p) = id.strip_prefix("blank.insert:") {
            self.insert_blank(Path::new(p), false);
        } else if let Some(p) = id.strip_prefix("blank.full:") {
            self.insert_blank(Path::new(p), true);
        } else if let Some(p) = id.strip_prefix("open:") {
            self.open_paths(vec![PathBuf::from(p)]);
        } else if let Some(s) = id.strip_prefix("sign.arm:") {
            self.arm_signature(s);
        } else if let Some(s) = id.strip_prefix("sign.rename:") {
            let cur = images::sig_index()
                .into_iter()
                .find(|x| x.get("id").and_then(|v| v.as_str()) == Some(s))
                .and_then(|x| x.get("name").and_then(|v| v.as_str()).map(String::from))
                .unwrap_or_default();
            self.input_dialog("Подпись", "Название:", &cur, &format!("sign.rename:{s}"));
        } else if let Some(s) = id.strip_prefix("sign.delete:") {
            let r = rfd::MessageDialog::new().set_title("Подпись").set_description("Удалить подпись из списка?").set_buttons(rfd::MessageButtons::YesNo).show();
            if r == rfd::MessageDialogResult::Yes {
                images::sig_remove(s);
                if self.signature_id.as_deref() == Some(s) {
                    self.signature_id = None;
                }
                self.refresh_signatures();
            }
        } else {
            return false;
        }
        true
    }

    // ------------------------------------------------------------------ бланки
    pub(crate) fn insert_blank(&mut self, path: &Path, full: bool) {
        if self.cur.is_none() {
            self.toast("Сначала откройте документ");
            return;
        }
        let at = self.current_page_index() + 1;
        let data = match blanks::prepared_blank(path, self.settings.bool("remove_stray_one", true)) {
            Ok(d) => d,
            Err(err) => {
                rfd::MessageDialog::new().set_title("RedColor").set_description(format!("Не удалось открыть бланк:\n{err}")).show();
                return;
            }
        };
        let info = blanks::analyze(path, &self.settings);
        let marks = if full { Some(blanks::full_marks(path, &self.settings)) } else { None };
        let Some(pg) = self.insert_pdf_bytes(at, &data) else { return };
        let c = self.cur.unwrap();
        // плюсы и баллы — отдельными объектами (их можно стереть или поправить)
        if let Some(m) = marks {
            let color = { let s = self.settings.str("shape_color", ""); if s.is_empty() { self.settings.str("text_color", "#ff0000") } else { s } };
            for (xc, yc, half, width) in m.plus {
                let w = (width * 2.0).max(4.0);
                self.docs[c].items[pg].push(Item::Shape(Shape {
                    x: xc - w / 2.0,
                    y: yc - half,
                    w,
                    h: 2.0 * half,
                    rot: 0.0,
                    shape: "vline".into(),
                    color: color.clone(),
                    width,
                    direction: 0,
                    number: None,
                    num_size: 12.0,
                }));
            }
            for (txt, right, baseline, cap) in m.scores {
                let mut t = self.text_props(595.0);
                t.size = ((cap / 0.66).max(10.0) * 2.0).round() / 2.0;
                t.bold = false;
                t.italic = false;
                t.align = "left".into();
                let font = self.text_cache.for_text(&self.fonts, &t);
                let (adv, asc) = match font.as_ref() {
                    Some(f) => (f.width(&txt, t.size), f.ascender() * t.size),
                    None => (t.size * 0.6, t.size * 0.8),
                };
                self.make_text(pg, right - adv - 1.0, baseline - asc, Some(adv + 20.0), &txt, t);
            }
        }
        if self.settings.bool("auto_quote_on_blank", true) {
            if let (Some(q), Some(info)) = (self.quotes.next(&mut self.settings), info) {
                let (x, y, w, size, mh) = blanks::quote_placement(&info, self.settings.f64("quote_default_size", 16.0));
                let mut t = self.text_props(595.0);
                t.font = crate::text::resolve_family(&self.fonts, &self.settings.str("quote_font", "Minion Pro")).to_string();
                t.size = size;
                t.bold = false;
                t.italic = false;
                t.align = "left".into();
                let k = self.make_text(pg, x, y, Some(w), &q, t);
                // уменьшаем кегль, пока цитата не влезет в поле комментария
                loop {
                    let Some(tt) = self.docs[c].items[pg][k].as_text().cloned() else { break };
                    let h = self.text_layout(&tt).height;
                    if h <= mh || tt.size <= 6.0 {
                        break;
                    }
                    if let Some(t) = self.docs[c].items[pg][k].as_text_mut() {
                        t.size -= 0.5;
                    }
                }
            }
        }
        self.push_overlay();
        self.go_to_page(pg as i64);
        let stem = path.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
        self.toast(&format!("Вставлен {}бланк «{stem}»", if full { "полный " } else { "" }));
    }

    /// «1» в комментариях бланков текущего документа (с отменой).
    pub(crate) fn clean_ones_current(&mut self, silent: bool) {
        let Some(c) = self.cur else { return };
        let src = self.docs[c].src.clone();
        match blanks::remove_comment_ones_doc(&src, None) {
            Some((out, n)) if n > 0 => {
                self.checkpoint();
                self.docs[c].src = Rc::new(out);
                self.reload_src();
                self.toast(&format!("Убрано «1» в комментариях: {n}"));
            }
            _ => {
                if !silent {
                    self.toast("«1» в комментариях бланков не найдено");
                }
            }
        }
    }

    pub(crate) fn clean_ones_folder(&mut self) {
        let dir = self.settings.str("blanks_dir", "");
        if dir.is_empty() {
            self.toast("Сначала выберите папку бланков");
            return;
        }
        let r = rfd::MessageDialog::new()
            .set_title("RedColor")
            .set_description("Убрать «1» во всех бланках папки?\nОригиналы сохранятся в подпапку «_оригиналы с единицами».")
            .set_buttons(rfd::MessageButtons::YesNo)
            .show();
        if r != rfd::MessageDialogResult::Yes {
            return;
        }
        let backup = PathBuf::from(&dir).join("_оригиналы с единицами");
        let (mut files, mut total) = (0, 0);
        for (_, p) in panel::blank_files(&dir) {
            let n = blanks::clean_blank_file(&p, &backup);
            if n > 0 {
                files += 1;
                total += n;
            }
        }
        self.toast(&format!("Обработано бланков: {files}, убрано «1»: {total}"));
    }

    // ------------------------------------------------------------------ цитаты
    pub(crate) fn place_quote(&mut self, page: usize, q: crate::items::P) {
        let Some(qt) = self.quotes.next(&mut self.settings) else {
            self.toast("Список цитат пуст — добавьте цитаты (Меню → Цитаты…)");
            return;
        };
        let (pw, _) = self.page_size_pt(page);
        let t = self.text_props(pw);
        self.checkpoint();
        let k = self.make_text(page, q.x, q.y, None, &qt, t);
        if let Some(d) = self.doc() {
            d.sel = vec![(page, k)];
        }
        self.set_tool("select");
        self.push_overlay();
    }

    pub(crate) fn quote_here(&mut self) {
        let Some(c) = self.cur else { return };
        let pg = self.current_page_index();
        let (pw, ph) = (self.docs[c].pages[pg].w as f64, self.docs[c].pages[pg].h as f64);
        let pos = self.last_mouse.and_then(|(x, y)| self.page_at_pub(x, y)).filter(|(i, _)| *i == pg).map(|(_, q)| q).unwrap_or(p(pw * 0.1, ph * 0.4));
        self.place_quote(pg, pos);
    }

    pub(crate) fn add_selected_to_quotes(&mut self) {
        let Some(c) = self.cur else { return };
        let texts: Vec<String> = self
            .selected_texts()
            .into_iter()
            .filter_map(|(pg, k)| self.docs[c].items[pg][k].as_text().map(|t| t.plain().replace('\n', " ").replace(crate::text::OBJ, "")))
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();
        if texts.is_empty() {
            self.toast("Выделите текстовый блок");
            return;
        }
        self.quotes.reload(&self.settings);
        let mut all = self.quotes.quotes.clone();
        let n = texts.len();
        for t in texts {
            if !all.contains(&t) {
                all.push(t);
            }
        }
        self.quotes.save(&mut self.settings, &all.join("\n"));
        self.toast(&format!("Добавлено в цитаты: {n}"));
    }

    pub(crate) fn quotes_dialog(&mut self) {
        self.quotes.reload(&self.settings);
        let w = self.win();
        w.set_quotes_text(self.quotes.quotes.join("\n").into());
        w.set_dialog("quotes".into());
    }

    // ------------------------------------------------------------------ файлы
    fn add_unsaved_doc(&mut self, data: Vec<u8>, title: &str) {
        let tmp = std::env::temp_dir().join(format!("redcolor_{}_{}", std::process::id(), title));
        if std::fs::write(&tmp, &data).is_ok() {
            let count = self.docs.len();
            self.open_paths(vec![tmp.clone()]);
            if self.docs.len() > count {
                let c = self.docs.len() - 1;
                self.docs[c].path = None;
                self.docs[c].title = title.to_string();
                self.docs[c].modified = true;
                self.refresh_tabs();
            }
            let _ = std::fs::remove_file(tmp);
        }
    }

    pub(crate) fn new_blank_pdf(&mut self) {
        let mut doc = mupdf::pdf::PdfDocument::new();
        if doc.new_page(mupdf::Size::new(595.28, 841.89)).is_ok() {
            let mut b = Vec::new();
            if doc.write_to(&mut b).is_ok() {
                self.add_unsaved_doc(b, "Новый документ.pdf");
            }
        }
    }

    pub(crate) fn merge_files(&mut self) {
        let Some(files) = rfd::FileDialog::new()
            .set_title("Объединение файлов")
            .add_filter("PDF и изображения", &["pdf", "png", "jpg", "jpeg"])
            .pick_files()
        else {
            return;
        };
        if self.cur.is_some() {
            let n = files.len();
            for f in files {
                if let Ok(b) = crate::docops::file_as_pdf(&f) {
                    let at = self.docs[self.cur.unwrap()].pages.len();
                    self.insert_pdf_bytes(at, &b);
                }
            }
            self.toast(&format!("Добавлено файлов: {n}"));
            return;
        }
        let mut out = mupdf::pdf::PdfDocument::new();
        for f in files {
            if let Ok(b) = crate::docops::file_as_pdf(&f) {
                if let Ok(src) = mupdf::pdf::PdfDocument::from_bytes(&b) {
                    let _ = out.insert_pdf(&src, mupdf::pdf::InsertPdfOptions { copy_annotations: true, copy_links: true, copy_widgets: true, ..Default::default() });
                }
            }
        }
        let mut b = Vec::new();
        if out.write_to(&mut b).is_ok() {
            self.add_unsaved_doc(b, "Объединённый.pdf");
        }
    }

    pub(crate) fn compress(&mut self) {
        let Some(c) = self.cur else { return };
        let stem = self.docs[c].title.trim_end_matches(".pdf").to_string();
        let Some(path) = rfd::FileDialog::new().set_title("Сжать PDF").add_filter("PDF", &["pdf"]).set_file_name(format!("{stem}_сжатый.pdf")).save_file() else {
            return;
        };
        let r = (|| -> Result<u64, String> {
            let b = self.output_bytes(None)?;
            let doc = mupdf::pdf::PdfDocument::from_bytes(&b).map_err(|e| e.to_string())?;
            let mut o = mupdf::pdf::PdfWriteOptions::default();
            o.set_garbage_level(4);
            o.set_compress(true);
            o.set_compress_images(true);
            o.set_compress_fonts(true);
            o.set_clean(true);
            let mut out = Vec::new();
            doc.write_to_with_options(&mut out, o).map_err(|e| e.to_string())?;
            crate::pdfio::replace_file(&out, &path)?;
            Ok(out.len() as u64)
        })();
        match r {
            Ok(n) => self.toast(&format!("Сжато: {} — {:.1} МБ", path.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default(), n as f64 / 1048576.0)),
            Err(err) => self.toast(&format!("Не удалось сжать: {err}")),
        }
    }

    pub(crate) fn export_images(&mut self) {
        let Some(c) = self.cur else { return };
        let Some(folder) = rfd::FileDialog::new().set_title("Папка для изображений").pick_folder() else { return };
        let stem = self.docs[c].title.trim_end_matches(".pdf").to_string();
        let r = (|| -> Result<usize, String> {
            let b = self.output_bytes(None)?;
            let doc = mupdf::Document::from_bytes(&b, "application/pdf").map_err(|e| e.to_string())?;
            let n = doc.page_count().map_err(|e| e.to_string())?;
            let k = 150.0 / 72.0;
            for i in 0..n {
                let pg = doc.load_page(i).map_err(|e| e.to_string())?;
                let pix = pg.to_pixmap(&mupdf::Matrix::new_scale(k, k), &mupdf::Colorspace::device_rgb(), false, true).map_err(|e| e.to_string())?;
                let f = folder.join(format!("{stem}_{:03}.png", i + 1));
                pix.save_as(&f.to_string_lossy(), mupdf::ImageFormat::PNG).map_err(|e| e.to_string())?;
            }
            Ok(n as usize)
        })();
        match r {
            Ok(n) => self.toast(&format!("Сохранено изображений: {n}")),
            Err(err) => self.toast(&format!("Не удалось: {err}")),
        }
    }

    /// Печать: готовый PDF отдаётся системной печати (программа PDF по умолчанию).
    pub(crate) fn print_doc(&mut self) {
        let Some(c) = self.cur else { return };
        match self.output_bytes(None) {
            Ok(b) => {
                let name = format!("RedColor печать {}", self.docs[c].title);
                let tmp = std::env::temp_dir().join(name);
                if std::fs::write(&tmp, b).is_ok() {
                    let ps = format!("Start-Process -FilePath '{}' -Verb Print", tmp.display().to_string().replace('\'', "''"));
                    let ok = std::process::Command::new("powershell")
                        .args(["-NoProfile", "-WindowStyle", "Hidden", "-Command", &ps])
                        .status()
                        .map(|s| s.success())
                        .unwrap_or(false);
                    if !ok {
                        let _ = std::process::Command::new("explorer").arg(&tmp).spawn();
                        self.toast("Открыт файл для печати");
                    } else {
                        self.toast("Отправлено на печать");
                    }
                }
            }
            Err(err) => self.toast(&format!("Не удалось подготовить печать: {err}")),
        }
    }

    // ------------------------------------------------------------------ поиск
    pub(crate) fn find(&mut self, q: &str) {
        let Some(c) = self.cur else { return };
        let q = q.trim().to_string();
        self.hits.clear();
        self.hit_idx = 0;
        if !q.is_empty() {
            if let Ok(doc) = mupdf::Document::from_bytes(&self.docs[c].src, "application/pdf") {
                for i in 0..self.docs[c].pages.len() {
                    if let Ok(pg) = doc.load_page(i as i32) {
                        if let Ok(quads) = pg.search(&q, 500) {
                            for qd in quads.iter() {
                                let x0 = qd.ul.x.min(qd.ll.x) as f64;
                                let y0 = qd.ul.y.min(qd.ur.y) as f64;
                                let x1 = qd.ur.x.max(qd.lr.x) as f64;
                                let y1 = qd.ll.y.max(qd.lr.y) as f64;
                                self.hits.push((i, x0, y0, x1 - x0, y1 - y0));
                            }
                        }
                    }
                }
            }
        }
        let w = self.win();
        w.set_find_info(if q.is_empty() { SharedString::new() } else if self.hits.is_empty() { "Не найдено".into() } else { format!("1 из {}", self.hits.len()).into() });
        self.push_hits();
        self.goto_hit();
    }

    pub(crate) fn find_step(&mut self, d: i64) {
        if self.hits.is_empty() {
            return;
        }
        let n = self.hits.len() as i64;
        self.hit_idx = ((self.hit_idx as i64 + d).rem_euclid(n)) as usize;
        self.win().set_find_info(format!("{} из {}", self.hit_idx + 1, n).into());
        self.push_hits();
        self.goto_hit();
    }

    fn goto_hit(&mut self) {
        let Some(&(pg, _x, y, _, _)) = self.hits.get(self.hit_idx) else { return };
        let Some(c) = self.cur else { return };
        let vh = self.win().get_view_h() as f64;
        let z = self.docs[c].zoom as f64;
        let top = (self.docs[c].pages[pg].y as f64 + y) * z - vh / 3.0;
        let maxy = (self.docs[c].content_h as f64 - vh).max(0.0);
        self.win().set_view_y(-(top.clamp(0.0, maxy)) as f32);
        self.update_render();
    }

    pub(crate) fn push_hits(&mut self) {
        let w = self.win();
        let Some(c) = self.cur else { return };
        let z = self.docs[c].zoom as f64;
        let v: Vec<SelView> = self
            .hits
            .iter()
            .map(|&(pg, x, y, hw, hh)| {
                let (ox, oy) = self.page_view_origin(pg);
                SelView { x: (ox + x * z) as f32, y: (oy + y * z) as f32, w: (hw * z) as f32, h: (hh * z) as f32 }
            })
            .collect();
        w.set_hit_current(self.hit_idx as i32);
        w.set_hits(ModelRc::new(VecModel::from(v)));
    }

    // ------------------------------------------------------------------ диалоги
    pub(crate) fn input_dialog(&mut self, title: &str, label: &str, value: &str, id: &str) {
        let w = self.win();
        w.set_input_title(title.into());
        w.set_input_label(label.into());
        w.set_input_text(value.into());
        w.set_input_id(id.into());
        w.set_dialog("input".into());
    }

    pub(crate) fn input_done(&mut self, id: &str, text: &str) {
        self.win().set_dialog("".into());
        let t = text.trim();
        if let Some(s) = id.strip_prefix("sign.rename:") {
            if !t.is_empty() {
                images::sig_rename(s, t);
                self.refresh_signatures();
            }
        } else if id == "goto" {
            if let Ok(n) = t.parse::<i64>() {
                self.go_to_page(n - 1);
            }
        } else if id == "extract" {
            let n = self.cur.map(|c| self.docs[c].pages.len()).unwrap_or(0);
            let pages = crate::docops::parse_ranges(t, n);
            slint::Timer::single_shot(std::time::Duration::from_millis(1), move || {
                with_app(|a| a.extract_pages_dialog(pages));
            });
        }
    }

    pub(crate) fn settings_dialog(&mut self) {
        let w = self.win();
        let s = &self.settings;
        w.set_set_light(s.str("theme", "dark") == "light");
        w.set_set_auto_quote(s.bool("auto_quote_on_blank", true));
        w.set_set_remove_one(s.bool("remove_stray_one", true));
        w.set_set_remove_ones_open(s.bool("auto_remove_ones", true));
        w.set_set_auto_size(s.bool("text_size_auto", true));
        w.set_set_pct(format!("{}", s.f64("auto_size_pct", 2.0)).into());
        w.set_set_quote_size(format!("{}", s.f64("quote_default_size", 16.0)).into());
        w.set_set_quote_font(crate::text::resolve_family(&self.fonts, &s.str("quote_font", "Minion Pro")).into());
        w.set_set_hl_color(panel::color(&s.str("hl_color", "#ffd400")));
        w.set_set_hl_width(format!("{}", s.f64("hl_width", 12.0)).into());
        w.set_dialog("settings".into());
    }

    pub(crate) fn settings_save(&mut self) {
        let w = self.win();
        let s = &mut self.settings;
        let light = w.get_set_light();
        s.set("theme", json!(if light { "light" } else { "dark" }));
        s.set("auto_quote_on_blank", json!(w.get_set_auto_quote()));
        s.set("remove_stray_one", json!(w.get_set_remove_one()));
        s.set("auto_remove_ones", json!(w.get_set_remove_ones_open()));
        s.set("text_size_auto", json!(w.get_set_auto_size()));
        if let Ok(v) = w.get_set_pct().replace(',', ".").parse::<f64>() {
            s.set("auto_size_pct", json!(v.clamp(0.5, 10.0)));
        }
        if let Ok(v) = w.get_set_quote_size().replace(',', ".").parse::<f64>() {
            s.set("quote_default_size", json!(v.clamp(4.0, 72.0)));
        }
        s.set("quote_font", json!(w.get_set_quote_font().to_string()));
        s.set("hl_color", json!(panel::hex(w.get_set_hl_color())));
        if let Ok(v) = w.get_set_hl_width().replace(',', ".").parse::<f64>() {
            s.set("hl_width", json!(v.clamp(2.0, 60.0)));
        }
        s.save();
        crate::Theme::get(&w).set_dark(!light);
        w.set_dialog("".into());
        self.push_text_props();
    }

    pub(crate) fn hotkeys_dialog(&mut self) {
        let mut lines = vec![
            "Файл: Ctrl+O открыть · Ctrl+S сохранить · Ctrl+Shift+S сохранить как · Ctrl+P печать · Ctrl+W закрыть".to_string(),
            "Правка: Ctrl+Z / Ctrl+Y отмена и повтор · Del удалить · Ctrl+D дублировать · Ctrl+A всё на странице · Esc снять выделение".into(),
            "Вид: Ctrl+= / Ctrl+- масштаб · Ctrl+1 реальный · Ctrl+2 по ширине · Ctrl+0 страница · Ctrl+колесо — масштаб · F4 левая панель · Ctrl+F поиск".into(),
            "Страницы: PgUp/PgDn · Ctrl+Home/End · Ctrl+Shift+N перейти · Ctrl+Shift+T пустая страница · Ctrl+Shift+D удалить · Ctrl+Shift+E извлечь · Ctrl+Shift+I вставить из файла".into(),
            "Текст: T инструмент · Ctrl+B / Ctrl+I · Ctrl+] / Ctrl+[ размер · Alt+1..4 цвет (красный, чёрный, синий, зелёный) · Ctrl+Shift+F по странице".into(),
            "Бланки и цитаты: B меню бланков · Q цитата щелчком · Shift+Q цитата под курсором · Ctrl+Alt+1 убрать «1» · Ctrl+Alt+Q цитаты".into(),
            String::new(),
            "Инструменты:".into(),
        ];
        for (k, t) in panel::TOOL_KEYS {
            lines.push(format!("    {} — {}", k.to_uppercase(), panel::action_name(&format!("tool.{t}"))));
        }
        lines.push(String::new());
        lines.push("Текст можно схватить и двигать в любом режиме; углы рамки — масштаб текста, бока — ширина строки.".into());
        let w = self.win();
        w.set_info_title("Горячие клавиши".into());
        w.set_info_text(lines.join("\n").into());
        w.set_dialog("info".into());
    }

    pub(crate) fn about(&mut self) {
        let w = self.win();
        w.set_info_title("О программе".into());
        w.set_info_text(
            format!(
                "RedColor {}\nРедактор PDF для проверки работ\n\nАвтор: Maksim Belonoskin, Zelenograd, Moscow, Russia\n© 2026 Maksim Belonoskin, Zelenograd, Moscow, Russia\n\nДанные пользователя (цитаты, подписи, настройки):\n{}",
                crate::APP_VERSION,
                crate::settings::data_dir().display()
            )
            .into(),
        );
        w.set_dialog("info".into());
    }

    pub(crate) fn show_info(&mut self) {
        let exe_dir = std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf())).unwrap_or_default();
        let candidates = [exe_dir.join("Информация RedColor.html"), exe_dir.join("assets").join("info.html"), PathBuf::from(r"C:\RedColor\assets\info.html")];
        match candidates.iter().find(|p| p.exists()) {
            Some(p) => {
                let _ = std::process::Command::new("explorer").arg(p).spawn();
            }
            None => self.hotkeys_dialog(),
        }
    }

    /// RedColor — программа для PDF (только для текущего пользователя).
    pub(crate) fn make_default(&mut self) {
        use winreg::RegKey;
        use winreg::enums::HKEY_CURRENT_USER;
        let exe = std::env::current_exe().map(|p| p.display().to_string()).unwrap_or_default();
        let cmd = format!("\"{exe}\" \"%1\"");
        let ico = format!("{exe},0");
        let h = RegKey::predef(HKEY_CURRENT_USER);
        let set = |path: &str, name: &str, val: &str| -> std::io::Result<()> {
            let (k, _) = h.create_subkey(path)?;
            k.set_value(name, &val.to_string())
        };
        let base = r"Software\Classes\BlueColor.PDF";
        let r = (|| -> std::io::Result<()> {
            set(base, "", "Документ PDF (BlueColor)")?;
            set(base, "FriendlyTypeName", "Документ PDF")?;
            set(&format!(r"{base}\DefaultIcon"), "", &ico)?;
            set(&format!(r"{base}\Application"), "ApplicationName", "BlueColor")?;
            set(&format!(r"{base}\Application"), "ApplicationIcon", &ico)?;
            set(&format!(r"{base}\Application"), "ApplicationDescription", "Редактор PDF для проверки работ")?;
            set(&format!(r"{base}\Application"), "ApplicationCompany", "Maksim Belonoskin, Zelenograd, Moscow, Russia")?;
            set(&format!(r"{base}\shell"), "", "open")?;
            set(&format!(r"{base}\shell\open"), "FriendlyAppName", "BlueColor")?;
            set(&format!(r"{base}\shell\open\command"), "", &cmd)?;
            set(r"Software\Classes\.pdf\OpenWithProgids", "BlueColor.PDF", "")?;
            let cap = r"Software\BlueColor\Capabilities";
            set(cap, "ApplicationName", "BlueColor")?;
            set(cap, "ApplicationIcon", &ico)?;
            set(cap, "ApplicationDescription", "Редактор PDF для проверки работ")?;
            set(&format!(r"{cap}\FileAssociations"), ".pdf", "BlueColor.PDF")?;
            set(r"Software\RegisteredApplications", "BlueColor", cap)?;
            Ok(())
        })();
        match r {
            Ok(()) => {
                let _ = std::process::Command::new("explorer").arg("ms-settings:defaultapps?registeredAppUser=BlueColor").spawn();
                rfd::MessageDialog::new()
                    .set_title("BlueColor")
                    .set_description("BlueColor зарегистрирован как программа для PDF.\n\nВ открывшемся окне Windows выберите BlueColor для PDF.")
                    .show();
            }
            Err(err) => self.toast(&format!("Не удалось зарегистрировать: {err}")),
        }
    }

    // ------------------------------------------------------------------ новая подпись
    pub(crate) fn open_signature_dialog(&mut self, kind: &str) {
        self.sig_strokes.clear();
        self.sig_kind = kind.to_string();
        let w = self.win();
        w.set_sig_title(if kind == "initials" { "Добавить инициалы".into() } else { "Добавить подпись".into() });
        w.set_sig_name(if kind == "initials" { "Инициалы".into() } else { "Подпись".into() });
        w.set_sig_mode("draw".into());
        w.set_sig_typed("".into());
        let pretty: Vec<SharedString> = ["Segoe Script", "Segoe Print", "Gabriola", "Caveat", "Marck Script", "Bad Script", "Pacifico", "Lobster", "Amatic SC", "Comic Sans MS"]
            .iter()
            .filter(|f| self.fonts.contains_key(**f))
            .map(|s| SharedString::from(*s))
            .collect();
        let first = pretty.first().cloned().unwrap_or_else(|| "Arial".into());
        w.set_sig_fonts(ModelRc::new(VecModel::from(pretty)));
        w.set_sig_font(first);
        w.set_sig_path("".into());
        w.set_sig_image_path("".into());
        w.set_dialog("signature".into());
    }

    pub(crate) fn sig_pointer(&mut self, kind: &str, x: f64, y: f64) {
        match kind {
            "down" => self.sig_strokes.push(vec![(x, y)]),
            "move" => {
                if let Some(s) = self.sig_strokes.last_mut() {
                    s.push((x, y));
                }
            }
            "clear" => self.sig_strokes.clear(),
            _ => {}
        }
        let mut d = String::new();
        for s in &self.sig_strokes {
            for (i, (x, y)) in s.iter().enumerate() {
                d += &format!("{} {x:.1} {y:.1} ", if i == 0 { "M" } else { "L" });
            }
        }
        self.win().set_sig_path(d.into());
    }

    pub(crate) fn sig_save(&mut self) {
        let w = self.win();
        let mode = w.get_sig_mode().to_string();
        let png = match mode.as_str() {
            "draw" => images::signature_from_strokes(&self.sig_strokes, 480.0, 180.0, 3.0),
            "type" => {
                let t = w.get_sig_typed().to_string();
                let fam = w.get_sig_font().to_string();
                crate::text::file_for(&self.fonts, &fam, false, false)
                    .and_then(|f| self.text_cache.load(&f))
                    .and_then(|f| images::signature_from_text(t.trim(), &f))
            }
            _ => {
                let p = w.get_sig_image_path().to_string();
                std::fs::read(&p).ok().and_then(|d| images::signature_from_image(&d))
            }
        };
        let Some(png) = png else {
            self.toast("Подпись пустая — нарисуйте, введите текст или выберите картинку");
            return;
        };
        let name = w.get_sig_name().to_string();
        let sid = images::sig_add(&png, if name.trim().is_empty() { "Подпись" } else { name.trim() }, &self.sig_kind.clone());
        w.set_dialog("".into());
        self.refresh_signatures();
        self.arm_signature(&sid);
    }

    pub(crate) fn place_formula(&mut self, page: usize, q: crate::items::P) {
        let Some(c) = self.cur else { return };
        let key = self.docs[c].key;
        let ver = self.docs[c].ver;
        self.set_tool("select");
        self.formula_dialog(key, ver, page, q, None);
    }

    pub(crate) fn formula_at(&self, page: usize, idx: usize, q: crate::items::P) -> Option<(String, usize)> {
        let c = self.cur?;
        let item = self.docs[c].items.get(page)?.get(idx)?;
        let t = item.as_text()?;
        let pt = item.unmap(q);
        let mut counts = std::collections::HashMap::<String, usize>::new();
        for line in self.text_layout(t).lines {
            for f in line.formulas {
                let n = counts.entry(f.key.clone()).or_default();
                let occurrence = *n;
                *n += 1;
                if pt.x >= f.x && pt.x <= f.x + f.w && pt.y >= f.y && pt.y <= f.y + f.h {
                    return Some((f.key, occurrence));
                }
            }
        }
        None
    }

    pub(crate) fn edit_formula_at(&mut self, page: usize, idx: usize, key: String, occurrence: usize) {
        let Some(c) = self.cur else { return };
        let Some(item) = self.docs[c].items.get(page).and_then(|v| v.get(idx)).cloned() else { return };
        self.formula_dialog(self.docs[c].key, self.docs[c].ver, page, p(0.0, 0.0), Some((idx, key, occurrence, item)));
    }

    fn formula_dialog(&mut self, doc_key: u64, ver: u64, page: usize, q: crate::items::P, edit: Option<(usize, String, usize, Item)>) {
        let fm = edit.as_ref().and_then(|(_, k, _, item)| item.as_text()?.formulas.get(k));
        let req = json!({"kind":"dialog", "latex":fm.map(|f| f.latex.as_str()).unwrap_or(""),
            "svg":fm.map(|f| f.svg.as_ref()).unwrap_or("")});
        let edit = edit.map(|(i, k, n, item)| (i, k, n, serde_json::to_value(item).ok()));
        std::thread::spawn(move || {
            let result = crate::formula_bridge::run(req);
            let _ = slint::invoke_from_event_loop(move || {
                with_app(|a| {
                    let value = match result {
                        Ok(v) if v.get("cancelled").and_then(|x| x.as_bool()) == Some(true) => return,
                        Ok(v) => v,
                        Err(e) => { a.toast(&format!("Не удалось открыть редактор формул: {e}")); return; }
                    };
                    let Some(key) = value.get("key").and_then(|x| x.as_str()).map(str::to_string) else { return };
                    let Some(f) = value.get("formula").cloned().and_then(|v| serde_json::from_value::<crate::text::Formula>(v).ok()) else { return };
                    let Some(c) = a.cur else { return };
                    if a.docs[c].key != doc_key || a.docs[c].ver != ver || page >= a.docs[c].pages.len() {
                        a.toast("Документ изменился; повторите работу с формулой"); return;
                    }
                    if let Some((idx, old_key, occurrence, original)) = edit {
                        if a.docs[c].items.get(page).and_then(|v| v.get(idx)).and_then(|i| serde_json::to_value(i).ok()) != original {
                            a.toast("Текст изменился; повторите работу с формулой"); return;
                        }
                        a.checkpoint();
                        let t = a.docs[c].items[page][idx].as_text_mut().unwrap();
                        let mut n = 0;
                        for r in t.blocks.iter_mut().flat_map(|b| b.runs.iter_mut()) {
                            if let Run::F(k, _) = r {
                                if *k == old_key {
                                    if n == occurrence { *k = key.clone(); break; }
                                    n += 1;
                                }
                            }
                        }
                        t.formulas.insert(key, f);
                        if !t.blocks.iter().flat_map(|b| &b.runs).any(|r| matches!(r, Run::F(k, _) if *k == old_key)) {
                            t.formulas.remove(&old_key);
                        }
                    } else {
                        let pw = a.docs[c].pages[page].w as f64;
                        let mut t = a.text_props(pw);
                        t.blocks = vec![crate::text::Block { align: None, runs: vec![Run::F(key.clone(), false)] }];
                        t.formulas.insert(key, f);
                        a.checkpoint();
                        let idx = a.make_rich_text(page, q.x, q.y, None, t);
                        a.docs[c].sel = vec![(page, idx)];
                    }
                    a.fix_text_heights();
                    a.push_overlay();
                });
            });
        });
    }

    pub(crate) fn page_at_pub(&self, x: f64, y: f64) -> Option<(usize, crate::items::P)> {
        self.page_at_strict(x, y)
    }
}

pub(crate) fn connect(win: &crate::AppWindow) {
    win.on_menu_pick(|id| {
        let id = id.to_string();
        with_app(|a| a.win().set_menu_visible(false));
        slint::Timer::single_shot(std::time::Duration::from_millis(1), move || {
            with_app(|a| a.action(&id));
        });
    });
    win.on_quotes_save(|t| {
        with_app(|a| {
            a.quotes.save(&mut a.settings, &t);
            a.win().set_dialog("".into());
            a.toast(&format!("Цитат: {}", a.quotes.quotes.len()));
        });
    });
    win.on_quotes_import(|| {
        slint::Timer::single_shot(std::time::Duration::from_millis(1), || {
            with_app(|a| {
                if let Some(p) = rfd::FileDialog::new().add_filter("Текст", &["txt"]).pick_file() {
                    if let Ok(s) = std::fs::read_to_string(p) {
                        let cur = a.win().get_quotes_text().to_string();
                        let merged = if cur.trim().is_empty() { s } else { format!("{}\n{}", cur.trim_end(), s) };
                        a.win().set_quotes_text(merged.trim_start_matches('\u{feff}').into());
                    }
                }
            });
        });
    });
    win.on_quotes_export(|| {
        slint::Timer::single_shot(std::time::Duration::from_millis(1), || {
            with_app(|a| {
                if let Some(p) = rfd::FileDialog::new().add_filter("Текст", &["txt"]).set_file_name("цитаты.txt").save_file() {
                    let _ = std::fs::write(p, a.win().get_quotes_text().as_str());
                }
            });
        });
    });
    win.on_input_ok(|id, t| {
        with_app(|a| a.input_done(id.as_str(), t.as_str()));
    });
    win.on_settings_save(|| {
        with_app(|a| a.settings_save());
    });
    win.on_find_text(|q| {
        with_app(|a| a.find(q.as_str()));
    });
    win.on_find_step(|d| {
        with_app(|a| a.find_step(d as i64));
    });
    win.on_find_close(|| {
        with_app(|a| {
            a.hits.clear();
            a.push_hits();
            a.win().set_find_visible(false);
        });
    });
    win.on_sig_pointer(|k, x, y| {
        with_app(|a| a.sig_pointer(k.as_str(), x as f64, y as f64));
    });
    win.on_sig_save(|| {
        with_app(|a| a.sig_save());
    });
    win.on_sig_pick_image(|| {
        slint::Timer::single_shot(std::time::Duration::from_millis(1), || {
            with_app(|a| {
                if let Some(p) = rfd::FileDialog::new().add_filter("Изображения", &["png", "jpg", "jpeg", "bmp"]).pick_file() {
                    a.win().set_sig_image_path(p.display().to_string().into());
                }
            });
        });
    });
    win.on_canvas_hover(|x, y| {
        with_app(|a| {
            a.last_mouse = Some((x as f64, y as f64));
            a.canvas_hover(x as f64, y as f64);
        });
    });
    win.on_edit_escape(|| {
        with_app(|a| a.finish_edit());
    });
}

pub fn _unused(_: Run) {}
