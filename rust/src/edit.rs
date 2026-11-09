// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Инструменты мыши на холсте, выделение, отмена, сохранение.

use std::path::PathBuf;

use slint::{Model, ModelRc, VecModel};

use crate::items::{self, Item, P, SYMBOLS, Shape, p};
use crate::panel::color;
use crate::{APP_VERSION, App, HandleView, LabelView, MARGIN, PrimView, SelView, with_app};

const HANDLE_PX: f64 = 7.0;
const UNDO_LIMIT: usize = 200;

pub enum Drag {
    Ink { page: usize, pts: Vec<(f64, f64)> },
    Erase { page: usize, started: bool },
    Shape { page: usize, start: P, cur: P, shift: bool },
    Move { page: usize, last: P, moved: bool, click_edit: Option<usize> },
    Resize { page: usize, idx: usize, start: Item, handle: &'static str },
    Band { page: usize, start: P, cur: P },
}

fn is_shape_tool(t: &str) -> bool {
    matches!(t, "ellipse" | "ellipse_num" | "rect" | "line" | "arrow") || SYMBOLS.contains(&t)
}

impl App {
    /// Смещение страницы i в координатах содержимого (px) и масштаб.
    fn page_origin(&self, i: usize) -> Option<(f64, f64, f64)> {
        let c = self.cur?;
        let d = &self.docs[c];
        let pg = d.pages.get(i)?;
        let z = d.zoom as f64;
        let vw = self.win().get_view_w() as f64;
        let full = (d.content_w as f64).max(vw);
        let off = (full - d.content_w as f64) / 2.0;
        let x = off + (MARGIN as f64 + (d.max_w() as f64 - pg.w as f64) / 2.0) * z;
        Some((x, pg.y as f64 * z, z))
    }

    /// Точка содержимого → (страница, точка страницы в pt). strict — только внутри страницы.
    pub(crate) fn page_at_strict(&self, x: f64, y: f64) -> Option<(usize, P)> {
        self.page_at(x, y, true)
    }

    pub(crate) fn page_at(&self, x: f64, y: f64, strict: bool) -> Option<(usize, P)> {
        let c = self.cur?;
        let d = &self.docs[c];
        let mut best: Option<(f64, usize)> = None;
        for i in 0..d.pages.len() {
            let (ox, oy, z) = self.page_origin(i)?;
            let (w, h) = (d.pages[i].w as f64 * z, d.pages[i].h as f64 * z);
            if x >= ox && x <= ox + w && y >= oy && y <= oy + h {
                return Some((i, p((x - ox) / z, (y - oy) / z)));
            }
            let dist = if y < oy { oy - y } else if y > oy + h { y - oy - h } else { 0.0 };
            if best.map(|b| dist < b.0).unwrap_or(true) {
                best = Some((dist, i));
            }
        }
        if strict {
            return None;
        }
        let (_, i) = best?;
        let (ox, oy, z) = self.page_origin(i)?;
        Some((i, p((x - ox) / z, (y - oy) / z)))
    }

    fn to_page(&self, page: usize, x: f64, y: f64) -> P {
        let (ox, oy, z) = self.page_origin(page).unwrap_or((0.0, 0.0, 1.0));
        p((x - ox) / z, (y - oy) / z)
    }

    fn page_size(&self, page: usize) -> (f64, f64) {
        self.cur
            .and_then(|c| self.docs[c].pages.get(page))
            .map(|pg| (pg.w as f64, pg.h as f64))
            .unwrap_or((595.0, 842.0))
    }

    fn clamp_in_page(&self, page: usize, q: P) -> P {
        let (w, h) = self.page_size(page);
        p(q.x.clamp(0.0, w), q.y.clamp(0.0, h))
    }

    fn zoom(&self) -> f64 {
        self.cur.map(|c| self.docs[c].zoom as f64).unwrap_or(1.0)
    }

    /// Снимок объектов для отмены — перед каждым изменением.
    pub(crate) fn checkpoint(&mut self) {
        let Some(d) = self.doc() else { return };
        d.undo.push(crate::docops::Snap { items: d.items.clone(), src: d.src.clone() });
        if d.undo.len() > UNDO_LIMIT {
            d.undo.remove(0);
        }
        d.redo.clear();
        if !d.modified {
            d.modified = true;
            self.refresh_tabs();
        }
    }

    pub(crate) fn undo(&mut self) {
        self.undo_redo(true);
    }

    pub(crate) fn redo(&mut self) {
        self.undo_redo(false);
    }

    fn undo_redo(&mut self, back: bool) {
        if self.editing.is_some() {
            self.finish_edit();
        }
        let Some(d) = self.doc() else { return };
        let snap = if back { d.undo.pop() } else { d.redo.pop() };
        let Some(snap) = snap else { return };
        let cur = crate::docops::Snap { items: std::mem::replace(&mut d.items, snap.items), src: d.src.clone() };
        let src_changed = !std::rc::Rc::ptr_eq(&d.src, &snap.src);
        d.src = snap.src;
        if back {
            d.redo.push(cur);
        } else {
            d.undo.push(cur);
        }
        d.sel.clear();
        d.modified = true;
        self.refresh_tabs();
        if src_changed {
            self.reload_src();
        } else {
            self.push_overlay();
        }
    }

    fn hit_item(&self, page: usize, q: P) -> Option<usize> {
        let c = self.cur?;
        let d = &self.docs[c];
        let tol = 3.0 / self.zoom();
        let items = d.items.get(page)?;
        (0..items.len()).rev().find(|&k| items[k].hit(q, tol, d.sel.contains(&(page, k))))
    }

    fn handle_at(&self, page: usize, q: P) -> Option<(usize, &'static str)> {
        let c = self.cur?;
        let d = &self.docs[c];
        if d.sel.len() != 1 || d.sel[0].0 != page {
            return None;
        }
        let k = d.sel[0].1;
        let it = d.items.get(page)?.get(k)?;
        let hs = HANDLE_PX / self.zoom() * 1.1;
        for (name, hp) in it.handles() {
            let hp = it.map(hp);
            if (q.x - hp.x).abs() <= hs && (q.y - hp.y).abs() <= hs {
                return Some((k, name));
            }
        }
        None
    }

    /// События мыши на холсте (координаты содержимого).
    pub(crate) fn canvas_pointer(&mut self, kind: &str, x: f64, y: f64, shift: bool) {
        if self.cur.is_none() {
            return;
        }
        match kind {
            "down" => self.pointer_down(x, y, shift),
            "move" => self.pointer_move(x, y, shift),
            "up" => self.pointer_up(x, y),
            "double" => {
                if let Some((page, q)) = self.page_at(x, y, true) {
                    if let Some(k) = self.text_hit(page, q) {
                        self.drag = None;
                        if let Some((key, occurrence)) = self.formula_at(page, k, q) {
                            self.edit_formula_at(page, k, key, occurrence);
                        } else {
                            self.start_edit(page, k, false);
                        }
                    }
                }
            }
            _ => {}
        }
    }

    /// Текст под точкой (в любом режиме текст можно схватить).
    pub(crate) fn text_hit(&self, page: usize, q: P) -> Option<usize> {
        let c = self.cur?;
        let d = &self.docs[c];
        let tol = 3.0 / self.zoom();
        let items = d.items.get(page)?;
        let editing = self.editing.as_ref().map(|e| (e.page, e.idx));
        (0..items.len()).rev().find(|&k| items[k].is_text() && editing != Some((page, k)) && items[k].hit(q, tol, true))
    }

    /// Курсор при наведении: над текстом — «переместить», над ручками — «размер».
    pub(crate) fn canvas_hover(&mut self, x: f64, y: f64) {
        let mut cur = "";
        if self.cur.is_some() && self.tool != "hand" {
            if let Some((page, q)) = self.page_at(x, y, true) {
                if let Some((k, h)) = self.handle_at(page, q) {
                    let text = self.docs[self.cur.unwrap()].items[page][k].is_text();
                    if self.tool == "select" || text {
                        cur = match h {
                            "tl" | "br" => "nwse",
                            "tr" | "bl" => "nesw",
                            "t" | "b" => "ns",
                            _ => "ew",
                        };
                    }
                } else if self.text_hit(page, q).is_some() {
                    cur = if self.tool == "text" { "text" } else { "move" };
                } else if self.tool == "select" && self.hit_item(page, q).is_some() {
                    cur = "move";
                }
            }
        }
        let w = self.win();
        if w.get_hover_cursor().as_str() != cur {
            w.set_hover_cursor(cur.into());
        }
    }

    fn pointer_down(&mut self, x: f64, y: f64, shift: bool) {
        let tool = self.tool.clone();
        if self.editing.is_some() {
            self.finish_edit();
        }
        if tool == "hand" {
            return;
        }
        // текст хватается и меняет размер в любом режиме (фигуры и минусы бланков — только в «Выделении»)
        if tool != "select" {
            if let Some((page, q)) = self.page_at(x, y, true) {
                if let Some((idx, handle)) = self.handle_at(page, q) {
                    if self.docs[self.cur.unwrap()].items[page][idx].is_text() {
                        let start = self.docs[self.cur.unwrap()].items[page][idx].clone();
                        self.checkpoint();
                        self.drag = Some(Drag::Resize { page, idx, start, handle });
                        return;
                    }
                }
                if let Some(k) = self.text_hit(page, q) {
                    let d = self.doc().unwrap();
                    d.sel = vec![(page, k)];
                    self.drag = Some(Drag::Move { page, last: q, moved: false, click_edit: Some(k) });
                    self.push_overlay();
                    return;
                }
            }
        }
        if tool == "select" {
            let Some((page, q)) = self.page_at(x, y, true) else {
                if let Some(d) = self.doc() {
                    d.sel.clear();
                }
                self.push_overlay();
                return;
            };
            if let Some((idx, handle)) = self.handle_at(page, q) {
                let start = self.docs[self.cur.unwrap()].items[page][idx].clone();
                self.checkpoint();
                self.drag = Some(Drag::Resize { page, idx, start, handle });
                return;
            }
            match self.hit_item(page, q) {
                Some(k) => {
                    let d = self.doc().unwrap();
                    if shift {
                        if let Some(pos) = d.sel.iter().position(|s| *s == (page, k)) {
                            d.sel.remove(pos);
                        } else {
                            d.sel.push((page, k));
                        }
                    } else if !d.sel.contains(&(page, k)) {
                        d.sel = vec![(page, k)];
                    }
                    d.sel.retain(|s| s.0 == page);
                    self.drag = Some(Drag::Move { page, last: q, moved: false, click_edit: None });
                }
                None => {
                    if let Some(d) = self.doc() {
                        if !shift {
                            d.sel.clear();
                        }
                    }
                    self.drag = Some(Drag::Band { page, start: q, cur: q });
                }
            }
            self.push_overlay();
            return;
        }
        let Some((page, q)) = self.page_at(x, y, true) else { return };
        match tool.as_str() {
            "pencil" | "highlighter" => {
                self.drag = Some(Drag::Ink { page, pts: vec![(q.x, q.y)] });
            }
            "eraser" => {
                self.drag = Some(Drag::Erase { page, started: false });
                self.erase_at(page, q);
            }
            t if is_shape_tool(t) => {
                self.drag = Some(Drag::Shape { page, start: q, cur: q, shift });
            }
            "text" => {
                self.create_text(page, q);
                return;
            }
            "quote" => {
                self.place_quote(page, q);
                return;
            }
            "signature" => {
                self.place_signature(page, q);
                return;
            }
            "image" => {
                self.place_image_dialog(page, q);
                return;
            }
            "formula" => {
                self.place_formula(page, q);
                return;
            }
            _ => return,
        }
        self.push_overlay();
    }

    fn pointer_move(&mut self, x: f64, y: f64, shift: bool) {
        let z = self.zoom();
        let Some(drag) = self.drag.take() else { return };
        let drag = match drag {
            Drag::Ink { page, mut pts } => {
                let q = self.clamp_in_page(page, self.to_page(page, x, y));
                let last = *pts.last().unwrap();
                if ((q.x - last.0).powi(2) + (q.y - last.1).powi(2)).sqrt() * z >= 1.2 {
                    pts.push((q.x, q.y));
                }
                Drag::Ink { page, pts }
            }
            Drag::Erase { page, started } => {
                let q = self.to_page(page, x, y);
                let s = self.erase_at_flag(page, q, started);
                Drag::Erase { page, started: s }
            }
            Drag::Shape { page, start, .. } => {
                let q = self.clamp_in_page(page, self.to_page(page, x, y));
                Drag::Shape { page, start, cur: q, shift }
            }
            Drag::Move { page, last, moved, click_edit } => {
                let q = self.to_page(page, x, y);
                let (dx, dy) = (q.x - last.x, q.y - last.y);
                if !moved && (dx.abs() + dy.abs()) * z < 2.0 {
                    // дрожание руки при щелчке — ещё не перемещение
                    self.drag = Some(Drag::Move { page, last, moved, click_edit });
                    return;
                }
                if !moved {
                    self.checkpoint();
                }
                let d = self.doc().unwrap();
                for &(pg, k) in d.sel.clone().iter() {
                    if let Some(it) = d.items.get_mut(pg).and_then(|v| v.get_mut(k)) {
                        it.translate(dx, dy);
                    }
                }
                Drag::Move { page, last: q, moved: true, click_edit }
            }
            Drag::Resize { page, idx, start, handle } => {
                let q = self.to_page(page, x, y);
                let d = self.doc().unwrap();
                if let Some(it) = d.items.get_mut(page).and_then(|v| v.get_mut(idx)) {
                    it.drag_handle(&start, handle, q, shift);
                }
                Drag::Resize { page, idx, start, handle }
            }
            Drag::Band { page, start, .. } => Drag::Band { page, start, cur: self.to_page(page, x, y) },
        };
        self.drag = Some(drag);
        self.push_overlay();
    }

    fn pointer_up(&mut self, _x: f64, _y: f64) {
        let Some(drag) = self.drag.take() else { return };
        match drag {
            Drag::Ink { page, pts } => {
                let hl = self.tool == "highlighter";
                let s = &self.settings;
                let it = if hl {
                    items::new_ink(&pts, &s.str("hl_color", "#ffd400"), s.f64("hl_width", 12.0), 0.4, true)
                } else {
                    items::new_ink(&pts, &s.str("ink_color", "#ff0000"), s.f64("ink_width", 1.5), 1.0, false)
                };
                self.add_item(page, it, false);
            }
            Drag::Erase { .. } => {}
            Drag::Shape { page, start, cur, shift } => self.finish_shape(page, start, cur, shift),
            Drag::Move { page, moved, click_edit, .. } => {
                // щелчок по тексту инструментом «Текст» — правка
                if let (false, Some(k), "text") = (moved, click_edit, self.tool.as_str()) {
                    self.start_edit(page, k, false);
                    return;
                }
            }
            Drag::Resize { .. } => {}
            Drag::Band { page, start, cur } => {
                let (x0, x1) = (start.x.min(cur.x), start.x.max(cur.x));
                let (y0, y1) = (start.y.min(cur.y), start.y.max(cur.y));
                if (x1 - x0) * self.zoom() > 3.0 || (y1 - y0) * self.zoom() > 3.0 {
                    let d = self.doc().unwrap();
                    for (k, it) in d.items[page].iter().enumerate() {
                        let (ix, iy) = it.pos();
                        let (w, h) = it.size();
                        if ix < x1 && ix + w > x0 && iy < y1 && iy + h > y0 && !d.sel.contains(&(page, k)) {
                            d.sel.push((page, k));
                        }
                    }
                }
            }
        }
        self.push_overlay();
    }

    fn erase_at(&mut self, page: usize, q: P) {
        let _ = self.erase_at_flag(page, q, false);
        self.push_overlay();
    }

    /// Ластик удаляет рисунки от руки под курсором. started — снимок для отмены уже сделан.
    fn erase_at_flag(&mut self, page: usize, q: P, started: bool) -> bool {
        let r = 4.0 / self.zoom();
        let Some(c) = self.cur else { return started };
        let hits: Vec<usize> = self.docs[c].items[page]
            .iter()
            .enumerate()
            .filter(|(_, it)| it.is_ink() && it.hit(q, r, false))
            .map(|(k, _)| k)
            .collect();
        if hits.is_empty() {
            return started;
        }
        if !started {
            self.checkpoint();
        }
        let d = self.doc().unwrap();
        for k in hits.into_iter().rev() {
            d.items[page].remove(k);
        }
        d.sel.clear();
        true
    }

    pub(crate) fn add_item(&mut self, page: usize, it: Item, select: bool) {
        self.checkpoint();
        let d = self.doc().unwrap();
        d.items[page].push(it);
        if select {
            d.sel = vec![(page, d.items[page].len() - 1)];
        }
        self.push_overlay();
    }

    /// Завершение фигуры (перенос _finish_shape из версии на Python).
    fn finish_shape(&mut self, page: usize, start: P, cur: P, shift: bool) {
        let tool = self.tool.clone();
        let z = self.zoom();
        let (mut rx, mut ry) = (start.x.min(cur.x), start.y.min(cur.y));
        let (mut rw, mut rh) = ((cur.x - start.x).abs(), (cur.y - start.y).abs());
        if SYMBOLS.contains(&tool.as_str()) || shift {
            let side = rw.max(rh);
            rx = if cur.x >= start.x { start.x } else { start.x - side };
            ry = if cur.y >= start.y { start.y } else { start.y - side };
            rw = side;
            rh = side;
        }
        let small = rw * z < 4.0 && rh * z < 4.0;
        let (pw, _) = self.page_size(page);
        let unit = pw / 595.0;
        let s = &self.settings;
        let col = s.str("shape_color", &s.str("ink_color", "#ff0000"));
        let width = s.f64("shape_width", s.f64("ink_width", 1.5));
        let mut sh = Shape {
            x: rx,
            y: ry,
            w: rw,
            h: rh,
            rot: 0.0,
            shape: tool.clone(),
            color: col,
            width,
            direction: 0,
            number: None,
            num_size: 12.0,
        };
        if SYMBOLS.contains(&tool.as_str()) {
            let side = if small { 14.0 * unit } else { rw.max(rh) };
            if small {
                sh.x = start.x - side / 2.0;
                sh.y = start.y - side / 2.0;
            }
            sh.w = side;
            sh.h = side;
            sh.width = width.max(1.6 * unit);
        } else if tool == "line" || tool == "arrow" {
            if small {
                sh.x = start.x;
                sh.y = start.y;
                sh.w = 60.0 * unit;
                sh.h = 0.01;
            } else {
                let ex = if (rx - start.x).abs() < 1e-6 { rx + rw } else { rx };
                let ey = if (ry - start.y).abs() < 1e-6 { ry + rh } else { ry };
                sh.direction = match (ex >= start.x, ey >= start.y) {
                    (true, true) => 0,
                    (true, false) => 1,
                    (false, false) => 2,
                    (false, true) => 3,
                };
            }
            sh.w = sh.w.max(0.01);
            sh.h = sh.h.max(0.01);
        } else {
            if small {
                sh.x = start.x - 40.0 * unit;
                sh.y = start.y - 16.0 * unit;
                sh.w = 80.0 * unit;
                sh.h = 32.0 * unit;
            }
            if tool == "ellipse_num" {
                sh.shape = "ellipse".into();
                let c = self.cur.unwrap();
                let max_n = self.docs[c].items[page]
                    .iter()
                    .filter_map(|it| match it {
                        Item::Shape(s) => s.number,
                        _ => None,
                    })
                    .max()
                    .unwrap_or(0);
                sh.number = Some(max_n + 1);
            }
            sh.num_size = 13.0 * unit;
        }
        self.add_item(page, Item::Shape(sh), true);
    }

    pub(crate) fn delete_selected(&mut self) {
        let Some(d) = self.doc() else { return };
        if d.sel.is_empty() {
            return;
        }
        let mut sel = d.sel.clone();
        self.checkpoint();
        let d = self.doc().unwrap();
        sel.sort();
        for (pg, k) in sel.into_iter().rev() {
            if k < d.items[pg].len() {
                d.items[pg].remove(k);
            }
        }
        d.sel.clear();
        self.push_overlay();
    }

    pub(crate) fn duplicate(&mut self) {
        let Some(d) = self.doc() else { return };
        if d.sel.is_empty() {
            return;
        }
        let sel = d.sel.clone();
        self.checkpoint();
        let d = self.doc().unwrap();
        let mut new_sel = Vec::new();
        for (pg, k) in sel {
            let mut c = d.items[pg][k].clone();
            c.translate(12.0, 12.0);
            d.items[pg].push(c);
            new_sel.push((pg, d.items[pg].len() - 1));
        }
        d.sel = new_sel;
        self.push_overlay();
    }

    pub(crate) fn select_all(&mut self) {
        let vh = self.win().get_view_h();
        let Some(d) = self.doc() else { return };
        let pg = d.current_page(vh);
        d.sel = (0..d.items[pg].len()).map(|k| (pg, k)).collect();
        self.push_overlay();
    }

    pub(crate) fn nudge(&mut self, dx: f64, dy: f64) -> bool {
        let Some(d) = self.doc() else { return false };
        if d.sel.is_empty() {
            return false;
        }
        self.checkpoint();
        let d = self.doc().unwrap();
        for &(pg, k) in d.sel.clone().iter() {
            d.items[pg][k].translate(dx, dy);
        }
        self.push_overlay();
        true
    }

    pub(crate) fn has_selection(&self) -> bool {
        self.cur.map(|c| !self.docs[c].sel.is_empty()).unwrap_or(false)
    }

    pub(crate) fn clear_selection(&mut self) -> bool {
        let Some(d) = self.doc() else { return false };
        if d.sel.is_empty() {
            return false;
        }
        d.sel.clear();
        self.push_overlay();
        true
    }

    /// Цвет/толщина из панели — и для выделенных объектов (как в версии на Python).
    pub(crate) fn apply_to_selection(&mut self, color: Option<&str>, width: Option<f64>) {
        if !self.has_selection() {
            return;
        }
        self.checkpoint();
        let d = self.doc().unwrap();
        for &(pg, k) in d.sel.clone().iter() {
            let it = &mut d.items[pg][k];
            if let Some(c) = color {
                it.set_color(c);
            }
            if let Some(w) = width {
                it.set_stroke_width(w);
            }
        }
        self.push_overlay();
    }

    /// Передаёт в интерфейс векторные пометки, выделение и временную фигуру.
    pub(crate) fn push_overlay(&mut self) {
        let w = self.win();
        let Some(c) = self.cur else {
            w.set_prims(ModelRc::default());
            w.set_texts(ModelRc::default());
            w.set_formulas(ModelRc::default());
            w.set_images(ModelRc::default());
            w.set_edit_active(false);
            w.set_labels(ModelRc::default());
            w.set_sels(ModelRc::default());
            w.set_handles(ModelRc::default());
            w.set_has_band(false);
            return;
        };
        self.fix_text_heights();
        let z = self.docs[c].zoom as f64;
        let mut texts: Vec<crate::TextView> = Vec::new();
        let mut fviews: Vec<crate::FormulaView> = Vec::new();
        let mut images: Vec<crate::ImageView> = Vec::new();
        let editing = self.editing.as_ref().map(|e| (e.page, e.idx));
        let mut prims = Vec::new();
        let mut labels = Vec::new();
        let mut sels = Vec::new();
        let mut handles = Vec::new();
        let page_view = |i: usize| -> (f64, f64, f64, f64) {
            let (ox, oy, _) = self.page_origin(i).unwrap_or((0.0, 0.0, z));
            let d = &self.docs[c];
            let vw = w.get_view_w() as f64;
            let full = (d.content_w as f64).max(vw);
            let off = (full - d.content_w as f64) / 2.0;
            (ox - off, oy, d.pages[i].w as f64, d.pages[i].h as f64)
        };
        let mk = |i: usize, it_color: &str, alpha: f64, sw: f64, pr: &items::Prim| -> PrimView {
            let (x, y, pw, ph) = page_view(i);
            let col = color(it_color).with_alpha(alpha as f32);
            PrimView {
                x: x as f32,
                y: y as f32,
                w: (pw * z) as f32,
                h: (ph * z) as f32,
                vbw: pw as f32,
                vbh: ph as f32,
                d: items::svg(&pr.segs).into(),
                stroke: if pr.fill { slint::Color::from_argb_u8(0, 0, 0, 0) } else { col },
                fill: if pr.fill { col } else { slint::Color::from_argb_u8(0, 0, 0, 0) },
                sw: if pr.fill { 0.0 } else { (sw * z) as f32 },
                square: pr.square_cap,
            }
        };
        let d = &self.docs[c];
        // только страницы рядом с видимыми — остальным незачем рисоваться
        let vh = w.get_view_h();
        let cur_page = d.current_page(vh);
        for (i, page_items) in d.items.iter().enumerate() {
            if i + 3 < cur_page || i > cur_page + 3 {
                continue;
            }
            for (k, it) in page_items.iter().enumerate() {
                if let Item::Image(im) = it {
                    let (x, y, _, _) = page_view(i);
                    images.push(crate::ImageView {
                        x: (x + im.x * z) as f32,
                        y: (y + im.y * z) as f32,
                        w: (im.w * z) as f32,
                        h: (im.h * z) as f32,
                        img: self.image_for(im),
                        rot: im.rot as f32,
                    });
                }
                if let Some(t) = it.as_text() {
                    if editing != Some((i, k)) {
                        let (x, y, _, _) = page_view(i);
                        self.text_views(t, x, y, z, &mut texts, &mut fviews);
                    }
                }
                for pr in it.page_prims() {
                    prims.push(mk(i, it.color(), it.opacity(), it.stroke_width(), &pr));
                }
                if let Some(lb) = it.label() {
                    let (x, y, _, _) = page_view(i);
                    labels.push(LabelView {
                        x: (x + lb.at.x * z) as f32,
                        y: (y + (lb.at.y - lb.size * 0.95) * z) as f32,
                        text: lb.text.into(),
                        size: (lb.size * z) as f32,
                        color: color(it.color()),
                    });
                }
                if d.sel.contains(&(i, k)) {
                    let (x, y, _, _) = page_view(i);
                    let m = it.margin() + 1.5 / z;
                    let (iw, ih) = it.size();
                    let corners = [p(-m, -m), p(iw + m, -m), p(iw + m, ih + m), p(-m, ih + m)];
                    let pts: Vec<P> = corners.iter().map(|q| it.map(*q)).collect();
                    let x0 = pts.iter().map(|q| q.x).fold(f64::MAX, f64::min);
                    let y0 = pts.iter().map(|q| q.y).fold(f64::MAX, f64::min);
                    let x1 = pts.iter().map(|q| q.x).fold(f64::MIN, f64::max);
                    let y1 = pts.iter().map(|q| q.y).fold(f64::MIN, f64::max);
                    sels.push(SelView {
                        x: (x + x0 * z) as f32,
                        y: (y + y0 * z) as f32,
                        w: ((x1 - x0) * z) as f32,
                        h: ((y1 - y0) * z) as f32,
                    });
                    if d.sel.len() == 1 {
                        for (_, hp) in it.handles() {
                            let q = it.map(hp);
                            handles.push(HandleView { x: (x + q.x * z) as f32, y: (y + q.y * z) as f32 });
                        }
                    }
                }
            }
        }
        // временная фигура при рисовании
        let mut band = None;
        match &self.drag {
            Some(Drag::Ink { page, pts }) => {
                let hl = self.tool == "highlighter";
                let s = &self.settings;
                let tmp = if hl {
                    items::new_ink(pts, &s.str("hl_color", "#ffd400"), s.f64("hl_width", 12.0), 0.4, true)
                } else {
                    items::new_ink(pts, &s.str("ink_color", "#ff0000"), s.f64("ink_width", 1.5), 1.0, false)
                };
                for pr in tmp.page_prims() {
                    prims.push(mk(*page, tmp.color(), tmp.opacity(), tmp.stroke_width(), &pr));
                }
            }
            Some(Drag::Shape { page, start, cur, .. }) | Some(Drag::Band { page, start, cur }) => {
                let (x, y, _, _) = page_view(*page);
                band = Some((
                    x + start.x.min(cur.x) * z,
                    y + start.y.min(cur.y) * z,
                    (cur.x - start.x).abs() * z,
                    (cur.y - start.y).abs() * z,
                ));
            }
            _ => {}
        }
        w.set_texts(ModelRc::new(VecModel::from(texts)));
        w.set_formulas(ModelRc::new(VecModel::from(fviews)));
        w.set_images(ModelRc::new(VecModel::from(images)));
        self.position_editor();
        w.set_prims(ModelRc::new(VecModel::from(prims)));
        w.set_labels(ModelRc::new(VecModel::from(labels)));
        w.set_sels(ModelRc::new(VecModel::from(sels)));
        w.set_handles(ModelRc::new(VecModel::from(handles)));
        match band {
            Some((x, y, bw, bh)) => {
                w.set_band_x(x as f32);
                w.set_band_y(y as f32);
                w.set_band_w(bw as f32);
                w.set_band_h(bh as f32);
                w.set_has_band(true);
            }
            None => w.set_has_band(false),
        }
        let _ = w.get_prims().row_count();
    }

    // ------------------------------------------------------------------ сохранение
    pub(crate) fn save_doc(&mut self, idx: usize, path: Option<PathBuf>) -> bool {
        if self.editing.is_some() {
            self.finish_edit();
        }
        let Some(d) = self.docs.get(idx) else { return false };
        let path = match path.or_else(|| d.path.clone()) {
            Some(p) => p,
            None => return self.save_as_doc(idx),
        };
        // ASCII: строки PDF без явной кодировки читаются как PDFDocEncoding
        let creator = format!("RedColor {APP_VERSION} - Maksim Belonoskin, Zelenograd, Moscow, Russia");
        let out = match crate::pdfio::build_output(&d.src, &d.items, &creator, &self.fonts, &self.text_cache) {
            Ok(b) => b,
            Err(err) => {
                eprintln!("save failed: {err}");
                let r = rfd::MessageDialog::new()
                    .set_title("RedColor")
                    .set_level(rfd::MessageLevel::Warning)
                    .set_description(format!(
                        "Не удалось сохранить файл. Работа в программе не потеряна.\n\n{err}\n\nСохранить под другим именем?"
                    ))
                    .set_buttons(rfd::MessageButtons::YesNo)
                    .show();
                return r == rfd::MessageDialogResult::Yes && self.save_as_doc(idx);
            }
        };
        loop {
            match crate::pdfio::replace_file(&out, &path) {
                Ok(()) => break,
                Err(err) => {
                    let name = path.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
                    let text = if err == "locked" {
                        format!(
                            "Файл «{name}» сейчас открыт в другой программе (например, в Adobe Acrobat), поэтому Windows не даёт его перезаписать.\n\nЗакройте файл в той программе и нажмите «Повторить» — или «Отмена», чтобы сохранить под другим именем. Изменения не потеряются."
                        )
                    } else {
                        format!("Не удалось записать «{name}»: {err}\n\n«Повторить» — ещё раз, «Отмена» — сохранить под другим именем.")
                    };
                    let r = rfd::MessageDialog::new()
                        .set_title("RedColor")
                        .set_level(rfd::MessageLevel::Warning)
                        .set_description(text)
                        .set_buttons(rfd::MessageButtons::OkCancelCustom("Повторить".into(), "Отмена".into()))
                        .show();
                    if r == rfd::MessageDialogResult::Custom("Повторить".into()) || r == rfd::MessageDialogResult::Ok {
                        continue;
                    }
                    return self.save_as_doc(idx);
                }
            }
        }
        let d = &mut self.docs[idx];
        d.modified = false;
        d.path = Some(path.clone());
        d.title = path.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
        self.settings.add_recent(&path.to_string_lossy());
        self.refresh_tabs();
        self.refresh_recent();
        let t = format!("Сохранено: {}", self.docs[idx].title);
        self.toast(&t);
        true
    }

    pub(crate) fn save_as_doc(&mut self, idx: usize) -> bool {
        let Some(d) = self.docs.get(idx) else { return false };
        let mut dlg = rfd::FileDialog::new().set_title("Сохранить как").add_filter("PDF", &["pdf"]).set_file_name(&d.title);
        if let Some(dir) = d.path.as_ref().and_then(|p| p.parent()) {
            dlg = dlg.set_directory(dir);
        } else {
            let last = self.settings.str("last_dir", "");
            if !last.is_empty() {
                dlg = dlg.set_directory(last);
            }
        }
        let Some(mut p) = dlg.save_file() else { return false };
        if !p.extension().map(|e| e.eq_ignore_ascii_case("pdf")).unwrap_or(false) {
            p.set_extension("pdf");
        }
        if let Some(dir) = p.parent() {
            self.settings.set("last_dir", serde_json::json!(dir.to_string_lossy()));
        }
        self.save_doc(idx, Some(p))
    }

    /// Перед закрытием документа: «Сохранить изменения?». false — закрытие отменено.
    pub(crate) fn ask_save(&mut self, idx: usize) -> bool {
        let Some(d) = self.docs.get(idx) else { return true };
        if !d.modified {
            return true;
        }
        let r = rfd::MessageDialog::new()
            .set_title("RedColor")
            .set_description(format!("Сохранить изменения в «{}»?", d.title))
            .set_buttons(rfd::MessageButtons::YesNoCancelCustom(
                "Сохранить".into(),
                "Не сохранять".into(),
                "Отмена".into(),
            ))
            .show();
        match r {
            rfd::MessageDialogResult::Custom(s) if s == "Сохранить" => self.save_doc(idx, None),
            rfd::MessageDialogResult::Yes => self.save_doc(idx, None),
            rfd::MessageDialogResult::Custom(s) if s == "Не сохранять" => true,
            rfd::MessageDialogResult::No => true,
            _ => false,
        }
    }
}

pub(crate) fn connect(win: &crate::AppWindow) {
    win.on_canvas_pointer(|kind, x, y, shift| {
        with_app(|a| a.canvas_pointer(kind.as_str(), x as f64, y as f64, shift));
    });
    win.on_edit_changed(|s| {
        with_app(|a| {
            let Some(c) = a.cur else { return };
            let Some(e) = a.editing.as_mut() else { return };
            if let Some(t) = a.docs[c].items.get_mut(e.page).and_then(|v| v.get_mut(e.idx)).and_then(|i| i.as_text_mut()) {
                t.sync_plain_edit_at(s.as_str(), e.pending_range.take());
            }
        });
    });
    win.on_edit_prekey(|anchor, focus, key| {
        with_app(|a| {
            use slint::platform::Key;
            let Some(e) = a.editing.as_mut() else { return };
            let text = a.win.upgrade().map(|w| w.get_edit_text().to_string()).unwrap_or_default();
            let mut start = anchor.max(0).min(focus.max(0)) as usize;
            let mut end = anchor.max(0).max(focus.max(0)) as usize;
            let back: slint::SharedString = Key::Backspace.into();
            let del: slint::SharedString = Key::Delete.into();
            if start == end && text.is_char_boundary(start) {
                if key == back && start > 0 {
                    start = text[..start].char_indices().last().map(|(i, _)| i).unwrap_or(0);
                } else if key == del && end < text.len() {
                    end += text[end..].chars().next().map(char::len_utf8).unwrap_or(0);
                }
            }
            e.pending_range = Some((start, end));
        });
    });
    win.on_edit_paste(|anchor, focus| {
        with_app(|a| a.paste_in_editor(anchor.max(0) as usize, focus.max(0) as usize));
    });
}
