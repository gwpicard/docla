#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame
#import "/lib/theme.typ": colour, type-style, space

#let closing(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    fit-box("title", sec.id, content-frame.w, 100pt, {
      el("title", sec.id, {
        set text(..type-style("slides", "title"), fill: colour("ink"))
        sec.title
      })
    })
  })
  if paragraphs.len() > 0 {
    place(top + left, dx: content-frame.x, dy: content-frame.y + 180pt + space(3), {
      fit-box("spoken", sec.id, content-frame.w, 80pt, {
        el("spoken", sec.id, {
          set text(..type-style("slides", "body"), fill: colour("ink"))
          paragraphs.first()
        })
      })
    })
  }
})
