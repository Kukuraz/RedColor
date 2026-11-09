// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Объекты на странице: фигуры, знаки, рисунки от руки.
//! Координаты: 1 единица = 1 pt страницы в отображаемой ориентации, начало — левый верхний угол.
//! Формат JSON совпадает с версией на Python (поле "kind", те же имена полей).

use serde::{Deserialize, Serialize};

pub const SYMBOLS: [&str; 5] = ["check", "cross", "plus", "minus", "dot"];

fn one() -> f64 {
    1.0
}
fn twelve() -> f64 {
    12.0
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Shape {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
    #[serde(default)]
    pub rot: f64,
    pub shape: String,
    pub color: String,
    pub width: f64,
    #[serde(default)]
    pub direction: i32,
    #[serde(default)]
    pub number: Option<i64>,
    #[serde(default = "twelve")]
    pub num_size: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Ink {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
    #[serde(default)]
    pub rot: f64,
    pub color: String,
    pub width: f64,
    #[serde(default = "one")]
    pub opacity: f64,
    #[serde(default)]
    pub highlight: bool,
    pub pts: Vec<[f64; 2]>,
    pub base: [f64; 2],
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum Item {
    #[serde(rename = "shape")]
    Shape(Shape),
    #[serde(rename = "ink")]
    Ink(Ink),
    #[serde(rename = "text")]
    Text(crate::text::Text),
    #[serde(rename = "image")]
    Image(ImageObj),
}

fn no_tint<'de, D: serde::Deserializer<'de>>(d: D) -> Result<Option<String>, D::Error> {
    let v = serde_json::Value::deserialize(d)?;
    Ok(v.as_str().filter(|s| !s.is_empty()).map(String::from))
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ImageObj {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
    #[serde(default)]
    pub rot: f64,
    #[serde(default, deserialize_with = "no_tint")]
    pub tint: Option<String>,
    #[serde(default)]
    pub signature: bool,
    /// PNG/JPEG в base64 (как export_state в версии на Python)
    #[serde(default)]
    pub data: std::rc::Rc<str>,
}

#[cfg(test)]
mod image_state_tests {
    use super::*;

    #[test]
    fn image_data_is_shared_and_keeps_the_json_format() {
        let json = r#"{"kind":"image","x":1,"y":2,"w":3,"h":4,"data":"YWJj"}"#;
        let item: Item = serde_json::from_str(json).unwrap();
        let cloned = item.clone();
        let (Item::Image(a), Item::Image(b)) = (&item, &cloned) else { panic!("expected image") };
        assert!(std::rc::Rc::ptr_eq(&a.data, &b.data));
        assert_eq!(serde_json::to_value(&item).unwrap()["data"], "YWJj");
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct P {
    pub x: f64,
    pub y: f64,
}

pub fn p(x: f64, y: f64) -> P {
    P { x, y }
}

#[derive(Clone, Debug)]
pub enum Seg {
    M(P),
    L(P),
    C(P, P, P),
    Z,
}

#[derive(Clone, Debug)]
pub struct Prim {
    pub segs: Vec<Seg>,
    pub fill: bool,
    pub square_cap: bool,
}

/// Подпись-номер у овала: позиция базовой линии (в координатах страницы), текст, кегль.
pub struct Label {
    pub at: P,
    pub text: String,
    pub size: f64,
}

fn ellipse_segs(x: f64, y: f64, w: f64, h: f64) -> Vec<Seg> {
    let k = 0.552_284_75;
    let (rx, ry) = (w / 2.0, h / 2.0);
    let (cx, cy) = (x + rx, y + ry);
    vec![
        Seg::M(p(cx + rx, cy)),
        Seg::C(p(cx + rx, cy + k * ry), p(cx + k * rx, cy + ry), p(cx, cy + ry)),
        Seg::C(p(cx - k * rx, cy + ry), p(cx - rx, cy + k * ry), p(cx - rx, cy)),
        Seg::C(p(cx - rx, cy - k * ry), p(cx - k * rx, cy - ry), p(cx, cy - ry)),
        Seg::C(p(cx + k * rx, cy - ry), p(cx + rx, cy - k * ry), p(cx + rx, cy)),
        Seg::Z,
    ]
}

fn poly(pts: &[P]) -> Vec<Seg> {
    let mut v = Vec::with_capacity(pts.len());
    for (i, q) in pts.iter().enumerate() {
        v.push(if i == 0 { Seg::M(*q) } else { Seg::L(*q) });
    }
    v
}

impl Item {
    pub fn pos(&self) -> (f64, f64) {
        match self {
            Item::Shape(s) => (s.x, s.y),
            Item::Ink(s) => (s.x, s.y),
            Item::Text(s) => (s.x, s.y),
            Item::Image(s) => (s.x, s.y),
        }
    }
    pub fn size(&self) -> (f64, f64) {
        match self {
            Item::Shape(s) => (s.w, s.h),
            Item::Ink(s) => (s.w, s.h),
            Item::Text(s) => (s.w, s.h),
            Item::Image(s) => (s.w, s.h),
        }
    }
    pub fn rot(&self) -> f64 {
        match self {
            Item::Shape(s) => s.rot,
            Item::Ink(s) => s.rot,
            Item::Text(s) => s.rot,
            Item::Image(s) => s.rot,
        }
    }
    pub fn set_pos(&mut self, x: f64, y: f64) {
        match self {
            Item::Shape(s) => {
                s.x = x;
                s.y = y;
            }
            Item::Ink(s) => {
                s.x = x;
                s.y = y;
            }
            Item::Text(s) => {
                s.x = x;
                s.y = y;
            }
            Item::Image(s) => {
                s.x = x;
                s.y = y;
            }
        }
    }
    pub fn set_size(&mut self, w: f64, h: f64) {
        let (w, h) = (w.max(1.0), h.max(1.0));
        match self {
            Item::Shape(s) => {
                s.w = w;
                s.h = h;
            }
            Item::Ink(s) => {
                s.w = w;
                s.h = h;
            }
            Item::Text(s) => {
                s.w = w.max(12.0);
            }
            Item::Image(s) => {
                s.w = w;
                s.h = h;
            }
        }
    }
    pub fn translate(&mut self, dx: f64, dy: f64) {
        let (x, y) = self.pos();
        self.set_pos(x + dx, y + dy);
    }
    pub fn color(&self) -> &str {
        match self {
            Item::Shape(s) => &s.color,
            Item::Ink(s) => &s.color,
            Item::Text(s) => &s.color,
            Item::Image(s) => s.tint.as_deref().unwrap_or("#000000"),
        }
    }
    pub fn set_color(&mut self, c: &str) {
        match self {
            Item::Shape(s) => s.color = c.to_string(),
            Item::Ink(s) => s.color = c.to_string(),
            Item::Text(s) => s.color = c.to_string(),
            Item::Image(s) => {
                if s.signature {
                    s.tint = Some(c.to_string());
                }
            }
        }
    }
    pub fn stroke_width(&self) -> f64 {
        match self {
            Item::Shape(s) => s.width,
            Item::Ink(s) => s.width,
            _ => 0.0,
        }
    }
    pub fn set_stroke_width(&mut self, w: f64) {
        match self {
            Item::Shape(s) => s.width = w,
            Item::Ink(s) => s.width = w,
            _ => {}
        }
    }
    pub fn is_ink(&self) -> bool {
        matches!(self, Item::Ink(_))
    }
    pub fn is_text(&self) -> bool {
        matches!(self, Item::Text(_))
    }
    pub fn as_text(&self) -> Option<&crate::text::Text> {
        match self {
            Item::Text(t) => Some(t),
            _ => None,
        }
    }
    pub fn as_text_mut(&mut self) -> Option<&mut crate::text::Text> {
        match self {
            Item::Text(t) => Some(t),
            _ => None,
        }
    }
    pub fn opacity(&self) -> f64 {
        match self {
            Item::Ink(s) => s.opacity,
            _ => 1.0,
        }
    }
    pub fn keep_aspect(&self) -> bool {
        match self {
            Item::Shape(s) => SYMBOLS.contains(&s.shape.as_str()),
            Item::Image(_) => true,
            _ => false,
        }
    }
    pub fn min_size(&self) -> f64 {
        match self {
            Item::Shape(_) => 2.0,
            Item::Ink(_) => 1.0,
            Item::Text(_) => 12.0,
            Item::Image(_) => 4.0,
        }
    }
    /// Поле вокруг рамки (толщина линии, наконечник стрелки).
    pub fn margin(&self) -> f64 {
        match self {
            Item::Shape(s) => s.width / 2.0 + 1.0 + if s.shape == "arrow" { s.width * 4.0 } else { 0.0 },
            Item::Ink(s) => s.width / 2.0 + 1.0,
            _ => 0.0,
        }
    }

    /// Локальная точка → координаты страницы (поворот вокруг начала объекта, как в Qt).
    pub fn map(&self, q: P) -> P {
        let (x, y) = self.pos();
        let a = self.rot().to_radians();
        let (s, c) = a.sin_cos();
        p(x + q.x * c - q.y * s, y + q.x * s + q.y * c)
    }

    /// Координаты страницы → локальные.
    pub fn unmap(&self, q: P) -> P {
        let (x, y) = self.pos();
        let a = self.rot().to_radians();
        let (s, c) = a.sin_cos();
        let (dx, dy) = (q.x - x, q.y - y);
        p(dx * c + dy * s, -dx * s + dy * c)
    }

    fn ink_local_pts(ink: &Ink) -> Vec<P> {
        let sx = ink.w / ink.base[0].max(1e-6);
        let sy = ink.h / ink.base[1].max(1e-6);
        ink.pts.iter().map(|q| p(q[0] * sx, q[1] * sy)).collect()
    }

    /// Примитивы в локальных координатах.
    pub fn local_prims(&self) -> Vec<Prim> {
        match self {
            Item::Ink(ink) => {
                let pts = Self::ink_local_pts(ink);
                let mut segs = Vec::new();
                if let Some(first) = pts.first() {
                    segs.push(Seg::M(*first));
                    if pts.len() == 1 {
                        segs.push(Seg::L(p(first.x + 0.01, first.y + 0.01)));
                    }
                    // гладкая линия: квадратичные кривые через середины (как в версии на Python)
                    let mut cur = *first;
                    for i in 1..pts.len().saturating_sub(1) {
                        let ctrl = pts[i];
                        let mid = p((pts[i].x + pts[i + 1].x) / 2.0, (pts[i].y + pts[i + 1].y) / 2.0);
                        let c1 = p(cur.x + 2.0 / 3.0 * (ctrl.x - cur.x), cur.y + 2.0 / 3.0 * (ctrl.y - cur.y));
                        let c2 = p(mid.x + 2.0 / 3.0 * (ctrl.x - mid.x), mid.y + 2.0 / 3.0 * (ctrl.y - mid.y));
                        segs.push(Seg::C(c1, c2, mid));
                        cur = mid;
                    }
                    if pts.len() > 1 {
                        segs.push(Seg::L(*pts.last().unwrap()));
                    }
                }
                vec![Prim { segs, fill: false, square_cap: ink.highlight }]
            }
            Item::Text(_) | Item::Image(_) => vec![],
            Item::Shape(s) => {
                let (w, h) = (s.w, s.h);
                let stroke = |segs: Vec<Seg>| Prim { segs, fill: false, square_cap: false };
                match s.shape.as_str() {
                    "ellipse" => vec![stroke(ellipse_segs(0.0, 0.0, w, h))],
                    "rect" => vec![stroke(vec![
                        Seg::M(p(0.0, 0.0)),
                        Seg::L(p(w, 0.0)),
                        Seg::L(p(w, h)),
                        Seg::L(p(0.0, h)),
                        Seg::Z,
                    ])],
                    "line" | "arrow" => {
                        let (a, b) = [
                            (p(0.0, 0.0), p(w, h)),
                            (p(0.0, h), p(w, 0.0)),
                            (p(w, h), p(0.0, 0.0)),
                            (p(w, 0.0), p(0.0, h)),
                        ][s.direction.rem_euclid(4) as usize];
                        let mut out = vec![stroke(poly(&[a, b]))];
                        if s.shape == "arrow" {
                            let ang = (b.y - a.y).atan2(b.x - a.x);
                            let l = (s.width * 4.5).max(6.0);
                            let p1 = p(b.x - l * (ang - 0.45).cos(), b.y - l * (ang - 0.45).sin());
                            let p2 = p(b.x - l * (ang + 0.45).cos(), b.y - l * (ang + 0.45).sin());
                            out.push(stroke(poly(&[p1, b, p2])));
                        }
                        out
                    }
                    "check" => vec![stroke(poly(&[p(0.05 * w, 0.55 * h), p(0.38 * w, 0.9 * h), p(0.95 * w, 0.08 * h)]))],
                    "cross" => vec![
                        stroke(poly(&[p(0.1 * w, 0.1 * h), p(0.9 * w, 0.9 * h)])),
                        stroke(poly(&[p(0.9 * w, 0.1 * h), p(0.1 * w, 0.9 * h)])),
                    ],
                    "plus" => vec![
                        stroke(poly(&[p(0.5 * w, 0.05 * h), p(0.5 * w, 0.95 * h)])),
                        stroke(poly(&[p(0.05 * w, 0.5 * h), p(0.95 * w, 0.5 * h)])),
                    ],
                    "minus" => vec![stroke(poly(&[p(0.05 * w, 0.5 * h), p(0.95 * w, 0.5 * h)]))],
                    "vline" => vec![stroke(poly(&[p(0.5 * w, 0.0), p(0.5 * w, h)]))],
                    "dot" => vec![Prim { segs: ellipse_segs(0.2 * w, 0.2 * h, 0.6 * w, 0.6 * h), fill: true, square_cap: false }],
                    _ => vec![],
                }
            }
        }
    }

    /// Примитивы в координатах страницы.
    pub fn page_prims(&self) -> Vec<Prim> {
        self.local_prims()
            .into_iter()
            .map(|pr| Prim {
                segs: pr
                    .segs
                    .into_iter()
                    .map(|s| match s {
                        Seg::M(a) => Seg::M(self.map(a)),
                        Seg::L(a) => Seg::L(self.map(a)),
                        Seg::C(a, b, c) => Seg::C(self.map(a), self.map(b), self.map(c)),
                        Seg::Z => Seg::Z,
                    })
                    .collect(),
                ..pr
            })
            .collect()
    }

    pub fn label(&self) -> Option<Label> {
        match self {
            Item::Shape(s) => s.number.map(|n| Label { at: self.map(p(s.w + 1.0, 0.0)), text: n.to_string(), size: s.num_size }),
            _ => None,
        }
    }

    /// Попадание точки страницы в объект (tol — допуск в pt).
    pub fn hit(&self, q: P, tol: f64, selected: bool) -> bool {
        let l = self.unmap(q);
        let (w, h) = self.size();
        let m = self.margin().max(tol);
        let in_box = l.x >= -m && l.y >= -m && l.x <= w + m && l.y <= h + m;
        if !in_box {
            // номер овала
            if let Some(lb) = self.label() {
                let (lx, ly) = (lb.at.x, lb.at.y);
                return q.x >= lx - 2.0 && q.x <= lx + lb.size * 2.2 && q.y >= ly - lb.size * 1.1 && q.y <= ly + lb.size * 0.3;
            }
            return false;
        }
        if selected {
            return true;
        }
        let filled_box = match self {
            Item::Shape(s) => SYMBOLS.contains(&s.shape.as_str()),
            Item::Ink(_) => false,
            Item::Text(_) | Item::Image(_) => true,
        };
        if filled_box {
            return true;
        }
        // по линии
        let tol = (self.stroke_width() / 2.0).max(tol);
        for pr in self.local_prims() {
            let pts = flatten(&pr.segs);
            for w2 in pts.windows(2) {
                if seg_dist(l, w2[0], w2[1]) <= tol {
                    return true;
                }
            }
        }
        false
    }

    pub fn handles(&self) -> Vec<(&'static str, P)> {
        let (w, h) = self.size();
        if self.is_text() {
            // углы — масштаб текста целиком, бока — ширина строки
            return vec![
                ("tl", p(0.0, 0.0)),
                ("tr", p(w, 0.0)),
                ("r", p(w, h / 2.0)),
                ("br", p(w, h)),
                ("bl", p(0.0, h)),
                ("l", p(0.0, h / 2.0)),
            ];
        }
        vec![
            ("tl", p(0.0, 0.0)),
            ("t", p(w / 2.0, 0.0)),
            ("tr", p(w, 0.0)),
            ("r", p(w, h / 2.0)),
            ("br", p(w, h)),
            ("b", p(w / 2.0, h)),
            ("bl", p(0.0, h)),
            ("l", p(0.0, h / 2.0)),
        ]
    }

    /// Изменение размера за ручку (перенос BoxItem.mouseMoveEvent из версии на Python).
    pub fn drag_handle(&mut self, start: &Item, handle: &str, q: P, shift: bool) {
        if let (Item::Text(t0), true) = (start, handle.len() == 2) {
            // угол текста: масштаб целиком (кегль и ширина), противоположный угол на месте
            let l = start.unmap(q);
            let (w0, h0) = (t0.w.max(1.0), t0.h.max(1.0));
            let nw = if handle.contains('l') { w0 - l.x } else { l.x };
            let nh = if handle.starts_with('t') { h0 - l.y } else { l.y };
            let k = (nw / w0).max(nh / h0).clamp(0.05, 40.0);
            let k = if t0.size * k < 2.0 { 2.0 / t0.size } else { k };
            let mut t = t0.clone();
            t.size = (t0.size * k * 10.0).round() / 10.0;
            t.w = w0 * k;
            t.h = h0 * k;
            let ax = if handle.contains('l') { w0 } else { 0.0 };
            let ay = if handle.starts_with('t') { h0 } else { 0.0 };
            let anchor = start.map(p(ax, ay));
            let a = t0.rot.to_radians();
            let (sn, cs) = a.sin_cos();
            let (ox, oy) = (ax * k, ay * k);
            t.x = anchor.x - (ox * cs - oy * sn);
            t.y = anchor.y - (ox * sn + oy * cs);
            *self = Item::Text(t);
            return;
        }
        let (x0p, y0p) = start.pos();
        let (w0, h0) = start.size();
        let a = start.rot().to_radians();
        let (sn, cs) = a.sin_cos();
        let (dx, dy) = (q.x - x0p, q.y - y0p);
        let lx = dx * cs + dy * sn;
        let ly = -dx * sn + dy * cs;
        let mn = self.min_size();
        let (mut x0, mut y0, mut x1, mut y1) = (0.0, 0.0, w0, h0);
        if handle.contains('l') {
            x0 = lx.min(x1 - mn);
        }
        if handle.contains('r') {
            x1 = lx.max(x0 + mn);
        }
        if handle.starts_with('t') {
            y0 = ly.min(y1 - mn);
        }
        if handle.starts_with('b') {
            y1 = ly.max(y0 + mn);
        }
        let keep = start.keep_aspect() != shift;
        if keep && handle.len() == 2 && w0 > 0.0 && h0 > 0.0 {
            let ratio = w0 / h0;
            let (mut nw, mut nh) = (x1 - x0, y1 - y0);
            if nw / ratio > nh {
                nh = nw / ratio;
            } else {
                nw = nh * ratio;
            }
            if handle.contains('l') {
                x0 = x1 - nw;
            } else {
                x1 = x0 + nw;
            }
            if handle.starts_with('t') {
                y0 = y1 - nh;
            } else {
                y1 = y0 + nh;
            }
        }
        let nx = x0p + x0 * cs - y0 * sn;
        let ny = y0p + x0 * sn + y0 * cs;
        *self = start.clone();
        self.set_pos(nx, ny);
        self.set_size(x1 - x0, y1 - y0);
    }
}

/// Кривые → ломаная (для попадания мышью).
pub fn flatten(segs: &[Seg]) -> Vec<P> {
    let mut out: Vec<P> = Vec::new();
    let mut start = p(0.0, 0.0);
    for s in segs {
        match s {
            Seg::M(a) => {
                start = *a;
                out.push(*a);
            }
            Seg::L(a) => out.push(*a),
            Seg::C(a, b, c) => {
                let p0 = *out.last().unwrap_or(&start);
                for i in 1..=8 {
                    let t = i as f64 / 8.0;
                    let u = 1.0 - t;
                    out.push(p(
                        u * u * u * p0.x + 3.0 * u * u * t * a.x + 3.0 * u * t * t * b.x + t * t * t * c.x,
                        u * u * u * p0.y + 3.0 * u * u * t * a.y + 3.0 * u * t * t * b.y + t * t * t * c.y,
                    ));
                }
            }
            Seg::Z => out.push(start),
        }
    }
    out
}

pub fn seg_dist(q: P, a: P, b: P) -> f64 {
    let (vx, vy) = (b.x - a.x, b.y - a.y);
    let len2 = vx * vx + vy * vy;
    let t = if len2 > 0.0 { (((q.x - a.x) * vx + (q.y - a.y) * vy) / len2).clamp(0.0, 1.0) } else { 0.0 };
    let (cx, cy) = (a.x + t * vx, a.y + t * vy);
    ((q.x - cx).powi(2) + (q.y - cy).powi(2)).sqrt()
}

/// SVG-команды пути (для Path в Slint, координаты страницы в pt).
pub fn svg(segs: &[Seg]) -> String {
    let mut s = String::new();
    for g in segs {
        match g {
            Seg::M(a) => s += &format!("M {:.2} {:.2} ", a.x, a.y),
            Seg::L(a) => s += &format!("L {:.2} {:.2} ", a.x, a.y),
            Seg::C(a, b, c) => s += &format!("C {:.2} {:.2} {:.2} {:.2} {:.2} {:.2} ", a.x, a.y, b.x, b.y, c.x, c.y),
            Seg::Z => s += "Z ",
        }
    }
    s
}

/// Операторы PDF (в системе координат «как на экране» — матрицу задаёт вызывающий).
pub fn pdf_path(segs: &[Seg]) -> String {
    let mut s = String::new();
    for g in segs {
        match g {
            Seg::M(a) => s += &format!("{:.3} {:.3} m\n", a.x, a.y),
            Seg::L(a) => s += &format!("{:.3} {:.3} l\n", a.x, a.y),
            Seg::C(a, b, c) => s += &format!("{:.3} {:.3} {:.3} {:.3} {:.3} {:.3} c\n", a.x, a.y, b.x, b.y, c.x, c.y),
            Seg::Z => s += "h\n",
        }
    }
    s
}

pub fn rgb(hex: &str) -> (f64, f64, f64) {
    let v = u32::from_str_radix(hex.trim().trim_start_matches('#'), 16).unwrap_or(0xff0000);
    (((v >> 16) & 255) as f64 / 255.0, ((v >> 8) & 255) as f64 / 255.0, (v & 255) as f64 / 255.0)
}

/// Новый рисунок от руки из точек страницы.
pub fn new_ink(pts: &[(f64, f64)], color: &str, width: f64, opacity: f64, highlight: bool) -> Item {
    let mut pts = pts.to_vec();
    if pts.len() == 1 {
        pts.push((pts[0].0 + 0.3, pts[0].1 + 0.3));
    }
    let x0 = pts.iter().map(|q| q.0).fold(f64::MAX, f64::min);
    let y0 = pts.iter().map(|q| q.1).fold(f64::MAX, f64::min);
    let x1 = pts.iter().map(|q| q.0).fold(f64::MIN, f64::max);
    let y1 = pts.iter().map(|q| q.1).fold(f64::MIN, f64::max);
    let (w, h) = ((x1 - x0).max(1.0), (y1 - y0).max(1.0));
    Item::Ink(Ink {
        x: x0,
        y: y0,
        w,
        h,
        rot: 0.0,
        color: color.to_string(),
        width,
        opacity,
        highlight,
        pts: pts.iter().map(|q| [q.0 - x0, q.1 - y0]).collect(),
        base: [w, h],
    })
}

/// Содержимое PDF для объектов одной страницы (в координатах «как на экране»).
pub fn pdf_ops(items: &[Item]) -> String {
    let mut s = String::new();
    for it in items {
        let (r, g, b) = rgb(it.color());
        s += "q\n";
        if it.opacity() < 0.999 {
            s += "/RCa0 gs\n";
        }
        for pr in it.page_prims() {
            if pr.fill {
                s += &format!("{r:.4} {g:.4} {b:.4} rg\n");
                s += &pdf_path(&pr.segs);
                s += "f\n";
            } else {
                s += &format!(
                    "{r:.4} {g:.4} {b:.4} RG {:.3} w {} J 1 j\n",
                    it.stroke_width(),
                    if pr.square_cap { 2 } else { 1 }
                );
                s += &pdf_path(&pr.segs);
                s += "S\n";
            }
        }
        if let Some(lb) = it.label() {
            // ось y направлена вниз, поэтому текст переворачиваем матрицей
            s += &format!(
                "BT {r:.4} {g:.4} {b:.4} rg /RCHB {:.2} Tf 1 0 0 -1 {:.3} {:.3} Tm ({}) Tj ET\n",
                lb.size, lb.at.x, lb.at.y, lb.text
            );
        }
        s += "Q\n";
    }
    s
}
