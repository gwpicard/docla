#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": full-frame
#import "/lib/theme.typ": colour, type-style, space

#let full-image(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  let image-path = sec.at("image", default: content.at("image", default: ""))
  place(top + left, dx: full-frame.x, dy: full-frame.y, {
    fit-box("image", sec.id, full-frame.w, full-frame.h, {
      el("image", sec.id, width: full-frame.w, if image-path != "" {
        image(image-path, width: full-frame.w, height: full-frame.h, fit: "cover")
      })
    })
  })
  if paragraphs.len() > 0 {
    let caption = paragraphs.first()
    let height = space(7)
    place(top + left, dx: full-frame.x, dy: full-frame.y + full-frame.h - height, {
      fit-box("caption", sec.id, full-frame.w, height, {
        set text(..type-style("slides", "body"), fill: colour("ink"))
        el("caption", sec.id, width: full-frame.w, block(fill: colour("surface"), width: full-frame.w, inset: space(1), caption))
        if caption.len() > 100 { block(height: height) }
      })
    })
  }
})
