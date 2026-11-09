// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Фоновый рендер страниц в отдельном потоке (а не в отдельном процессе, как в версии на Python):
//! один экземпляр MuPDF на всю программу, интерфейс не подвисает при прокрутке.

use std::collections::HashMap;
use std::sync::mpsc::{Receiver, Sender, TryRecvError, channel};
use std::thread;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Req {
    pub key: u64,
    pub ver: u64,
    pub idx: usize,
    pub zoom: f32,
}

pub struct Rendered {
    pub req: Req,
    pub width: u32,
    pub height: u32,
    pub rgb: Vec<u8>,
}

enum Msg {
    Load { key: u64, ver: u64, data: Vec<u8> },
    Close(u64),
    Want(Vec<Req>),
}

#[derive(Clone)]
pub struct RenderService {
    tx: Sender<Msg>,
}

impl RenderService {
    /// Запускает поток рендера. `deliver` вызывается из потока рендера для каждой готовой страницы.
    pub fn start<F>(deliver: F) -> Self
    where
        F: Fn(Rendered) + Send + 'static,
    {
        let (tx, rx) = channel();
        thread::Builder::new()
            .name("render".into())
            .spawn(move || worker(rx, deliver))
            .expect("render thread");
        RenderService { tx }
    }

    pub fn load(&self, key: u64, ver: u64, data: Vec<u8>) {
        let _ = self.tx.send(Msg::Load { key, ver, data });
    }

    pub fn close(&self, key: u64) {
        let _ = self.tx.send(Msg::Close(key));
    }

    /// Заменяет очередь: рисуются только эти страницы, в этом порядке (первые — важнее).
    pub fn want(&self, reqs: Vec<Req>) {
        let _ = self.tx.send(Msg::Want(reqs));
    }
}

fn worker<F: Fn(Rendered)>(rx: Receiver<Msg>, deliver: F) {
    let mut docs: HashMap<u64, (u64, mupdf::Document)> = HashMap::new();
    let mut queue: Vec<Req> = Vec::new();
    let mut done: Vec<Req> = Vec::new();
    loop {
        // ждём сообщение, если делать нечего; иначе только забираем накопившиеся
        let first = if queue.is_empty() {
            match rx.recv() {
                Ok(m) => Some(m),
                Err(_) => return,
            }
        } else {
            None
        };
        let mut msgs: Vec<Msg> = first.into_iter().collect();
        loop {
            match rx.try_recv() {
                Ok(m) => msgs.push(m),
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => return,
            }
        }
        for m in msgs {
            match m {
                Msg::Load { key, ver, data } => {
                    match mupdf::Document::from_bytes(&data, "application/pdf") {
                        Ok(d) => {
                            docs.insert(key, (ver, d));
                        }
                        Err(e) => eprintln!("render: не удалось открыть документ: {e}"),
                    }
                    done.retain(|r| r.key != key);
                }
                Msg::Close(key) => {
                    docs.remove(&key);
                    done.retain(|r| r.key != key);
                    queue.retain(|r| r.key != key);
                }
                Msg::Want(reqs) => {
                    // Запоминать только ещё востребованные запросы: интерфейс может
                    // освободить страницу и позже попросить её заново.
                    replace_requests(&mut queue, &mut done, reqs);
                }
            }
        }
        if queue.is_empty() {
            continue;
        }
        let req = queue.remove(0);
        let Some((ver, doc)) = docs.get(&req.key) else { continue };
        if *ver != req.ver {
            continue;
        }
        match render_page(doc, req.idx, req.zoom) {
            Ok((width, height, rgb)) => {
                done.push(req);
                if done.len() > 400 {
                    done.drain(..200);
                }
                deliver(Rendered { req, width, height, rgb });
            }
            Err(e) => eprintln!("render error (стр. {}): {e}", req.idx + 1),
        }
    }
}

fn replace_requests(queue: &mut Vec<Req>, done: &mut Vec<Req>, reqs: Vec<Req>) {
    done.retain(|r| reqs.contains(r));
    *queue = reqs.into_iter().filter(|r| !done.contains(r)).collect();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn evicted_page_can_be_rendered_again() {
        let page = Req { key: 1, ver: 1, idx: 0, zoom: 1.0 };
        let mut queue = vec![];
        let mut done = vec![page];
        replace_requests(&mut queue, &mut done, vec![page]);
        assert!(queue.is_empty());
        replace_requests(&mut queue, &mut done, vec![]);
        replace_requests(&mut queue, &mut done, vec![page]);
        assert_eq!(queue, vec![page]);
    }
}

fn render_page(doc: &mupdf::Document, idx: usize, zoom: f32) -> Result<(u32, u32, Vec<u8>), mupdf::Error> {
    let page = doc.load_page(idx as i32)?;
    let m = mupdf::Matrix::new_scale(zoom, zoom);
    let pix = page.to_pixmap(&m, &mupdf::Colorspace::device_rgb(), false, true)?;
    let (w, h) = (pix.width(), pix.height());
    let n = pix.n() as usize;
    let stride = pix.stride() as usize;
    let samples = pix.samples();
    let mut rgb = Vec::with_capacity(w as usize * h as usize * 3);
    for y in 0..h as usize {
        let row = &samples[y * stride..y * stride + w as usize * n];
        if n == 3 {
            rgb.extend_from_slice(row);
        } else {
            for px in row.chunks_exact(n) {
                rgb.extend_from_slice(&px[..3]);
            }
        }
    }
    Ok((w, h, rgb))
}
