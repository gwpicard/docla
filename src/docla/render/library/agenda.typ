#import "/lib/marks.typ": section, el, fit-box
#import "/lib/frames.typ": content-frame, slide-title
#import "/lib/theme.typ": colour, type-style, space
#import "/lib/cite.typ": cite-keys

#let agenda(sec) = section(sec.id, {
  let items = sec.items
  let paragraphs = sec.paragraphs
  let source-line = sec.source_line
  let content = sec.at("content", default: (:))
  slide-title(sec + (title: el("title", sec.id, sec.title)))
  place(top + left, dx: content-frame.x, dy: content-frame.y, {
    fit-box("body", sec.id, content-frame.w, content-frame.h, {
      set block(above: 0pt, below: 0pt)
      for (i, item) in items.enumerate() {
        let citations = sec.at("citations", default: ()).at(i, default: ())
        block(width: content-frame.w, height: content-frame.h / 8, {
          set text(..type-style("slides", "body"), fill: colour("ink"))
          grid(
            columns: (space(5), 1fr),
            fit-box("number", sec.id, space(5), content-frame.h / 8, el("number", sec.id, str(i + 1))),
            fit-box("item", sec.id, content-frame.w - space(5), content-frame.h / 8, el("item", sec.id, [#item.body #cite-keys(citations)])),
          )
        })
      }
    })
  })
})
