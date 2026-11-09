// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Буфер обмена: копирование пометок между страницами и документами, вставка текста и картинок.

use crate::{App, with_app};
use crate::items::{Item, p};
use crate::text::{Block, Run, Text};

#[derive(Clone)]
enum Target {
    Page { key: u64, ver: u64, page: usize, x: f64, y: f64 },
    Editor { key: u64, page: usize, idx: usize, start: usize, end: usize, before: String },
}

fn text_fragment(text: &str, mut template: Text) -> Text {
    template.formulas.clear();
    template.blocks = text.replace("\r\n", "\n").replace('\r', "\n").split('\n')
        .map(|line| Block { align: None, runs: if line.is_empty() { vec![] } else { vec![Run::T(line.into())] } }).collect();
    template
}

fn decode_fragment(value: &serde_json::Value) -> Result<Text, String> {
    let v = serde_json::json!({"kind":"text", "x":0, "y":0, "w":200,
        "runs":value.get("blocks").cloned().unwrap_or_default(),
        "formulas":value.get("formulas").cloned().unwrap_or_default()});
    match serde_json::from_value::<Item>(v).map_err(|e| e.to_string())? {
        Item::Text(t) => Ok(t),
        _ => Err("Неверный формат вставки".into()),
    }
}

impl App {
    pub(crate) fn copy(&mut self, cut: bool) {
        let Some(c) = self.cur else { return };
        let d = &self.docs[c];
        if d.sel.is_empty() {
            return;
        }
        let items: Vec<Item> = d.sel.iter().filter_map(|&(pg, k)| d.items.get(pg).and_then(|v| v.get(k)).cloned()).collect();
        let text: Vec<String> = items.iter().filter_map(|i| i.as_text().map(|t| t.plain().replace(crate::text::OBJ, "[формула]"))).collect();
        self.clipboard_items = items;
        if let Ok(mut cb) = arboard::Clipboard::new() {
            let marker = if text.is_empty() { "\u{2063}RedColor".to_string() } else { text.join("\n") };
            let _ = cb.set_text(marker.clone());
            self.clipboard_marker = marker;
        }
        if cut {
            self.delete_selected();
        }
    }

    /// Вставка: свои пометки (если буфер не менялся), иначе картинка или текст из других программ.
    pub(crate) fn paste(&mut self) {
        let Some(c) = self.cur else { return };
        let pg = self.current_page_index();
        let (pw, ph) = (self.docs[c].pages[pg].w as f64, self.docs[c].pages[pg].h as f64);
        let target = self
            .last_mouse
            .and_then(|(x, y)| self.page_at_pub(x, y))
            .filter(|(i, _)| *i == pg)
            .map(|(_, q)| q)
            .unwrap_or(p(pw * 0.1, ph * 0.3));
        let mut cb = arboard::Clipboard::new().ok();
        let sys_text = cb.as_mut().and_then(|c| c.get_text().ok()).unwrap_or_default();
        if !self.clipboard_items.is_empty() && sys_text == self.clipboard_marker {
            self.checkpoint();
            let list = self.clipboard_items.clone();
            let d = &mut self.docs[c];
            let mut sel = Vec::new();
            for mut it in list {
                it.translate(10.0, 10.0);
                d.items[pg].push(it);
                sel.push((pg, d.items[pg].len() - 1));
            }
            d.sel = sel;
            // следующая вставка — ещё на 10 pt дальше
            for it in self.clipboard_items.iter_mut() {
                it.translate(10.0, 10.0);
            }
            self.push_overlay();
            return;
        }
        let html = clipboard_html().or_else(|| cb.as_mut().and_then(|c| c.get().html().ok()));
        let destination = Target::Page { key: self.docs[c].key, ver: self.docs[c].ver, page: pg, x: target.x, y: target.y };
        if let Some(html) = html.filter(|s| may_contain_formula(s)) {
            self.parse_html_async(html, destination);
            return;
        }
        if let Some(img) = cb.as_mut().and_then(|c| c.get_image().ok()) {
            if sys_text.trim().is_empty() {
                let png = crate::images::encode_png(img.width as u32, img.height as u32, &img.bytes);
                self.insert_image_data(pg, target, &png, false, None, None);
                return;
            }
        }
        let t = sys_text.replace("\r\n", "\n").replace('\r', "\n");
        let t = t.trim_end_matches('\n');
        if t.trim().is_empty() {
            return;
        }
        if self.editing.is_some() {
            return; // в поле правки вставляет само поле
        }
        let props = self.text_props(pw);
        self.checkpoint();
        let k = self.make_text(pg, target.x, target.y, None, t, props);
        if let Some(d) = self.doc() {
            d.sel = vec![(pg, k)];
        }
        self.push_overlay();
    }

    pub(crate) fn paste_in_editor(&mut self, anchor: usize, focus: usize) {
        let Some(c) = self.cur else { return };
        let Some(e) = self.editing.as_ref() else { return };
        let target = Target::Editor { key: self.docs[c].key, page: e.page, idx: e.idx,
            start: anchor.min(focus), end: anchor.max(focus), before: self.win().get_edit_text().to_string() };
        let Ok(mut cb) = arboard::Clipboard::new() else { return };
        if let Some(html) = clipboard_html().or_else(|| cb.get().html().ok()).filter(|s| may_contain_formula(s)) {
            self.parse_html_async(html, target);
            return;
        }
        let Ok(text) = cb.get_text() else { return };
        let t = text_fragment(&text, self.text_props(self.docs[c].pages[e.page].w as f64));
        self.apply_fragment(target, t);
    }

    fn parse_html_async(&mut self, html: String, target: Target) {
        self.toast("Обработка формул…");
        std::thread::spawn(move || {
            let result = crate::formula_bridge::run(serde_json::json!({"kind":"html", "html":html}));
            let _ = slint::invoke_from_event_loop(move || {
                with_app(|a| match result.and_then(|v| decode_fragment(&v)) {
                    Ok(t) if !t.is_empty() => a.apply_fragment(target, t),
                    Ok(_) => a.toast("В буфере нет текста или формул"),
                    Err(e) => a.toast(&format!("Не удалось вставить формулы: {e}")),
                });
            });
        });
    }

    fn apply_fragment(&mut self, target: Target, fragment: Text) {
        let Some(c) = self.cur else { return };
        match target {
            Target::Page { key, ver, page, x, y } => {
                if self.docs[c].key != key || self.docs[c].ver != ver || page >= self.docs[c].pages.len() {
                    self.toast("Документ изменился; повторите вставку");
                    return;
                }
                let pw = self.docs[c].pages[page].w as f64;
                let mut t = self.text_props(pw);
                t.blocks = fragment.blocks;
                t.formulas = fragment.formulas;
                self.checkpoint();
                let idx = self.make_rich_text(page, x, y, None, t);
                self.docs[c].sel = vec![(page, idx)];
                self.push_overlay();
            }
            Target::Editor { key, page, idx, start, end, before } => {
                if self.docs[c].key != key || self.win().get_edit_text().as_str() != before ||
                    !self.editing.as_ref().is_some_and(|e| e.page == page && e.idx == idx) {
                    self.toast("Текст изменился; повторите вставку");
                    return;
                }
                let Some(t) = self.docs[c].items.get_mut(page).and_then(|v| v.get_mut(idx)).and_then(|i| i.as_text_mut()) else { return };
                if t.replace_range(start, end, &fragment).is_err() {
                    self.toast("Не удалось вставить в это место");
                    return;
                }
                let text = t.plain();
                let cursor = start + fragment.plain().len();
                let contains_formulas = !fragment.formulas.is_empty();
                let w = self.win();
                w.set_edit_text(text.into());
                if contains_formulas {
                    // Slint's plain TextInput cannot draw inline SVG. Commit the field
                    // so the vector formula layer is visible immediately.
                    self.finish_edit();
                } else {
                    w.set_edit_cursor(cursor as i32);
                    w.set_edit_cursor_gen(w.get_edit_cursor_gen() + 1);
                }
            }
        }
    }
}

fn may_contain_formula(html: &str) -> bool {
    let s = html.to_ascii_lowercase();
    s.contains("<img") || s.contains("katex") || s.contains("mathjax") || s.contains("<math") || s.contains("mjx-container")
}

/// arboard returns only the fragment, discarding SourceURL needed for relative SVG links.
fn clipboard_html() -> Option<String> {
    let _open = clipboard_win::Clipboard::new_attempts(5).ok()?;
    let format = clipboard_win::raw::register_format("HTML Format")?;
    let mut bytes = Vec::new();
    clipboard_win::raw::get_vec(format.get(), &mut bytes).ok()?;
    while bytes.last() == Some(&0) { bytes.pop(); }
    String::from_utf8(bytes).ok()
}
