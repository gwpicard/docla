#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame, slide-title
#import "/lib/theme.typ": colour, type-style, space

#let quote(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  if sec.title != "" {
    slide-title(sec + (title: el("title", sec.id, sec.title)))
  }
  if paragraphs.len() > 0 {
    let quotation = paragraphs.first()
    place(top + left, dx: content-frame.x, dy: content-frame.y, {
      fit-box("quote", sec.id, content-frame.w, if quotation.len() > 200 { 0pt } else { content-frame.h - space(7) }, {
        set text(..type-style("slides", "title"), fill: colour("ink"))
        el("quote", sec.id, quotation, width: content-frame.w)
      })
    })
  }
  if source-line != "" {
    place(top + left, dx: content-frame.x, dy: content-frame.y + content-frame.h - space(6), {
      fit-box("source", sec.id, content-frame.w, space(6), {
        set text(..type-style("slides", "body"), fill: colour("ink"))
        el("source", sec.id, source-line, width: content-frame.w)
      })
    })
  }
})
