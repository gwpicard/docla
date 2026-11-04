#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let chapter-break(sec) = {
  set page(fill: colour("dark"))
  section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    fit-box("title", sec.id, content-frame.w * 0.6, 110pt, {
      el("title", sec.id, {
        set text(..type-style("slides", "figure"), fill: colour("on-dark"))
        sec.title
      })
    })
  })
  if paragraphs.len() > 0 {
    place(top + left, dx: content-frame.x, dy: content-frame.y - space(5), {
      fit-box("number", sec.id, content-frame.w, space(5), {
        el("number", sec.id, {
          set text(..type-style("slides", "body"), fill: colour("on-dark"))
          paragraphs.first()
        })
      })
    })
  }
  for (i, item) in items.enumerate() {
    let citations = sec.at("citations", default: ()).at(i, default: ())
    place(top + left, dx: content-frame.x, dy: content-frame.y + 200pt, {
      fit-box("item", sec.id, content-frame.w, 40pt, {
        el("item", sec.id, {
          set text(..type-style("slides", "body"), fill: colour("on-dark"))
          [#item.body #cite-keys(citations)]
        })
      })
    })
  }
  })
}
