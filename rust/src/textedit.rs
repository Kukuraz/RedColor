// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Текст на странице: создание, правка, формат, показ (с формулами).

use slint::Image;

use crate::items::{Item, P};
use crate::panel::color;
use crate::text::{self, Block, Run, Text};
use crate::{App, FormulaView, TextView};

pub struct Editing {
    pub page: usize,
    pub idx: usize,
    pub before: Vec<Vec<Item>>,
    pub src: std::rc::Rc<Vec<u8>>,
    pub pending_range: Option<(usize, usize)>,
}

impl App {
    /// Свойства нового текста (авторазмер — доля ширины страницы, как в версии на Python).
    pub(crate) fn text_props(&self, page_w: f64) -> Text {
        let s = &self.settings;
        let mut size = s.f64("text_size", 12.0);
        if s.bool("text_size_auto", true) {
            size = (page_w * s.f64("auto_size_pct", 2.0) / 100.0 * 2.0).round() / 2.0;
        }
        let font = text::resolve_family(&self.fonts, &s.str("text_font", "Minion Pro")).to_string();
        Text {
            x: 0.0,
            y: 0.0,
            w: 200.0,
            h: size * 1.2,
            rot: 0.0,
            font,
            size,
            color: s.str("text_color", "#ff0000"),
            bold: s.bool("text_bold", false),
            italic: s.bool("text_italic", false),
            align: s.str("text_align", "left"),
            blocks: vec![Block::default()],
            formulas: Default::default(),
        }
    }

    pub(crate) fn text_layout(&self, t: &Text) -> text::Layout {
        let f = self.text_cache.for_text(&self.fonts, t);
        text::layout(t, f.as_deref(), t.w)
    }

    /// Высота текстов по разметке (после правки, смены шрифта, ширины).
    pub(crate) fn fix_text_heights(&mut self) {
        let Some(c) = self.cur else { return };
        let mut updates = Vec::new();
        for (i, pg) in self.docs[c].items.iter().enumerate() {
            for (k, it) in pg.iter().enumerate() {
                if let Some(t) = it.as_text() {
                    let h = self.text_layout(t).height;
                    if (h - t.h).abs() > 0.01 {
                        updates.push((i, k, h));
                    }
                }
            }
        }
        for (i, k, h) in updates {
            if let Some(t) = self.docs[c].items[i][k].as_text_mut() {
                t.h = h;
            }
        }
    }

    fn formula_image(&self, f: &text::Formula, key: &str, col: &str) -> Image {
        let k = (key.to_string(), col.to_string());
        if let Some(img) = self.formula_imgs.borrow().get(&k) {
            return img.clone();
        }
        let img = Image::load_from_svg_data(f.colored_svg(col).as_bytes()).unwrap_or_default();
        let mut cache = self.formula_imgs.borrow_mut();
        if cache.len() >= 256 {
            cache.clear();
        }
        cache.insert(k, img.clone());
        img
    }

    /// Строки текста и формулы для показа (координаты содержимого, px).
    pub(crate) fn text_views(&self, t: &Text, ox: f64, oy: f64, z: f64, out: &mut Vec<TextView>, fout: &mut Vec<FormulaView>) {
        let lay = self.text_layout(t);
        let (sn, cs) = t.rot.to_radians().sin_cos();
        let map = |q: P| -> (f64, f64) { (ox + (t.x + q.x * cs - q.y * sn) * z, oy + (t.y + q.x * sn + q.y * cs) * z) };
        let fam = text::resolve_family(&self.fonts, &t.font).to_string();
        for line in &lay.lines {
            for sg in &line.segs {
                let (x, y) = map(crate::items::p(sg.x, line.baseline - lay.ascent));
                out.push(TextView {
                    x: x as f32,
                    y: y as f32,
                    text: sg.text.trim_end().into(),
                    size: (t.size * z) as f32,
                    family: fam.clone().into(),
                    bold: t.bold,
                    italic: t.italic,
                    color: color(&t.color),
                });
            }
            for fb in &line.formulas {
                let Some(f) = t.formulas.get(&fb.key) else { continue };
                let (x, y) = map(crate::items::p(fb.x, fb.y));
                fout.push(FormulaView {
                    x: x as f32,
                    y: y as f32,
                    w: (fb.w * z) as f32,
                    h: (fb.h * z) as f32,
                    img: self.formula_image(f, &fb.key, &t.color),
                });
            }
        }
    }

    /// Новый текст по щелчку инструментом «Текст».
    pub(crate) fn create_text(&mut self, page: usize, q: P) {
        let (pw, ph) = self.page_size_pt(page);
        let mut t = self.text_props(pw);
        let margin = pw * 0.04;
        t.x = q.x;
        t.w = (pw - q.x - margin).max(pw * 0.25);
        t.y = (q.y - t.size * 0.6).clamp(0.0, ph);
        let Some(c) = self.cur else { return };
        let before = self.docs[c].items.clone();
        self.docs[c].items[page].push(Item::Text(t));
        let idx = self.docs[c].items[page].len() - 1;
        self.docs[c].sel = vec![(page, idx)];
        let src = self.docs[c].src.clone();
        self.editing = Some(Editing { page, idx, before, src, pending_range: None });
        self.begin_editor(String::new());
    }

    /// Готовый текст (цитата, балл) — вписывается в страницу; возвращает индекс.
    pub(crate) fn make_text(&mut self, page: usize, x: f64, y: f64, width: Option<f64>, s: &str, mut t: Text) -> usize {
        t.blocks = s.split('\n').map(|l| Block { align: None, runs: if l.is_empty() { vec![] } else { vec![Run::T(l.to_string())] } }).collect();
        self.make_rich_text(page, x, y, width, t)
    }

    pub(crate) fn make_rich_text(&mut self, page: usize, x: f64, y: f64, width: Option<f64>, mut t: Text) -> usize {
        let (pw, ph) = self.page_size_pt(page);
        let margin = pw * 0.04;
        t.x = x;
        t.y = y.max(0.0);
        match width {
            Some(w) => t.w = w,
            None => {
                // сначала шире, если не влезает — меньше кегль, потом сдвиг влево
                let full = pw - 2.0 * margin;
                t.w = full;
                let mut need = self.text_layout(&t).ideal_width + 1.0;
                while need > full && t.size > 5.0 {
                    t.size = (t.size * full / need * 2.0).round() / 2.0 - 0.5;
                    need = self.text_layout(&t).ideal_width + 1.0;
                }
                let avail = pw - x - margin;
                if need > avail {
                    t.x = margin.max(pw - margin - need);
                }
                t.w = (pw - t.x - margin).max(need).min(full);
                let ideal = self.text_layout(&t).ideal_width + 1.0;
                t.w = t.w.min(ideal).max(12.0);
            }
        }
        t.h = self.text_layout(&t).height;
        if t.y + t.h > ph {
            t.y = (ph - t.h - margin).max(0.0);
        }
        let c = self.cur.unwrap();
        self.docs[c].items[page].push(Item::Text(t));
        self.docs[c].items[page].len() - 1
    }

    pub(crate) fn page_size_pt(&self, page: usize) -> (f64, f64) {
        self.cur
            .and_then(|c| self.docs[c].pages.get(page))
            .map(|pg| (pg.w as f64, pg.h as f64))
            .unwrap_or((595.0, 842.0))
    }

    pub(crate) fn start_edit(&mut self, page: usize, idx: usize, _select_all: bool) {
        let Some(c) = self.cur else { return };
        let Some(t) = self.docs[c].items.get(page).and_then(|v| v.get(idx)).and_then(|i| i.as_text()) else { return };
        let plain = t.plain();
        let before = self.docs[c].items.clone();
        self.docs[c].sel = vec![(page, idx)];
        let src = self.docs[c].src.clone();
        self.editing = Some(Editing { page, idx, before, src, pending_range: None });
        self.begin_editor(plain);
    }

    fn begin_editor(&mut self, s: String) {
        let w = self.win();
        w.set_edit_text(s.into());
        w.set_edit_active(true);
        w.set_edit_gen(w.get_edit_gen() + 1);
        self.push_overlay();
    }

    /// Поле правки поверх текста — при каждом изменении масштаба и прокрутки.
    pub(crate) fn position_editor(&self) {
        let w = self.win();
        let Some(e) = self.editing.as_ref() else {
            w.set_edit_active(false);
            return;
        };
        let Some(c) = self.cur else { return };
        let Some(t) = self.docs[c].items.get(e.page).and_then(|v| v.get(e.idx)).and_then(|i| i.as_text()) else { return };
        let z = self.docs[c].zoom as f64;
        let (ox, oy) = self.page_view_origin(e.page);
        w.set_edit_x((ox + t.x * z) as f32);
        w.set_edit_y((oy + t.y * z) as f32);
        w.set_edit_w((t.w * z) as f32);
        w.set_edit_size((t.size * z) as f32);
        w.set_edit_family(text::resolve_family(&self.fonts, &t.font).into());
        w.set_edit_bold(t.bold);
        w.set_edit_italic(t.italic);
        w.set_edit_color(color(&t.color));
        w.set_edit_align(t.align.clone().into());
    }

    /// Начало страницы относительно начала содержимого (без центрирования, как у остальных пометок).
    pub(crate) fn page_view_origin(&self, page: usize) -> (f64, f64) {
        let Some(c) = self.cur else { return (0.0, 0.0) };
        let d = &self.docs[c];
        let z = d.zoom as f64;
        let Some(pg) = d.pages.get(page) else { return (0.0, 0.0) };
        ((crate::MARGIN as f64 + (d.max_w() as f64 - pg.w as f64) / 2.0) * z, pg.y as f64 * z)
    }

    /// Конец правки: пустой текст удаляется; изменение — в отмену.
    pub(crate) fn finish_edit(&mut self) {
        let Some(e) = self.editing.take() else { return };
        let w = self.win();
        let s = w.get_edit_text().to_string();
        w.set_edit_active(false);
        let Some(c) = self.cur else { return };
        let d = &mut self.docs[c];
        if let Some(t) = d.items.get_mut(e.page).and_then(|v| v.get_mut(e.idx)).and_then(|i| i.as_text_mut()) {
            t.sync_plain_edit(&s);
            if t.is_empty() {
                d.items[e.page].remove(e.idx);
                d.sel.clear();
            }
        }
        if d.items != e.before {
            d.undo.push(crate::docops::Snap { items: e.before, src: e.src });
            d.redo.clear();
            if !d.modified {
                d.modified = true;
                self.refresh_tabs();
            }
            if self.tool == "quote" || self.tool == "formula" {
                self.set_tool("select");
            }
        }
        self.push_overlay();
    }

    /// Выделенные тексты.
    pub(crate) fn selected_texts(&self) -> Vec<(usize, usize)> {
        let Some(c) = self.cur else { return vec![] };
        let d = &self.docs[c];
        let mut v: Vec<(usize, usize)> =
            d.sel.iter().copied().filter(|&(p, k)| d.items.get(p).and_then(|x| x.get(k)).map(|i| i.is_text()).unwrap_or(false)).collect();
        if let Some(e) = &self.editing {
            if !v.contains(&(e.page, e.idx)) {
                v.push((e.page, e.idx));
            }
        }
        v
    }

    /// Формат из панели — для выделенных текстов (шрифт, кегль, цвет, начертание, выравнивание, «по странице»).
    pub(crate) fn format_selected_texts(&mut self, key: &str, val: &str) {
        let sel = self.selected_texts();
        if sel.is_empty() {
            return;
        }
        let editing = self.editing.is_some();
        if !editing {
            self.checkpoint();
        }
        let pct = self.settings.f64("auto_size_pct", 2.0);
        let c = self.cur.unwrap();
        for (p, k) in sel {
            let pw = self.docs[c].pages[p].w as f64;
            let Some(t) = self.docs[c].items[p][k].as_text_mut() else { continue };
            match key {
                "font" => t.font = val.to_string(),
                "size" => {
                    if let Ok(v) = val.replace(',', ".").parse::<f64>() {
                        if (1.0..=400.0).contains(&v) {
                            t.size = v;
                        }
                    }
                }
                "color" => t.color = val.to_string(),
                "bold" => t.bold = val == "1",
                "italic" => t.italic = val == "1",
                "align" => t.align = val.to_string(),
                "fit" => t.size = (pw * pct / 100.0 * 2.0).round() / 2.0,
                _ => {}
            }
        }
        self.push_overlay();
    }
}
