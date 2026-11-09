// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Текст с формулами: модель (формат версии на Python), шрифты, разметка строк.

use std::cell::RefCell;
use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::rc::Rc;

use serde::de::Error as _;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::{Value, json};

use crate::panel::FontFamilies;

pub const OBJ: char = '\u{FFFC}';

#[derive(Clone, Debug, PartialEq)]
pub enum Run {
    T(String),
    /// формула: ключ и «выключная» (на отдельной строке) или в строке
    F(String, bool),
}

#[derive(Clone, Debug, PartialEq, Default)]
pub struct Block {
    pub align: Option<String>,
    pub runs: Vec<Run>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Formula {
    pub svg: Rc<str>,
    pub w: f64,
    pub h: f64,
    #[serde(rename = "src")]
    pub src_size: f64,
    #[serde(default)]
    pub latex: String,
    #[serde(default)]
    pub alt: String,
}

impl Formula {
    /// SVG формулы в нужном цвете (чёрные заливки и линии перекрашиваются).
    pub fn colored_svg(&self, color: &str) -> String {
        let mut s = self.svg.to_string();
        for black in ["#000000", "#000", "black"] {
            for q in ['\'', '"'] {
                s = s.replace(&format!("fill={q}{black}{q}"), &format!("fill='{color}'"));
                s = s.replace(&format!("stroke={q}{black}{q}"), &format!("stroke='{color}'"));
            }
        }
        if let Some(i) = s.find("<svg") {
            s.insert_str(i + 4, &format!(" fill='{color}' color='{color}'"));
        }
        s
    }
}

fn ser_blocks<S: Serializer>(blocks: &[Block], s: S) -> Result<S::Ok, S::Error> {
    let v: Vec<Value> = blocks
        .iter()
        .map(|b| {
            let runs: Vec<Value> = b
                .runs
                .iter()
                .map(|r| match r {
                    Run::T(t) => json!(["t", t]),
                    Run::F(k, d) => json!(["f", k, d]),
                })
                .collect();
            json!([b.align, runs])
        })
        .collect();
    v.serialize(s)
}

fn de_blocks<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<Block>, D::Error> {
    let v = Value::deserialize(d)?;
    let arr = v.as_array().ok_or_else(|| D::Error::custom("runs"))?;
    let mut out = Vec::new();
    for b in arr {
        let block = b.as_array().filter(|b| b.len() == 2).ok_or_else(|| D::Error::custom("invalid text block"))?;
        let al = match &block[0] {
            Value::Null => None,
            Value::String(s) => Some(s.clone()),
            _ => return Err(D::Error::custom("invalid text alignment")),
        };
        let mut runs = Vec::new();
        for r in block[1].as_array().ok_or_else(|| D::Error::custom("invalid text runs"))? {
            match r.get(0).and_then(|x| x.as_str()) {
                Some("t") => runs.push(Run::T(r.get(1).and_then(|x| x.as_str()).ok_or_else(|| D::Error::custom("invalid text run"))?.to_string())),
                Some("f") => runs.push(Run::F(
                    r.get(1).and_then(|x| x.as_str()).ok_or_else(|| D::Error::custom("invalid formula run"))?.to_string(),
                    r.get(2).and_then(|x| x.as_bool()).unwrap_or(false),
                )),
                _ => return Err(D::Error::custom("unsupported text run")),
            }
        }
        out.push(Block { align: al, runs });
    }
    Ok(out)
}

#[cfg(test)]
mod compatibility_tests {
    use super::*;

    #[test]
    fn unknown_text_run_is_rejected_instead_of_losing_content() {
        let input = r#"{"kind":"text","x":0,"y":0,"w":100,"runs":[[null,[["unknown","data"]]]]}"#;
        assert!(serde_json::from_str::<crate::items::Item>(input).is_err());
    }

    #[test]
    fn formula_svg_is_shared_across_history_snapshots() {
        let formula: Formula = serde_json::from_str(r#"{"svg":"<svg/>","w":1,"h":2,"src":12}"#).unwrap();
        let copy = formula.clone();
        assert!(Rc::ptr_eq(&formula.svg, &copy.svg));
        assert_eq!(serde_json::to_value(copy).unwrap()["svg"], "<svg/>");
    }

    fn sample_text() -> Text {
        let input = r#"{"kind":"text","x":0,"y":0,"w":100,"runs":[[null,[["t","А"],["f","one",false],["t","B"],["f","two",false]]]],"formulas":{"one":{"svg":"<svg/>","w":1,"h":2,"src":12},"two":{"svg":"<svg/>","w":2,"h":2,"src":12}}}"#;
        let crate::items::Item::Text(t) = serde_json::from_str(input).unwrap() else { panic!() };
        t
    }

    #[test]
    fn removing_first_formula_keeps_the_second() {
        let mut text = sample_text();
        let mut empty = sample_text();
        empty.blocks = vec![Block::default()];
        empty.formulas.clear();
        text.replace_range("А".len(), "А\u{fffc}".len(), &empty).unwrap();
        assert_eq!(text.plain(), "АB\u{fffc}");
        assert!(!text.formulas.contains_key("one"));
        assert!(text.formulas.contains_key("two"));
    }

    #[test]
    fn ordinary_edit_preserves_formula_identity() {
        let mut text = sample_text();
        text.sync_plain_edit("А\u{fffc}текстB\u{fffc}");
        assert_eq!(text.blocks[0].runs.iter().filter_map(|r| if let Run::F(k, _) = r {Some(k.as_str())} else {None}).collect::<Vec<_>>(), vec!["one", "two"]);
    }
}

fn default_font() -> String {
    "Minion Pro".into()
}
fn default_size() -> f64 {
    12.0
}
fn default_color() -> String {
    "#ff0000".into()
}
fn default_align() -> String {
    "left".into()
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Text {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    #[serde(default)]
    pub h: f64,
    #[serde(default)]
    pub rot: f64,
    #[serde(default = "default_font")]
    pub font: String,
    #[serde(default = "default_size")]
    pub size: f64,
    #[serde(default = "default_color")]
    pub color: String,
    #[serde(default, deserialize_with = "de_bool")]
    pub bold: bool,
    #[serde(default, deserialize_with = "de_bool")]
    pub italic: bool,
    #[serde(default = "default_align")]
    pub align: String,
    #[serde(rename = "runs", serialize_with = "ser_blocks", deserialize_with = "de_blocks", default)]
    pub blocks: Vec<Block>,
    #[serde(default)]
    pub formulas: BTreeMap<String, Formula>,
}

fn de_bool<'de, D: Deserializer<'de>>(d: D) -> Result<bool, D::Error> {
    Ok(Value::deserialize(d)?.as_bool().unwrap_or(false))
}

impl Text {
    pub fn plain(&self) -> String {
        self.blocks
            .iter()
            .map(|b| {
                b.runs
                    .iter()
                    .map(|r| match r {
                        Run::T(t) => t.clone(),
                        Run::F(..) => OBJ.to_string(),
                    })
                    .collect::<String>()
            })
            .collect::<Vec<_>>()
            .join("\n")
    }

    /// Текст после правки → блоки; символы OBJ снова становятся формулами (по порядку).
    pub fn set_plain(&mut self, text: &str) {
        let mut formulas: Vec<Run> =
            self.blocks.iter().flat_map(|b| b.runs.iter().filter(|r| matches!(r, Run::F(..))).cloned()).collect();
        formulas.reverse();
        let old_align: Vec<Option<String>> = self.blocks.iter().map(|b| b.align.clone()).collect();
        let mut blocks = Vec::new();
        for (i, line) in text.replace("\r\n", "\n").replace('\r', "\n").split('\n').enumerate() {
            let mut runs: Vec<Run> = Vec::new();
            let mut cur = String::new();
            for ch in line.chars() {
                if ch == OBJ {
                    if let Some(f) = formulas.pop() {
                        if !cur.is_empty() {
                            runs.push(Run::T(std::mem::take(&mut cur)));
                        }
                        runs.push(f);
                    }
                } else {
                    cur.push(ch);
                }
            }
            if !cur.is_empty() {
                runs.push(Run::T(cur));
            }
            blocks.push(Block { align: old_align.get(i).cloned().flatten(), runs });
        }
        // удалённые формулы — из словаря тоже
        let keys: std::collections::HashSet<String> = blocks
            .iter()
            .flat_map(|b: &Block| b.runs.iter())
            .filter_map(|r| if let Run::F(k, _) = r { Some(k.clone()) } else { None })
            .collect();
        self.formulas.retain(|k, _| keys.contains(k));
        self.blocks = blocks;
    }

    pub fn is_empty(&self) -> bool {
        self.blocks.iter().all(|b| {
            b.runs.iter().all(|r| match r {
                Run::T(t) => t.trim().is_empty(),
                Run::F(..) => false,
            })
        })
    }

    /// Replace a UTF-8 range while keeping the identity of formula objects on either side.
    pub fn replace_range(&mut self, start: usize, end: usize, inserted: &Text) -> Result<(), &'static str> {
        #[derive(Clone)]
        enum Atom { Char(char), Formula(String, bool), Break(Option<String>) }
        fn flatten(blocks: &[Block]) -> Vec<Atom> {
            let mut atoms = Vec::new();
            for (i, block) in blocks.iter().enumerate() {
                if i > 0 { atoms.push(Atom::Break(block.align.clone())); }
                for run in &block.runs {
                    match run {
                        Run::T(s) => atoms.extend(s.chars().map(Atom::Char)),
                        Run::F(k, d) => atoms.push(Atom::Formula(k.clone(), *d)),
                    }
                }
            }
            atoms
        }
        fn len(a: &Atom) -> usize {
            match a { Atom::Char(c) => c.len_utf8(), Atom::Formula(..) => OBJ.len_utf8(), Atom::Break(..) => 1 }
        }
        fn boundary(atoms: &[Atom], byte: usize) -> Option<usize> {
            let mut pos = 0;
            for (i, a) in atoms.iter().enumerate() {
                if pos == byte { return Some(i); }
                pos += len(a);
            }
            (pos == byte).then_some(atoms.len())
        }
        let mut atoms = flatten(&self.blocks);
        let a = boundary(&atoms, start).ok_or("invalid text selection")?;
        let b = boundary(&atoms, end).ok_or("invalid text selection")?;
        if a > b { return Err("invalid text selection"); }
        atoms.splice(a..b, flatten(&inserted.blocks));
        self.formulas.extend(inserted.formulas.clone());
        let mut blocks = vec![Block { align: self.blocks.first().and_then(|b| b.align.clone()), runs: Vec::new() }];
        for atom in atoms {
            match atom {
                Atom::Break(align) => blocks.push(Block { align, runs: Vec::new() }),
                Atom::Formula(k, d) => blocks.last_mut().unwrap().runs.push(Run::F(k, d)),
                Atom::Char(ch) => {
                    let runs = &mut blocks.last_mut().unwrap().runs;
                    if let Some(Run::T(s)) = runs.last_mut() { s.push(ch); }
                    else { runs.push(Run::T(ch.to_string())); }
                }
            }
        }
        let keys: std::collections::HashSet<&str> = blocks.iter().flat_map(|b| b.runs.iter())
            .filter_map(|r| if let Run::F(k, _) = r { Some(k.as_str()) } else { None }).collect();
        self.formulas.retain(|k, _| keys.contains(k.as_str()));
        self.blocks = blocks;
        Ok(())
    }

    /// Apply an ordinary editor change without assigning a deleted formula to a different placeholder.
    pub fn sync_plain_edit(&mut self, new: &str) {
        self.sync_plain_edit_at(new, None);
    }

    pub fn sync_plain_edit_at(&mut self, new: &str, expected: Option<(usize, usize)>) {
        let old = self.plain();
        if old == new { return; }
        if let Some((start, end)) = expected {
            if start <= end && end <= old.len() && old.is_char_boundary(start) && old.is_char_boundary(end)
                && new.len() >= old.len() - (end - start) {
                let new_end = new.len() - (old.len() - end);
                if new_end >= start && new.is_char_boundary(start) && new.is_char_boundary(new_end)
                    && old[..start] == new[..start] && old[end..] == new[new_end..] {
                    let mut inserted = self.clone();
                    inserted.formulas.clear();
                    inserted.blocks = new[start..new_end].split('\n').map(|s| Block {
                        align: None, runs: if s.is_empty() { vec![] } else { vec![Run::T(s.to_string())] },
                    }).collect();
                    let _ = self.replace_range(start, end, &inserted);
                    return;
                }
            }
        }
        let mut prefix = 0;
        for (a, b) in old.chars().zip(new.chars()) {
            if a != b { break; }
            prefix += a.len_utf8();
        }
        let mut old_end = old.len();
        let mut new_end = new.len();
        for (a, b) in old[prefix..].chars().rev().zip(new[prefix..].chars().rev()) {
            if a != b { break; }
            old_end -= a.len_utf8();
            new_end -= b.len_utf8();
        }
        let mut inserted = self.clone();
        inserted.formulas.clear();
        inserted.blocks = new[prefix..new_end].split('\n').map(|s| Block {
            align: None, runs: if s.is_empty() { vec![] } else { vec![Run::T(s.to_string())] },
        }).collect();
        let _ = self.replace_range(prefix, old_end, &inserted);
    }
}

// ============================================================================ шрифты

pub struct LoadedFont {
    pub font: mupdf::Font,
    pub path: PathBuf,
    adv: RefCell<HashMap<char, (i32, f32)>>,
}

impl LoadedFont {
    /// (номер глифа, ширина при кегле 1)
    pub fn glyph(&self, ch: char) -> (i32, f32) {
        if let Some(v) = self.adv.borrow().get(&ch) {
            return *v;
        }
        let gid = self.font.encode_character(ch as i32).unwrap_or(0);
        let a = self.font.advance_glyph(gid).unwrap_or(0.5);
        self.adv.borrow_mut().insert(ch, (gid, a));
        (gid, a)
    }

    pub fn width(&self, s: &str, size: f64) -> f64 {
        s.chars().map(|c| self.glyph(c).1 as f64).sum::<f64>() * size
    }

    pub fn ascender(&self) -> f64 {
        self.font.ascender() as f64
    }

    pub fn descender(&self) -> f64 {
        self.font.descender() as f64
    }
}

#[derive(Default)]
pub struct FontCache {
    fonts: RefCell<HashMap<PathBuf, Rc<LoadedFont>>>,
}

pub fn resolve_family<'a>(fams: &'a FontFamilies, fam: &'a str) -> &'a str {
    if fams.contains_key(fam) {
        return fam;
    }
    for f in ["Minion Pro", "Times New Roman", "Arial"] {
        if fams.contains_key(f) {
            return f;
        }
    }
    fams.keys().next().map(|s| s.as_str()).unwrap_or("Arial")
}

/// Файл начертания: bi / b / i / r (как fonts.file_for в версии на Python).
pub fn file_for(fams: &FontFamilies, fam: &str, bold: bool, italic: bool) -> Option<PathBuf> {
    let v = fams.get(resolve_family(fams, fam))?;
    let key = if bold && italic { "bi" } else if bold { "b" } else if italic { "i" } else { "r" };
    v.get(key)
        .or(if bold { v.get("b") } else { None })
        .or(if italic { v.get("i") } else { None })
        .or(v.get("r"))
        .cloned()
}

impl FontCache {
    pub fn load(&self, path: &Path) -> Option<Rc<LoadedFont>> {
        if let Some(f) = self.fonts.borrow().get(path) {
            return Some(f.clone());
        }
        let data = std::fs::read(path).ok()?;
        let font = mupdf::Font::from_bytes(&path.file_stem()?.to_string_lossy(), &data).ok()?;
        let lf = Rc::new(LoadedFont { font, path: path.to_path_buf(), adv: RefCell::new(HashMap::new()) });
        self.fonts.borrow_mut().insert(path.to_path_buf(), lf.clone());
        Some(lf)
    }

    pub fn for_text(&self, fams: &FontFamilies, t: &Text) -> Option<Rc<LoadedFont>> {
        self.load(&file_for(fams, &t.font, t.bold, t.italic)?)
    }
}

// ============================================================================ разметка строк

#[derive(Clone, Debug)]
pub struct Seg {
    pub x: f64,
    pub text: String,
}

#[derive(Clone, Debug)]
pub struct FBox {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
    pub key: String,
}

#[derive(Clone, Debug)]
pub struct Line {
    pub top: f64,
    pub baseline: f64,
    pub segs: Vec<Seg>,
    pub formulas: Vec<FBox>,
}

#[derive(Clone, Debug, Default)]
pub struct Layout {
    pub lines: Vec<Line>,
    pub height: f64,
    pub ideal_width: f64,
    pub ascent: f64,
}

enum Tok {
    Word(String),
    Space(String),
    Formula(String, f64, f64, bool),
}

/// Разметка: перенос по словам (длинное слово — по буквам), выравнивание блока или всего текста.
pub fn layout(t: &Text, font: Option<&LoadedFont>, width: f64) -> Layout {
    let size = t.size;
    let (asc, desc) = match font {
        Some(f) => (f.ascender() * size, -f.descender() * size),
        None => (0.8 * size, 0.2 * size),
    };
    let wfn = |s: &str| -> f64 {
        match font {
            Some(f) => f.width(s, size),
            None => s.chars().count() as f64 * size * 0.5,
        }
    };
    let mut lines = Vec::new();
    let mut y = 0.0;
    let mut ideal: f64 = 0.0;
    for b in &t.blocks {
        // слова и пробелы
        let mut toks: Vec<Tok> = Vec::new();
        for r in &b.runs {
            match r {
                Run::T(s) => {
                    let mut cur = String::new();
                    let mut space = false;
                    for ch in s.chars() {
                        let is_sp = ch == ' ' || ch == '\t';
                        if !cur.is_empty() && is_sp != space {
                            toks.push(if space { Tok::Space(std::mem::take(&mut cur)) } else { Tok::Word(std::mem::take(&mut cur)) });
                        }
                        space = is_sp;
                        cur.push(if ch == '\t' { ' ' } else { ch });
                    }
                    if !cur.is_empty() {
                        toks.push(if space { Tok::Space(cur) } else { Tok::Word(cur) });
                    }
                }
                Run::F(k, disp) => {
                    let (fw, fh) = t
                        .formulas
                        .get(k)
                        .map(|f| {
                            let s = size / f.src_size.max(1.0);
                            (f.w * s, f.h * s)
                        })
                        .unwrap_or((10.0, 10.0));
                    toks.push(Tok::Formula(k.clone(), fw, fh, *disp));
                }
            }
        }
        // строки
        struct Item {
            w: f64,
            text: Option<String>,
            f: Option<(String, f64, bool)>,
            space: bool,
        }
        let mut cur: Vec<Item> = Vec::new();
        let mut cur_w = 0.0;
        let mut block_lines: Vec<Vec<Item>> = Vec::new();
        let flush = |cur: &mut Vec<Item>, cur_w: &mut f64, out: &mut Vec<Vec<Item>>| {
            // пробелы в конце строки не занимают места
            while cur.last().map(|i| i.space).unwrap_or(false) {
                cur.pop();
            }
            out.push(std::mem::take(cur));
            *cur_w = 0.0;
        };
        for tok in toks {
            match tok {
                Tok::Space(s) => {
                    let w = wfn(&s);
                    cur_w += w;
                    cur.push(Item { w, text: Some(s), f: None, space: true });
                }
                Tok::Word(s) => {
                    let w = wfn(&s);
                    if cur_w + w > width + 0.01 && !cur.is_empty() {
                        flush(&mut cur, &mut cur_w, &mut block_lines);
                    }
                    if w > width + 0.01 {
                        // слово длиннее строки — по буквам
                        let mut part = String::new();
                        let mut pw = 0.0;
                        for ch in s.chars() {
                            let cw = wfn(&ch.to_string());
                            if pw + cw > width && !part.is_empty() {
                                cur.push(Item { w: pw, text: Some(std::mem::take(&mut part)), f: None, space: false });
                                flush(&mut cur, &mut cur_w, &mut block_lines);
                                pw = 0.0;
                            }
                            part.push(ch);
                            pw += cw;
                        }
                        cur_w += pw;
                        cur.push(Item { w: pw, text: Some(part), f: None, space: false });
                    } else {
                        cur_w += w;
                        cur.push(Item { w, text: Some(s), f: None, space: false });
                    }
                }
                Tok::Formula(k, fw, fh, disp) => {
                    if cur_w + fw > width + 0.01 && !cur.is_empty() {
                        flush(&mut cur, &mut cur_w, &mut block_lines);
                    }
                    cur_w += fw;
                    cur.push(Item { w: fw, text: None, f: Some((k, fh, disp)), space: false });
                }
            }
        }
        flush(&mut cur, &mut cur_w, &mut block_lines);
        let align = b.align.clone().unwrap_or_else(|| t.align.clone());
        for items in block_lines {
            let lw: f64 = items.iter().map(|i| i.w).sum();
            ideal = ideal.max(lw);
            // высота строки: шрифт или формула (по центру относительно оси текста)
            let axis = asc - (asc + desc) / 2.0;
            let mut la = asc;
            let mut ld = desc;
            for it in &items {
                if let Some((_, fh, disp)) = &it.f {
                    if *disp {
                        la = la.max(*fh - desc);
                    } else {
                        la = la.max(axis + fh / 2.0);
                        ld = ld.max(fh / 2.0 - axis);
                    }
                }
            }
            let x0 = match align.as_str() {
                "center" => (width - lw) / 2.0,
                "right" => width - lw,
                _ => 0.0,
            }
            .max(0.0);
            let baseline = y + la;
            let mut segs: Vec<Seg> = Vec::new();
            let mut fbs = Vec::new();
            let mut x = x0;
            let mut cur_seg: Option<Seg> = None;
            for it in items {
                match (it.text, it.f) {
                    (Some(s), _) => {
                        match cur_seg.as_mut() {
                            Some(sg) => sg.text.push_str(&s),
                            None => cur_seg = Some(Seg { x, text: s }),
                        }
                        x += it.w;
                    }
                    (None, Some((k, fh, disp))) => {
                        if let Some(sg) = cur_seg.take() {
                            segs.push(sg);
                        }
                        let fy = if disp { baseline + desc - fh } else { baseline - axis - fh / 2.0 };
                        fbs.push(FBox { x, y: fy, w: it.w, h: fh, key: k });
                        x += it.w;
                    }
                    _ => {}
                }
            }
            if let Some(sg) = cur_seg.take() {
                segs.push(sg);
            }
            lines.push(Line { top: y, baseline, segs, formulas: fbs });
            y = baseline + ld;
        }
    }
    Layout { lines, height: y.max(size * 1.1), ideal_width: ideal, ascent: asc }
}
