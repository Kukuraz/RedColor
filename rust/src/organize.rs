use crate::{App, Image, ModelRc, Rgb8Pixel, SharedPixelBuffer, VecModel};

pub(crate) fn moved_order(n: usize, from: usize, to: usize) -> Vec<usize> {
    let mut order: Vec<_> = (0..n).collect();
    if from < n && to < n { let page = order.remove(from); order.insert(to, page); }
    order
}

impl App {
    pub(crate) fn refresh_organizer(&mut self) {
        let Some(c) = self.cur else { return };
        let n = self.docs[c].pages.len();
        let w = self.win();
        let selected = (w.get_org_selected().max(0) as usize).min(n.saturating_sub(1));
        let start = selected / 12 * 12;
        w.set_org_selected(selected as i32);
        w.set_org_start(start as i32);
        w.set_org_total(n as i32);
        let result = (|| -> Result<Vec<Image>, String> {
            // Render only the visible batch, at thumbnail resolution, including edits.
            let bytes = self.output_bytes(None)?;
            let doc = mupdf::Document::from_bytes(&bytes, "application/pdf").map_err(|e| e.to_string())?;
            let mut images = Vec::new();
            for i in start..(start + 12).min(n) {
                let p = &self.docs[c].pages[i];
                let zoom = (140.0 / p.w).min(165.0 / p.h);
                let (width, height, rgb) = crate::render::render_page(&doc, i, zoom).map_err(|e| e.to_string())?;
                images.push(Image::from_rgb8(SharedPixelBuffer::<Rgb8Pixel>::clone_from_slice(&rgb, width, height)));
            }
            Ok(images)
        })();
        match result {
            Ok(images) => { w.set_org_images(ModelRc::new(VecModel::from(images))); w.set_org_visible(true); }
            Err(e) => self.toast(&format!("Не удалось показать страницы: {e}")),
        }
    }

    pub(crate) fn organizer_action(&mut self, id: &str, target: i32) {
        let Some(c) = self.cur else { return };
        let n = self.docs[c].pages.len();
        let w = self.win();
        let selected = w.get_org_selected().max(0) as usize;
        if selected >= n { return; }
        match id {
            "close" => { w.set_org_visible(false); w.set_org_images(ModelRc::default()); self.go_to_page(selected as i64); return; }
            "select" => { if target >= 0 && (target as usize) < n { w.set_org_selected(target); } return; }
            "batch" => { w.set_org_selected(target.clamp(0, n.saturating_sub(1) as i32)); }
            "move" => {
                if target < 0 || target as usize >= n || target as usize == selected { return; }
                self.reorder(moved_order(n, selected, target as usize));
                w.set_org_selected(target);
            }
            "rotate" => self.rotate_pages(&[selected], target),
            "delete" => self.delete_pages(&[selected]),
            "undo" => self.action("edit.undo"),
            "insert" => self.insert_blank_page(selected + 1),
            _ => return,
        }
        self.refresh_organizer();
    }
}

#[cfg(test)]
mod tests {
    use super::moved_order;
    #[test]
    fn moving_keeps_every_page_exactly_once() {
        assert_eq!(moved_order(4, 0, 3), vec![1,2,3,0]);
        assert_eq!(moved_order(4, 3, 0), vec![3,0,1,2]);
        assert_eq!(moved_order(4, 2, 2), vec![0,1,2,3]);
        assert_eq!(moved_order(4, 9, 0), vec![0,1,2,3]);
    }
}
